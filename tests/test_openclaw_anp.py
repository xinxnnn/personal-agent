import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app import group_anp
from app.octopus_group_runtime import attach, group_chat

class OpenClawANPTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_receipt_retry_dedup_and_restart(self):
        http,ws=await asyncio.to_thread(group_anp.ensure_gateway)
        self.addCleanup(group_anp.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'anp_groups/parent.json';registry.parent.mkdir()
            members={name:{'port':port,'token':name+'-secret'} for name,port in [('parent',19211),('child',19212)]}
            for name in members:
                folder=root/'agents'/name;folder.mkdir(parents=True);(folder/'agent_manifest.json').write_text('{}')
            registry.write_text(json.dumps({'gateway_http':f'http://127.0.0.1:{http}','gateway_ws':f'ws://127.0.0.1:{ws}','members':members}))
            def apps():
                a,b=FastAPI(),FastAPI();attach(a,None,registry,'parent');attach(b,None,registry,'child',lambda:SimpleNamespace(process_natural_language=AsyncMock(return_value='chat reply')));return a,b
            a,b=apps();body={'message_id':'retry-stable-id','target_id':'child','content':'Persistent message'}
            headers={'Authorization':'Bearer parent-secret'}
            async with a.router.lifespan_context(a),b.router.lifespan_context(b):
                await asyncio.sleep(.2)
                with patch.dict('os.environ',{'OCTOPUS_GROUP_FILE':str(registry),'OCTOPUS_INSTANCE_ID':'parent'}):
                    self.assertEqual(await group_chat('hello','127.0.0.1:19212'),'chat reply')
                    with self.assertRaises(ValueError):
                        await group_chat('hello','127.0.0.1:9999')
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a),base_url='http://source') as sender:
                    original=httpx.AsyncClient.post
                    lost=False
                    async def lose_receipt(client,url,*args,**kwargs):
                        nonlocal lost
                        response=await original(client,url,*args,**kwargs)
                        if str(url).startswith(f'http://127.0.0.1:{http}') and not lost:
                            lost=True;raise httpx.ReadTimeout('simulated lost acknowledgement')
                        return response
                    with patch.object(httpx.AsyncClient,'post',lose_receipt):
                        self.assertEqual((await sender.post('/local-anp/send',headers=headers,json=body)).status_code,502)
                    for _ in range(2):
                        result=await sender.post('/local-anp/send',headers=headers,json=body)
                        self.assertEqual(result.status_code,200,result.text)
                        self.assertEqual(result.json()['receipt']['message_id'],body['message_id'])
                    self.assertEqual((await sender.post('/local-anp/send',headers=headers,json={**body,'content':'changed'})).status_code,409)
            a,b=apps()
            async with a.router.lifespan_context(a),b.router.lifespan_context(b):
                await asyncio.sleep(.2)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=b),base_url='http://target') as target:
                    result=await target.get('/local-anp/messages',headers={'Authorization':'Bearer child-secret'})
                    self.assertEqual(len(result.json()['messages']),1)
                    self.assertEqual(result.json()['messages'][0]['content'],body['content'])
                    self.assertEqual((await target.get('/local-anp/messages')).status_code,403)
                    reply=await target.post('/local-anp/send',headers={'Authorization':'Bearer child-secret'},json={'message_id':'reply','target_id':'parent','content':'Reply'})
                    self.assertEqual(reply.status_code,200,reply.text)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=a),base_url='http://source') as sender:
                    result=await sender.get('/local-anp/messages',headers=headers)
                    self.assertEqual(result.json()['sent'][0]['status'],'delivered')
                    self.assertEqual(result.json()['messages'][0]['content'],'Reply')

if __name__=='__main__':unittest.main()
