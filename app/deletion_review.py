"""Durable deletion approvals shared by the local User and TP services."""
import hashlib
import json
import re
import sqlite3
import socket
import os
import subprocess
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app import auth_common as auth
from app import experience_runtime as rt

DB = rt.ROOT/'local_store/deletion_reviews.sqlite3'
log = logging.getLogger(__name__)

def archive_instance(source, target):
    # Windows can release directory handles slightly after taskkill reports exit.
    for attempt in range(5):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.5 * (attempt + 1))

def stop_orphan_gateway(source):
    """Stop only Node gateways whose CLI entry is inside this approved instance."""
    if os.name != 'nt':
        return
    entry = source/'openclaw_package/state/npm/node_modules/openclaw/openclaw.mjs'
    if not entry.exists():
        return
    script = "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction Stop | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],
                            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,creationflags=rt.HIDDEN)
    if result.returncode:
        raise RuntimeError('无法检查实例遗留进程，请使用有进程查询权限的账号启动用户服务后重试。')
    processes = json.loads(result.stdout.strip() or '[]')
    if isinstance(processes,dict): processes=[processes]
    expected = re.escape(str(entry).replace('/','\\'))
    pattern = re.compile(r'(?:^|\s)"?'+expected+r'"?\s+gateway\s+run(?:\s|$)',re.I)
    for process in processes:
        command = (process.get('CommandLine') or '').replace('/','\\')
        if not pattern.search(command): continue
        pid = int(process['ProcessId'])
        stopped = subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,
                                 timeout=20,creationflags=rt.HIDDEN)
        if stopped.returncode:
            raise RuntimeError('该实例的遗留网关未能停止，请关闭该实例的网关窗口后重试。')

def owns_octopus_process(source, process):
    """Require an exact instance Python executable, never an ID substring."""
    package = source / 'octopus_build'
    expected = {str(package / folder / 'Scripts' / name).replace('/', '\\').casefold()
                for folder in ('.web-venv', '.venv', 'venv')
                for name in ('python.exe', 'pythonw.exe')}
    executable = (process.get('ExecutablePath') or '').replace('/', '\\').casefold()
    command = process.get('CommandLine') or ''
    first = re.match(r'^\s*(?:"([^"]+)"|(\S+))', command)
    command_exe = ((first.group(1) or first.group(2)) if first else '').replace('/', '\\').casefold()
    return executable in expected or command_exe in expected

def stop_orphan_octopus(source):
    if os.name != 'nt' or not (source / 'octopus_build').is_dir():
        return
    script = "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" -ErrorAction Stop | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,creationflags=rt.HIDDEN)
    if result.returncode:
        raise RuntimeError('无法查询 Octopus 遗留进程，请检查用户服务的进程查询权限后重试。')
    processes = json.loads(result.stdout.strip() or '[]')
    if isinstance(processes, dict): processes = [processes]
    for process in processes:
        if not owns_octopus_process(source, process): continue
        pid = int(process['ProcessId'])
        if pid == os.getpid(): continue
        stopped = subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,
            timeout=20,creationflags=rt.HIDDEN)
        if stopped.returncode:
            # A parent taskkill may have already stopped this child process.
            check = subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
                f'if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 1 }}'],
                capture_output=True,timeout=20,creationflags=rt.HIDDEN)
            if check.returncode:
                raise RuntimeError('Octopus 遗留进程未能停止，请检查进程权限后重试。')
@contextmanager
def db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB,timeout=15)
    conn.row_factory=sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, agent_id TEXT, name TEXT, owner TEXT, reason TEXT, status TEXT, created_at TEXT, reviewer TEXT, comment TEXT, fingerprint TEXT)')
    if 'last_error' not in {row[1] for row in conn.execute('PRAGMA table_info(requests)')}:
        conn.execute("ALTER TABLE requests ADD COLUMN last_error TEXT DEFAULT ''")
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def now(): return datetime.now(timezone.utc).isoformat()
def records(owner=None):
    with db() as c:
        rows=c.execute('SELECT * FROM requests'+(' WHERE owner=?' if owner else '')+' ORDER BY created_at DESC', (owner,) if owner else ()).fetchall()
    return [{k:v for k,v in dict(row).items() if k!='fingerprint'} for row in rows]

def frozen(agent_id):
    with db() as c:
        return bool(c.execute("SELECT 1 FROM requests WHERE agent_id=? AND status IN ('pending','approved','executing','failed')",(agent_id,)).fetchone())

def tp_guard(request:Request,response:Response):
    session=auth.current_session(request,auth.COOKIE_TP,'tp')
    if not session: raise HTTPException(401,'请登录审核端')
    if request.headers.get('origin') not in {None,str(request.base_url).rstrip('/')}:
        raise HTTPException(403,'不允许跨站审批')
    response.headers['Cache-Control']='no-store'
    return session

user_router=APIRouter(prefix='/user/deletions',dependencies=[Depends(rt.guard)])
tp_router=APIRouter(prefix='/v1/tp/deletions',dependencies=[Depends(tp_guard)])

class Apply(BaseModel):
    agent_id:str=Field(max_length=120)
    reason:str=Field(min_length=1,max_length=500)

class Decision(BaseModel):
    decision:str
    comment:str=Field(default='',max_length=500)

def assert_no_children(agent_id):
    from app import user_app as legacy
    for group in legacy.list_agent_groups():
        if group.parent_agent_id.replace(':','_')==agent_id and group.sub_agents:
            raise HTTPException(409,'主智能体仍有关联子智能体，请先申请删除所有子智能体')

@user_router.get('')
def mine(request:Request):
    return {'success':True,'items':records(auth.public_session(auth.current_session(request,auth.COOKIE_USER,'user'))['username'])}

@user_router.post('')
def apply(body:Apply,request:Request):
    path=rt.agent_dir(body.agent_id)
    assert_no_children(body.agent_id)
    if not body.reason.strip(): raise HTTPException(400,'请填写删除原因')
    manifest=path/'agent_manifest.json'
    content=manifest.read_bytes()
    owner=auth.public_session(auth.current_session(request,auth.COOKIE_USER,'user'))['username']
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute("SELECT id FROM requests WHERE agent_id=? AND status IN ('pending','approved','executing','failed')",(body.agent_id,)).fetchone()
        if old: return {'success':True,'request_id':old['id']}
        rid=uuid.uuid4().hex
        c.execute('INSERT INTO requests (id,agent_id,name,owner,reason,status,created_at,reviewer,comment,fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,body.agent_id,json.loads(content).get('name',body.agent_id),owner,body.reason.strip(),'pending',now(),'','',hashlib.sha256(content).hexdigest()))
    return {'success':True,'request_id':rid}

@tp_router.get('')
def queue(): return {'success':True,'items':records()}

@tp_router.post('/{rid}/review')
def review(rid:str,body:Decision,session=Depends(tp_guard)):
    if body.decision not in {'approved','rejected'}: raise HTTPException(400,'审批决定无效')
    with db() as c:
        cur=c.execute("UPDATE requests SET status=?,reviewer=?,comment=? WHERE id=? AND status='pending'",(body.decision,auth.public_session(session)['username'],body.comment,rid))
        if not cur.rowcount: raise HTTPException(409,'申请不存在或已审批，请刷新列表')
    return {'success':True}

@tp_router.post('/{rid}/reopen')
def reopen(rid:str,session=Depends(tp_guard)):
    """Create a new review, preserving the rejected decision as history."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
        if not old or old['status']!='rejected':
            raise HTTPException(409,'仅被拒绝的申请可以重新送审')
        active=c.execute("SELECT id FROM requests WHERE agent_id=? AND status IN ('pending','approved','executing','failed')",(old['agent_id'],)).fetchone()
        if active: return {'success':True,'request_id':active['id']}
        path=rt.agent_dir(old['agent_id'])
        assert_no_children(old['agent_id'])
        content=(path/'agent_manifest.json').read_bytes()
        if hashlib.sha256(content).hexdigest()!=old['fingerprint']:
            raise HTTPException(409,'实例信息已变化，请用户重新申请删除')
        new_id=uuid.uuid4().hex
        actor=auth.public_session(session)['username']
        c.execute('INSERT INTO requests (id,agent_id,name,owner,reason,status,created_at,reviewer,comment,fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (new_id,old['agent_id'],old['name'],old['owner'],old['reason'],'pending',now(),'','',old['fingerprint']))
        # Record who reopened the decision without altering the original rejection.
        c.execute('CREATE TABLE IF NOT EXISTS reconsiderations (request_id TEXT PRIMARY KEY, previous_id TEXT, actor TEXT, created_at TEXT)')
        c.execute('INSERT INTO reconsiderations VALUES (?,?,?,?)',(new_id,rid,actor,now()))
    return {'success':True,'request_id':new_id}


@user_router.post('/{rid}/execute')
def execute(rid:str,request:Request):
    owner=auth.public_session(auth.current_session(request,auth.COOKIE_USER,'user'))['username']
    return execute_approved(rid, owner)

def execute_approved(rid: str, owner: str):
    """Execute only an existing approval belonging to this owner."""
    from app import user_app as legacy
    from app.experience_subagents import CREATE_LOCK
    with CREATE_LOCK,rt.LOCK:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM requests WHERE id=? AND owner=?',(rid,owner)).fetchone()
            if not row: raise HTTPException(404,'申请不存在')
            if row['status']=='deleted': return {'success':True,'status':'deleted'}
            if row['status'] not in {'approved','failed'}: raise HTTPException(409,'删除须先通过审核端审批')
            agent_id=row['agent_id']
            assert_no_children(agent_id)
            job=rt.JOBS.get(agent_id,{})
            if job.get('stage') in {'checking','installing','starting'}: raise HTTPException(409,'实例正在部署，请稍后执行删除')
            c.execute("UPDATE requests SET status='executing' WHERE id=?",(rid,))
        try:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',agent_id): raise RuntimeError('invalid id')
            source=(rt.AGENTS/agent_id).resolve()
            archive_root=(rt.ROOT/'local_store/deleted_agents').resolve()
            target=(archive_root/rid).resolve()
            if not source.is_relative_to(rt.AGENTS.resolve()) or not target.is_relative_to(archive_root): raise RuntimeError('invalid path')
            existing=source if source.exists() else target
            if hashlib.sha256((existing/'agent_manifest.json').read_bytes()).hexdigest()!=row['fingerprint']:
                raise RuntimeError('实例清单在审批后发生变化，不能使用旧审批删除，请联系管理员核对。')
            rt.kill(job.get('process'))
            stop_orphan_octopus(source)
            stop_orphan_gateway(source)
            config=existing/'openclaw_package/state/openclaw.json'
            if config.exists():
                port=json.loads(config.read_text(encoding='utf-8-sig')).get('gateway',{}).get('port')
                if port:
                    with socket.socket() as sock:
                        sock.settimeout(1)
                        if sock.connect_ex(('127.0.0.1',int(port)))==0:
                            raise RuntimeError('实例配置端口仍被占用。已停止能确认归属的网关，请检查其他启动窗口后重试。')
            archive_root.mkdir(parents=True,exist_ok=True)
            if source.exists(): archive_instance(source,target)
            for group in legacy.list_agent_groups():
                group.sub_agents=[s for s in group.sub_agents if s.phc_id.replace(':','_')!=agent_id]
                legacy.save_agent_group(group)
            snapshot=Path(legacy._last_agent_path())
            if owner != 'user':
                account = hashlib.sha256(owner.encode('utf-8')).hexdigest()
                snapshot = rt.ROOT/'local_store/user_state'/account/'last_agent.json'
            if snapshot.exists():
                data=json.loads(snapshot.read_text(encoding='utf-8'))
                if str((data.get('phc') or {}).get('id','')).replace(':','_')==agent_id:
                    snapshot.unlink()
            rt.JOBS.pop(agent_id,None)
            with db() as c: c.execute("UPDATE requests SET status='deleted',last_error='' WHERE id=?",(rid,))
            return {'success':True,'status':'deleted'}
        except Exception as exc:
            log.exception('Approved deletion failed request=%s agent=%s',rid,agent_id)
            message = str(exc) if isinstance(exc,RuntimeError) else ('实例目录仍被程序占用或缺少文件权限，请关闭使用该目录的窗口后重试。' if isinstance(exc,PermissionError) else '实例归档或记录清理失败，具体异常已记录到用户服务日志。')
            with db() as c: c.execute("UPDATE requests SET status='failed',last_error=? WHERE id=?",(message,rid))
            raise HTTPException(409,message)
