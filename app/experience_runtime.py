"""Local, authenticated orchestration; never execute a client-supplied command."""
from pathlib import Path
from urllib.parse import urlsplit, quote
import filecmp
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app import auth_common as auth

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / 'local_store' / 'agents'
LOCK = threading.RLock()
JOBS = {}
STOPPING = threading.Event()
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
logger=logging.getLogger(__name__)

def record_agent_lifecycle(agent_id,kind):
    try:
        from app import group_anp
        group_anp.record_activity(agent_id,kind)
    except Exception:
        logger.exception('Failed to record agent lifecycle event for %s',agent_id)

def guard(request: Request, response: Response):
    if not auth.current_session(request, auth.COOKIE_USER, 'user'):
        raise HTTPException(401, '请先登录')
    if request.client and request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
        raise HTTPException(403, '仅限本机工作台使用')
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, '不允许跨站操作')
    response.headers['Cache-Control'] = 'no-store'

router = APIRouter(prefix='/user/runtime', dependencies=[Depends(guard)])

def agent_dir(agent_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', agent_id):
        raise HTTPException(400, '智能体编号无效')
    path = (AGENTS / agent_id).resolve()
    if not path.is_relative_to(AGENTS.resolve()) or not (path / 'agent_manifest.json').is_file():
        raise HTTPException(404, '未找到已生成的智能体')
    # Reject redirected runtime directories before writing/installing anything.
    for child in ('openclaw_package', 'octopus_build', 'openclaw_package/state', 'openclaw_package/state/npm', 'openclaw_package/.env', 'openclaw_package/state/openclaw.json', 'octopus_build/.env', 'octopus_build/.web-venv'):
        if not (path / child).resolve().is_relative_to(path):
            raise HTTPException(400, '实例目录不能指向外部路径')
    return path

def package(path):
    return path / ('openclaw_package' if (path / 'openclaw_package').is_dir() else 'octopus_build')

def read_env(path):
    result = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                if k.strip() in {'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENCLAW_MODEL', 'OPENAI_MODEL', 'LLM_PROVIDER'}:
                    result[k.strip()] = v.strip().strip('"').strip("'")
    return result

def model_env(path, seen=None):
    """Resolve a complete local connection; never return credentials to the browser."""
    values=read_env(package(path)/'.env')
    if values.get('OPENAI_API_KEY'):return values,'instance'
    seen=set(seen or ())
    if path.name in seen:raise RuntimeError('主子智能体配置存在循环引用')
    seen.add(path.name)
    manifest=json.loads((path/'agent_manifest.json').read_text(encoding='utf-8'))
    parent=manifest.get('parent_phc_id')
    if parent:
        inherited,_=model_env(agent_dir(str(parent).replace(':','_')),seen)
        if inherited.get('OPENAI_API_KEY'):return inherited,'parent'
    kind='openclaw' if package(path).name=='openclaw_package' else 'octopus'
    defaults=read_env(ROOT/'agent_provider'/kind/'.env')
    if defaults.get('OPENAI_API_KEY') and defaults.get('OPENAI_BASE_URL') and (defaults.get('OPENAI_MODEL') or defaults.get('OPENCLAW_MODEL')):
        # Take URL/model/key together rather than sending a key to an unrelated URL.
        return defaults,'system'
    return values,'missing'

def provision_model(path):
    """Fill missing instance credentials from the existing local connection."""
    with LOCK:
        values,source=model_env(path)
        if source not in {'parent','system'} or not values.get('OPENAI_API_KEY'):return False
        env_path=package(path)/'.env'
        lines=env_path.read_text(encoding='utf-8-sig').splitlines() if env_path.exists() else []
        lines=[line for line in lines if line.split('=',1)[0].strip() not in values]
        env_path.write_text('\n'.join(lines+[f'{k}={v}' for k,v in values.items()])+'\n',encoding='utf-8')
        return True

def host_env():
    env = os.environ.copy()
    extra = []
    if os.name == 'nt':
        import winreg
        for hive, key in [(winreg.HKEY_CURRENT_USER, 'Environment'), (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    extra.append(winreg.QueryValueEx(handle, 'Path')[0])
                    for name in ('NVM_HOME','NVM_SYMLINK'):
                        try:
                            env[name]=winreg.QueryValueEx(handle,name)[0]
                        except OSError:
                            pass
            except OSError:
                pass
    lookup={key.upper():value for key,value in env.items()}
    extra=[re.sub(r'%([^%]+)%',lambda match:lookup.get(match[1].upper(),match[0]),value) for value in extra]
    env['PATH'] = os.pathsep.join([env.get('PATH', ''), *extra,env.get('NVM_SYMLINK','')])
    return env

def tools(env):
    node = shutil.which('node', path=env['PATH'])
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm', path=env['PATH'])
    cli = Path(npm).parent / 'node_modules/npm/bin/npm-cli.js' if npm else None
    if node and (not cli or not cli.is_file()):
        cli = Path(node).parent / 'node_modules/npm/bin/npm-cli.js'
    return node, cli if cli and cli.is_file() else None

def running(job):
    return job and job.get('process') and job['process'].poll() is None

def runtime_failure(pkg, code=None):
    """Classify local errors without exposing API keys or authentication URLs."""
    log_path = pkg/'web-runtime.log'
    tail = ''
    if log_path.exists():
        with log_path.open('rb') as stream:
            stream.seek(max(0, log_path.stat().st_size-24000))
            tail = stream.read().decode('utf-8', errors='replace').lower()
    if 'eaddrinuse' in tail or 'already listening' in tail:
        return '实例端口被占用或存在遗留网关。点击重试会清理本实例的遗留网关后重新启动。'
    if 'invalid config' in tail or 'config validation failed' in tail:
        return 'OpenClaw 配置校验失败，请检查模型配置；详细原因见本实例 web-runtime.log。'
    if 'cannot find module' in tail or 'modulenotfounderror' in tail:
        return '运行依赖不完整，请检查本实例依赖安装日志。'
    return f'智能体进程退出（退出码 {code}），详细原因已保存在本实例 web-runtime.log。'

def prepare_gateway(path):
    from app.deletion_review import stop_orphan_gateway
    stop_orphan_gateway(path)

def reserve_port(port):
    """Windows default bind can succeed on a port another process is using."""
    sock=socket.socket()
    try:
        if os.name=='nt': sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        sock.bind(('127.0.0.1',port))
        return sock.getsockname()[1]
    finally:
        sock.close()

def snapshot(agent_id):
    path = agent_dir(agent_id)
    env,source = model_env(path)
    with LOCK:
        job = JOBS.get(agent_id, {})
        if job.get('stage') == 'ready' and not running(job):
            job.update(stage='error', message=runtime_failure(package(path),job['process'].poll() if job.get('process') else None), url=None)
        return {'success': True, 'agent_id': agent_id, 'stage': job.get('stage', 'idle'),
                'message': job.get('message', '准备好后，点击部署并启动。'),
                'url': job.get('url') if job.get('stage') == 'ready' else None,
                'auto_restarts': job.get('restarts',0),
                'model_config_source':source,
                'last_health_check': job.get('last_health_check'),
                'model': env.get('OPENCLAW_MODEL', env.get('OPENAI_MODEL', '')),
                'base_url': env.get('OPENAI_BASE_URL', ''), 'key_configured': bool(env.get('OPENAI_API_KEY')),
                'agent_type': 'openclaw' if package(path).name == 'openclaw_package' else 'octopus'}

@router.get('/{agent_id}/status')
def status(agent_id: str):
    return snapshot(agent_id)

class ModelConfig(BaseModel):
    api_key: str = Field(default='', max_length=4096)
    base_url: str = Field(max_length=2048)
    model: str = Field(min_length=1, max_length=200)

@router.post('/{agent_id}/model')
def model_config(agent_id: str, config: ModelConfig):
    path = agent_dir(agent_id)
    if any('\n' in x or '\r' in x for x in (config.api_key, config.base_url, config.model)):
        raise HTTPException(400, '配置不能包含换行')
    if urlsplit(config.base_url).scheme not in {'http', 'https'} or not urlsplit(config.base_url).hostname:
        raise HTTPException(400, '请填写有效的模型服务地址')
    with LOCK:
        if JOBS.get(agent_id, {}).get('stage') in {'checking', 'installing', 'starting', 'recovering', 'ready'}:
            raise HTTPException(409, '请先停止实例，再修改模型配置')
        pkg = package(path)
        p = pkg / '.env'
        values,_ = model_env(path)
        if config.api_key:
            values['OPENAI_API_KEY'] = config.api_key.strip()
        values['OPENAI_BASE_URL'] = config.base_url.strip()
        values['OPENCLAW_MODEL' if pkg.name == 'openclaw_package' else 'OPENAI_MODEL'] = config.model.strip()
        lines = p.read_text(encoding='utf-8-sig').splitlines() if p.exists() else []
        lines = [line for line in lines if line.split('=', 1)[0].strip() not in values]
        p.write_text('\n'.join(lines + [f'{k}={v}' for k, v in values.items()]) + '\n', encoding='utf-8')
        if pkg.name == 'openclaw_package':
            cfg_path = pkg / 'state/openclaw.json'
            cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
            # This project's templates route compatible models through provider openai.
            provider = cfg.setdefault('models', {}).setdefault('providers', {}).setdefault('openai', {})
            provider['baseUrl'] = values['OPENAI_BASE_URL']
            provider['apiKey'] = '${OPENAI_API_KEY}'
            model_id = config.model.removeprefix('openai/')
            existing = provider.get('models', [])
            selected = next((m for m in existing if m.get('id') == model_id), None)
            provider['models'] = [selected or {'id': model_id, 'name': model_id}]
            cfg.setdefault('agents', {}).setdefault('defaults', {})['model'] = {'primary': 'openai/' + model_id}
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'success': True}

def stage(job, name, message):
    with LOCK:
        job.update(stage=name, message=message)

def repair_octopus_package(pkg):
    """Restore absent generated runtime assets, preserving instance configuration."""
    source=ROOT/'agent_provider/octopus'
    restored=[]
    candidates=['pyproject.toml','README.md','web']
    if not (pkg/'octopus').exists():candidates.append('octopus')
    for name in candidates:
        target=pkg/name
        if target.exists():continue
        if not target.resolve().is_relative_to(pkg.resolve()):raise RuntimeError('运行文件路径无效')
        original=source/name
        if not original.exists():raise RuntimeError('项目模板缺少 Octopus 运行文件，请恢复 agent_provider/octopus')
        if original.is_dir():
            shutil.copytree(original,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env','*.log'))
        else:shutil.copy2(original,target)
        restored.append(name)
    if not (pkg/'octopus/octopus.py').is_file():raise RuntimeError('Octopus 运行包不完整，缺少 octopus/octopus.py')
    managed_files=('web/index.html','web/script.js','octopus/api/chat_router.py','octopus/api/auth_middleware.py')
    for name in managed_files:
        original=source/name
        if not original.is_file():
            continue
        target=pkg/name
        if not target.resolve().is_relative_to(pkg.resolve()):
            raise RuntimeError('运行文件路径无效')
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.is_file() or not filecmp.cmp(original,target,shallow=False):
            shutil.copy2(original,target)
    if any(name in restored for name in ('pyproject.toml','octopus')):(pkg/'.web-dependencies-ready').unlink(missing_ok=True)
    return restored


def stop_octopus_using_venv(python):
    """Stop only stale Octopus processes using this instance's interpreter."""
    if os.name != 'nt':
        return
    escaped = str(python.resolve()).replace("'", "''")
    script = ("try { Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | "
              f"Where-Object {{ $_.Path -eq '{escaped}' }} | "
              "Stop-Process -Force -ErrorAction Stop; exit 0 } catch { exit 1 }")
    result = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=HIDDEN, timeout=20)
    if result.returncode:
        raise RuntimeError('旧 Octopus 进程仍占用运行环境，请关闭该实例后重试。')

def run_install(args, cwd, env, job):
    # Never pass model credentials to package install scripts.
    clean = {k:v for k,v in env.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
    with (cwd / 'web-install.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(args, cwd=cwd, env=clean, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=HIDDEN)
        with LOCK:
            job['installer'] = process
        try:
            code = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            kill(process)
            raise RuntimeError('安装超过 30 分钟，请检查网络后重试。')
        if code:
            log.flush()
            failure = (cwd / 'web-install.log').read_text(encoding='utf-8', errors='replace')
            if 'pip' in args and 'ProxyError' in failure and not STOPPING.is_set() and clean.get('NO_PROXY') != '*':
                direct = {k:v for k,v in clean.items() if k.upper() not in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','PIP_PROXY','NO_PROXY'}}
                direct['NO_PROXY'] = '*'
                log.write('\nProxy connection failed; retrying once without proxy.\n')
                log.flush()
                process = subprocess.Popen(args, cwd=cwd, env=direct, stdout=log, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, creationflags=HIDDEN)
                with LOCK:
                    job['installer'] = process
                try:
                    code = process.wait(timeout=1800)
                except subprocess.TimeoutExpired:
                    kill(process)
                    raise RuntimeError('直连安装超时，请检查网络后重试。')
            if code:
                raise RuntimeError('依赖安装失败，请检查网络和运行环境；管理员可查看实例内 web-install.log。')
        if STOPPING.is_set():
            raise RuntimeError('用户服务已关闭，请重新启动后重试。')

def kill(process):
    if process and process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=HIDDEN, timeout=15)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

def launch(agent_id, job):
    process = None
    try:
        path = agent_dir(agent_id)
        pkg = package(path)
        env = host_env()
        values,config_source = model_env(path)
        if not values.get('OPENAI_API_KEY'):
            raise RuntimeError('本机未配置可用的模型密钥，请管理员配置平台默认模型连接。')
        env.update(values)
        configured_port = 0
        if pkg.name == 'openclaw_package':
            config = json.loads((pkg/'state/openclaw.json').read_text(encoding='utf-8-sig'))
            configured_port = int(config.get('gateway', {}).get('port', 0))
            stage(job,'checking','正在检查并清理本实例的遗留网关…')
            prepare_gateway(path)
        for attempt in range(6):
            try:
                port = reserve_port(configured_port)
                break
            except OSError:
                if attempt==5:
                    raise RuntimeError('配置端口仍被其他进程占用，未停止无关服务。请管理员检查端口冲突。')
                time.sleep(1)
        url = f'http://127.0.0.1:{port}'
        if pkg.name == 'openclaw_package':
            node, npm = tools(env)
            if not node or not npm or not shutil.which('git', path=env['PATH']):
                raise RuntimeError('主机缺少 Node.js/npm 或 Git。请在连接设置中完成环境安装，再重试。')
            prefix = pkg / 'state/npm'
            entry = prefix / 'node_modules/openclaw/openclaw.mjs'
            codex = prefix / 'node_modules/@openai/codex/bin/codex.js'
            if not entry.exists() or not codex.exists():
                if job.get('auto_recovery'):
                    raise RuntimeError('自动恢复发现运行组件缺失，请手动重新部署。')
                stage(job, 'installing', '正在下载安装智能体运行组件，首次安装可能需要几分钟…')
                run_install([node, str(npm), 'install', '--engine-strict', '--prefix', str(prefix), 'openclaw', '@openai/codex'], pkg, env, job)
            cfg_path = pkg / 'state/openclaw.json'
            cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
            cfg.setdefault('gateway', {})['port'] = port
            if config_source in {'parent','system'}:
                provider=cfg.setdefault('models',{}).setdefault('providers',{}).setdefault('openai',{})
                provider.update(baseUrl=values['OPENAI_BASE_URL'],apiKey='${OPENAI_API_KEY}')
                model=values.get('OPENCLAW_MODEL',values.get('OPENAI_MODEL','')).removeprefix('openai/')
                provider['models']=[{'id':model,'name':model}]
                cfg.setdefault('agents',{}).setdefault('defaults',{})['model']={'primary':'openai/'+model}
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
            token = cfg.get('gateway', {}).get('auth', {}).get('token')
            if not isinstance(token, str) or not token or token.startswith('${'):
                raise RuntimeError('实例缺少有效的网关认证配置，请重新生成。')
            env.update(OPENCLAW_STATE_DIR=str(pkg/'state'), OPENCLAW_CONFIG_PATH=str(cfg_path),
                       OPENCLAW_BINDING_PATH=str(pkg/'openclaw_binding.json'), PERSONAL_AGENT_MANIFEST=str(path/'agent_manifest.json'),
                       OPENCLAW_CODEX_APP_SERVER_BIN=str(codex), NODE_PATH=str(prefix/'node_modules'))
            args = [node, str(entry), 'gateway', 'run', '--port', str(port), '--bind', 'loopback']
            url += '/#token=' + quote(token, safe='')
        else:
            repair_octopus_package(pkg)
            python = pkg / '.web-venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            marker = pkg / '.web-dependencies-ready'
            if not python.exists() or not (pkg/'.web-venv/pyvenv.cfg').exists():
                if job.get('auto_recovery'):
                    raise RuntimeError('自动恢复发现 Python 运行环境缺失，请手动重新部署。')
                stage(job, 'installing', '正在准备 Python 环境并安装智能体依赖…')
                if python.exists():
                    stop_octopus_using_venv(python)
                run_install([sys.executable, '-m', 'venv', str(pkg/'.web-venv')], pkg, env, job)
            if not marker.exists():
                if job.get('auto_recovery'):
                    raise RuntimeError('自动恢复发现 Python 依赖未安装完成，请手动重新部署。')
                stage(job, 'installing', '正在安装智能体依赖…')
                # An interrupted install can leave a usable venv without pip or
                # the marker. Do not recreate it in place: on Windows a former
                # instance may still hold Scripts/python.exe open.
                stop_octopus_using_venv(python)
                pip_probe = subprocess.run([str(python), '-m', 'pip', '--version'], cwd=pkg,
                                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=HIDDEN, timeout=30)
                if pip_probe.returncode:
                    run_install([str(python), '-m', 'ensurepip', '--upgrade'], pkg, env, job)
                run_install([str(python), '-m', 'pip', 'install', '-e', str(pkg)], pkg, env, job)
                marker.touch()
            env.update(PYTHONPATH=str(pkg), DOTENV_PATH=str(pkg/'.env'), OCTOPUS_ALLOWED_AGENTS_PATH=str(path/'active_agents.json'),
                       ANP_SDK_ENABLED='false', MODEL_PROVIDER='openai', DEBUG='false')
            from app import group_anp
            env.update(group_anp.prepare(agent_id,port))
            args = [str(python), str(ROOT/'app/octopus_group_runtime.py'), str(port)]
        if STOPPING.is_set():
            raise RuntimeError('用户服务已关闭，请重试。')
        stage(job, 'starting', '组件已就绪，正在启动并等待服务响应…')
        with (pkg / 'web-runtime.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(args, cwd=pkg, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, creationflags=HIDDEN)
        with LOCK:
            job['process'] = process
        with httpx.Client(trust_env=False, timeout=2) as client:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(runtime_failure(pkg,process.poll()))
                try:
                    probe = '/readyz' if pkg.name=='openclaw_package' else '/'
                    response = client.get(f'http://127.0.0.1:{port}{probe}')
                    ready = response.status_code==200 and (pkg.name!='openclaw_package' or response.json().get('ready') is True)
                    if ready and process.poll() is None:
                        record_agent_lifecycle(agent_id,'agent_started')
                        with LOCK:
                            job.update(stage='ready', message='智能体页面已就绪，后台健康巡检已启用。模型调用结果以实际回复为准。', url=url,
                                       probe_url=f'http://127.0.0.1:{port}{probe}',probe_json=pkg.name=='openclaw_package',
                                       desired_running=True,ever_ready=True,health_failures=0,healthy_since=time.monotonic())
                        return
                except (httpx.HTTPError,ValueError):
                    pass
                time.sleep(1)
        raise RuntimeError('启动等待超时，请检查运行环境后重试。')
    except Exception as exc:
        kill(process)
        stage(job, 'error', str(exc) if isinstance(exc, RuntimeError) else '部署发生异常，请联系管理员检查本地实例配置。')

@router.post('/{agent_id}/start')
def start(agent_id: str):
    agent_dir(agent_id)
    with LOCK:
        snapshot(agent_id)
        if JOBS.get(agent_id, {}).get('stage') not in {'checking','installing','starting','recovering','ready'}:
            previous=JOBS.get(agent_id,{})
            previous['desired_running']=False
            was_running=running(previous)
            kill(previous.get('process'))
            if was_running:record_agent_lifecycle(agent_id,'agent_stopped')
            job = {'agent_id':agent_id,'stage':'checking', 'desired_running':True,'restarts':0, 'message':'正在检查实例和模型配置…'}
            JOBS[agent_id] = job
            threading.Thread(target=launch, args=(agent_id, job), daemon=True).start()
    return snapshot(agent_id)

@router.post('/{agent_id}/stop')
def stop(agent_id: str):
    agent_dir(agent_id)
    with LOCK:
        job = JOBS.get(agent_id, {})
        if job.get('stage') in {'checking', 'installing', 'starting'}:
            raise HTTPException(409, '部署仍在进行，请等待完成')
        job['desired_running']=False
        was_running=running(job)
        kill(job.get('process'))
        job.update(stage='idle', message='实例已停止，可修改模型配置或重新启动。', url=None)
    if was_running:record_agent_lifecycle(agent_id,'agent_stopped')
    return snapshot(agent_id)

def shutdown():
    STOPPING.set()
    with LOCK:
        for job in JOBS.values():
            kill(job.get('installer'))
            was_running=running(job)
            kill(job.get('process'))
            if was_running:record_agent_lifecycle(job.get('agent_id',''))
    from app import group_anp
    group_anp.shutdown()
