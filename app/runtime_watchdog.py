"""Bounded local health supervision; never sends model requests."""
import logging
import threading
import time
import httpx

log = logging.getLogger(__name__)
INTERVAL = 15
FAILURE_THRESHOLD = 3
MAX_RESTARTS = 3
STABLE_RESET_SECONDS = 600
_thread = None

def probe(job):
    url = job.get('probe_url')
    if not url:
        return False
    try:
        with httpx.Client(trust_env=False,timeout=3) as client:
            response=client.get(url)
            return response.status_code==200 and (not job.get('probe_json') or response.json().get('ready') is True)
    except (httpx.HTTPError,ValueError):
        return False

def inspect_once(rt, clock=time.monotonic, restart=None):
    """Probe outside the lock, then recheck identity to avoid stopping a new job."""
    with rt.LOCK:
        candidates=list(rt.JOBS.items())
    for agent_id,job in candidates:
        if rt.STOPPING.is_set():return
        with rt.LOCK:
            if rt.JOBS.get(agent_id) is not job or not job.get('desired_running') or not job.get('ever_ready'):
                continue
            state=job.get('stage')
            if state not in {'ready','error','recovering'}:continue
            if state=='recovering':
                if clock()<job.get('retry_at',0):continue
                # Stop only the process tracked for this instance.
                was_running=bool(job.get('process') and job['process'].poll() is None)
                rt.kill(job.get('process'))
                if was_running:rt.record_agent_lifecycle(agent_id,'agent_stopped')
                job.update(stage='starting',url=None,auto_recovery=True,
                           message=f"正在自动恢复（第 {job['restarts']} 次）…")
                if restart:
                    restart(agent_id,job)
                else:
                    threading.Thread(target=rt.launch,args=(agent_id,job),daemon=True).start()
                continue
            process=job.get('process')
        healthy=bool(process and process.poll() is None and probe(job))
        with rt.LOCK:
            if rt.JOBS.get(agent_id) is not job or not job.get('desired_running') or job.get('stage')!=state:
                continue
            job['last_health_check']=time.time()
            if healthy:
                job['health_failures']=0
                job.setdefault('healthy_since',clock())
                if clock()-job['healthy_since']>=STABLE_RESET_SECONDS:job['restarts']=0
                continue
            job.pop('healthy_since',None)
            job['health_failures']=job.get('health_failures',0)+1
            if job['health_failures']<FAILURE_THRESHOLD:continue
            if job.get('restarts',0)>=MAX_RESTARTS:
                job.update(stage='error',desired_running=False,url=None,
                           message='自动恢复已达 3 次上限。请检查运行日志、模型配置或端口，再手动重试。')
                log.warning('Runtime recovery exhausted agent=%s',agent_id)
                continue
            attempt=job.get('restarts',0)+1
            delay=min(10*2**(attempt-1),60)
            job.update(stage='recovering',restarts=attempt,retry_at=clock()+delay,
                       health_failures=0,url=None,message=f'连续 3 次健康检查未通过，将在约 {delay} 秒后自动恢复（{attempt}/3）。')
            log.warning('Runtime recovery scheduled agent=%s attempt=%s',agent_id,attempt)

def start(rt):
    global _thread
    if _thread and _thread.is_alive():return
    rt.STOPPING.clear()
    def loop():
        while not rt.STOPPING.wait(INTERVAL):
            try:inspect_once(rt)
            except Exception:log.exception('Runtime health check failed')
    _thread=threading.Thread(target=loop,name='runtime-health-watchdog',daemon=True)
    _thread.start()

def join():
    if _thread and _thread is not threading.current_thread():_thread.join(timeout=5)
