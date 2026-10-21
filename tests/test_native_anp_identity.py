import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

import httpx
from fastapi import FastAPI
from app import group_anp
from app.identity_memory import provision
from app.anp_mailbox import ActivityLog, Mailbox
from app.octopus_group_runtime import attach,group_chat,MessageRequest


class NativeChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_chat_authentication_before_model_and_reconnect(self):
        http,ws=await asyncio.to_thread(group_anp.ensure_gateway)
        self.addCleanup(group_anp.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'anp_groups/parent.json';registry.parent.mkdir()
            members={}
            for name,port in [('parent',19131),('child',19132)]:
                path=root/'agents'/name;path.mkdir(parents=True)
                (path/'agent_manifest.json').write_text('{}')
                members[name]={'port':port,'token':name+'-test','memory_public_key':provision(path)}
            registry.write_text(json.dumps({'gateway_http':f'http://127.0.0.1:{http}',
                'gateway_ws':f'ws://127.0.0.1:{ws}','members':members}))
            model=type('Model',(),{})()
            model.process_natural_language=AsyncMock(return_value='reply from target')
            for cycle,expected in [(0,'bootstrap'),(1,'history')]:
                a,b=FastAPI(),FastAPI()
                attach(a,None,registry,'parent');attach(b,None,registry,'child',lambda:model)
                async with a.router.lifespan_context(a),b.router.lifespan_context(b):
                    with patch.dict(os.environ,{'OCTOPUS_GROUP_FILE':str(registry),'OCTOPUS_INSTANCE_ID':'parent'}):
                        conversation_id='native-chat-'+str(cycle)
                        result=await group_chat('hello '+str(cycle),'127.0.0.1:19132',conversation_id)
                        self.assertEqual(result['identity_auth'],expected)
                        self.assertEqual(result['response'],'reply from target')
                        self.assertEqual(result['identity_events'],cycle+1)
                        sent=Mailbox(root/'agents/parent/anp_messages.sqlite3').conversations()
                        self.assertTrue(any(item['message_id']==conversation_id and item['response']=='reply from target' for item in sent))
                        events=ActivityLog(registry.with_suffix('.activity.sqlite3')).listing()
                        current=[item for item in events if item['conversation_id']==conversation_id]
                        self.assertEqual(
                            [(item['kind'],item['agent_id'],item['peer_id']) for item in current],
                            [('request_sent','parent','child'),('request_received','child','parent'),
                             ('response_returned','child','parent'),('response_received','parent','child')],
                        )
                        self.assertNotIn('hello '+str(cycle),str(current))
                        self.assertNotIn('reply from target',str(current))
                        with self.assertRaises(ValueError):await group_chat('no','127.0.0.1:9999')
                    received=Mailbox(root/'agents/child/anp_messages.sqlite3').conversations()
                    self.assertTrue(any(item['message_id']==conversation_id and item['request']=='hello '+str(cycle)
                                        and item['response']=='reply from target' for item in received))
                    self.assertEqual(model.process_natural_language.await_count,cycle+1)
                    # A valid group token alone cannot invoke the target model.
                    async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
                        headers={'Host':'127.0.0.1:19132','Authorization':'Bearer parent-test','x-agent-sender':'parent'}
                        raw=await client.post(f'http://127.0.0.1:{http}/local-anp/chat',
                            headers=headers,json=MessageRequest(target_id='child',content='bypass',purpose='chat').model_dump())
                        self.assertEqual(raw.status_code,422)
                    self.assertEqual(model.process_natural_language.await_count,cycle+1)


if __name__=='__main__':unittest.main()
