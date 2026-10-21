import asyncio
import json
import sys
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app import group_anp, experience_runtime as rt
from app.octopus_group_runtime import attach
from app.identity_memory import provision

sys.path.insert(0,str(rt.ROOT/'agent_provider/octopus'))
from octopus.agents.message.message_agent import MessageAgent

class ANPTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_octopus_processes_exchange_messages(self):
        http,ws=await asyncio.to_thread(group_anp.ensure_gateway)
        self.addCleanup(group_anp.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'anp_groups/parent.json';registry.parent.mkdir()
            ports=[rt.reserve_port(0),rt.reserve_port(0)]
            self.assertNotEqual(*ports)
            members={name:{'port':port,'token':name+'-secret'} for name,port in zip(['parent','child'],ports)}
            registry.write_text(json.dumps({'gateway_http':f'http://127.0.0.1:{http}','gateway_ws':f'ws://127.0.0.1:{ws}','members':members}))
            processes=[];logs=[]
            try:
                for name,info in members.items():
                    path=root/'agents'/name;path.mkdir(parents=True);(path/'agent_manifest.json').write_text('{}')
                    info['memory_public_key']=provision(path)
                    registry.write_text(json.dumps({'gateway_http':f'http://127.0.0.1:{http}','gateway_ws':f'ws://127.0.0.1:{ws}','members':members}))
                    env=dict(os.environ,DEBUG='false',OPENAI_API_KEY='test-not-a-real-key',OPENAI_BASE_URL='http://127.0.0.1:1/v1',OPENAI_MODEL='test',MODEL_PROVIDER='openai',
                        OCTOPUS_GROUP_FILE=str(registry),OCTOPUS_INSTANCE_ID=name,PYTHONPATH=str(rt.ROOT/'agent_provider/octopus'))
                    log=(root/f'{name}.log').open('w',encoding='utf-8');logs.append(log)
                    process=subprocess.Popen([sys.executable,str(rt.ROOT/'app/octopus_group_runtime.py'),str(info['port'])],cwd=path,env=env,stdout=log,stderr=log,creationflags=rt.HIDDEN)
                    processes.append(process)
                async with httpx.AsyncClient(trust_env=False,timeout=2) as client:
                    for name,info in members.items():
                        for _ in range(90):
                            try:
                                r=await client.get(f"http://127.0.0.1:{info['port']}/local-anp/messages",headers={'Authorization':'Bearer '+info['token']})
                                if r.status_code==200 and r.json()['connected']:break
                            except httpx.HTTPError:pass
                            if any(p.poll() is not None for p in processes):
                                self.fail((root/f'{name}.log').read_text(encoding='utf-8')[-5000:])
                            await asyncio.sleep(.5)
                        else:self.fail('Native runtime did not become ready')
                    for source,target in [('parent','child'),('child','parent')]:
                        info=members[source]
                        r=await client.post(f"http://127.0.0.1:{info['port']}/local-anp/send",headers={'Authorization':'Bearer '+info['token']},json={'target_id':target,'content':'Native ANP test'})
                        self.assertEqual(r.status_code,200,r.text)
                        target_info=members[target]
                        r=await client.get(f"http://127.0.0.1:{target_info['port']}/local-anp/messages",headers={'Authorization':'Bearer '+target_info['token']})
                        self.assertEqual(r.json()['messages'][-1]['content'],'Native ANP test')
            finally:
                for p in processes:
                    if p.poll() is None:await asyncio.to_thread(rt.kill,p)
                    p.wait(timeout=10)
                for log in logs:log.close()

    async def test_real_gateway_bidirectional_delivery_and_auth(self):
        # Real TCP gateway + two WebSocket receivers + original MessageAgent objects.
        http,ws=await asyncio.to_thread(group_anp.ensure_gateway)
        self.addCleanup(group_anp.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'anp_groups/parent.json';registry.parent.mkdir()
            members={name:{'port':port,'token':name+'-secret'} for name,port in [('parent',19011),('child',19012)]}
            for name in members:
                path=root/'agents'/name;path.mkdir(parents=True);(path/'agent_manifest.json').write_text('{}')
                members[name]['memory_public_key']=provision(path)
            registry.write_text(json.dumps({'gateway_http':f'http://127.0.0.1:{http}','gateway_ws':f'ws://127.0.0.1:{ws}','members':members}))
            with patch.dict(os.environ,{'DEBUG':'false','OPENAI_API_KEY':''}):
                parent=MessageAgent();child=MessageAgent()
            app1=FastAPI();app2=FastAPI()
            attach(app1,lambda:parent,registry,'parent');attach(app2,lambda:child,registry,'child')
            async with app1.router.lifespan_context(app1),app2.router.lifespan_context(app2):
                await asyncio.sleep(.2)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app1),base_url='http://local') as a,httpx.AsyncClient(transport=httpx.ASGITransport(app=app2),base_url='http://local') as b:
                    response=await a.post('/local-anp/send',headers={'Authorization':'Bearer parent-secret'},json={'target_id':'child','content':'Hello child'})
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(child.received_messages[-1].content,'Hello child')
                    response=await b.post('/local-anp/send',headers={'Authorization':'Bearer child-secret'},json={'target_id':'parent','content':'Hello parent'})
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(parent.received_messages[-1].content,'Hello parent')
                    self.assertEqual((await a.get('/local-anp/messages')).status_code,403)
                    response=await a.post('/local-anp/send',headers={'Authorization':'Bearer parent-secret'},json={'target_id':'outsider','content':'blocked'})
                    self.assertEqual(response.status_code,403)
                    inbox=await b.get('/local-anp/messages',headers={'Authorization':'Bearer child-secret'})
                    self.assertTrue(inbox.json()['connected'])
                    self.assertNotIn('secret',inbox.text)

if __name__=='__main__':unittest.main()
