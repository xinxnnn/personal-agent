"""Optional local smoke test against already installed OpenClaw (no model calls)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
import httpx
from app import experience_runtime as rt, group_anp

class SupervisorTests(unittest.TestCase):
    def test_real_openclaw_pair_and_lifecycle(self):
        env=rt.host_env();node,_=rt.tools(env)
        entries=list(rt.AGENTS.glob('*/openclaw_package/state/npm/node_modules/openclaw/openclaw.mjs'))
        if not node or not entries:self.skipTest('Requires locally installed Node and OpenClaw')
        http,ws=group_anp.ensure_gateway();self.addCleanup(group_anp.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'anp_groups/parent.json';registry.parent.mkdir()
            members={name:{'port':rt.reserve_port(0),'token':name+'-secret'} for name in ('parent','child')}
            registry.write_text(json.dumps({'gateway_http':f'http://127.0.0.1:{http}','gateway_ws':f'ws://127.0.0.1:{ws}','members':members}))
            processes=[];logs=[];node_ports={}
            try:
                for name,info in members.items():
                    folder=root/'agents'/name;folder.mkdir(parents=True);(folder/'agent_manifest.json').write_text('{}')
                    port=rt.reserve_port(0);node_ports[name]=port
                    config=folder/'openclaw.json';config.write_text(json.dumps({'gateway':{'mode':'local','bind':'loopback','port':port,'auth':{'mode':'token','token':'test-local-gateway-token-123456'}}}))
                    clean={k:v for k,v in env.items() if not any(part in k.upper() for part in ('API_KEY','SECRET','TOKEN','PASSWORD'))}
                    clean.update(OPENCLAW_CONFIG_PATH=str(config),OPENCLAW_STATE_DIR=str(folder/'state'),OCTOPUS_GROUP_FILE=str(registry),OCTOPUS_INSTANCE_ID=name)
                    log=(root/f'{name}.log').open('w',encoding='utf-8');logs.append(log)
                    processes.append(subprocess.Popen([sys.executable,str(rt.ROOT/'app/openclaw_group_runtime.py'),str(info['port']),node,str(entries[0]),'gateway','run','--port',str(port),'--bind','loopback'],cwd=folder,env=clean,stdout=log,stderr=log,creationflags=rt.HIDDEN))
                with httpx.Client(trust_env=False,timeout=2) as client:
                    for name,info in members.items():
                        deadline=time.monotonic()+90
                        while time.monotonic()<deadline:
                            if any(p.poll() is not None for p in processes):self.fail((root/f'{name}.log').read_text(encoding='utf-8')[-2500:])
                            try:
                                main=client.get(f'http://127.0.0.1:{node_ports[name]}/readyz')
                                adapter=client.get(f"http://127.0.0.1:{info['port']}/health")
                                if main.status_code==200 and main.json().get('ready') and adapter.json().get('ready'):break
                            except (httpx.HTTPError,ValueError):pass
                            time.sleep(.5)
                        else:self.fail('OpenClaw readiness timeout')
                    for source,target in [('parent','child'),('child','parent')]:
                        info=members[source]
                        result=client.post(f"http://127.0.0.1:{info['port']}/local-anp/send",headers={'Authorization':'Bearer '+info['token']},json={'message_id':source+'-test','target_id':target,'content':'OpenClaw ANP smoke'})
                        self.assertEqual(result.status_code,200,result.text)
                    # Stopping the supervisor must stop its Node gateway too.
                    for process in processes:rt.kill(process);process.wait(timeout=10)
                    for port in node_ports.values():
                        with self.assertRaises(httpx.HTTPError):client.get(f'http://127.0.0.1:{port}/readyz')
            finally:
                for process in processes:
                    rt.kill(process);process.wait(timeout=10)
                for log in logs:log.close()

if __name__=='__main__':unittest.main()
