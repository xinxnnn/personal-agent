import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent_provider/octopus'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.anp_mailbox import Mailbox
with patch.dict(os.environ,{'DEBUG':'false'}):
    from octopus.api.auth_middleware import auth_middleware
    from octopus.api.chat_router import router


class PeerDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        self.app.middleware('http')(auth_middleware)
        self.app.include_router(router,prefix='/v1')

    def test_native_ui_can_discover_without_did_authorization_header(self):
        with patch.dict(os.environ,{'OCTOPUS_GROUP_FILE':''}):
            response=TestClient(self.app).get('/v1/chat/anp/peers')
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['managed'])

    def test_discovery_rejects_remote_client_and_cross_origin(self):
        response=TestClient(self.app,client=('192.0.2.10',1234)).get('/v1/chat/anp/peers')
        self.assertEqual(response.status_code,403)
        response=TestClient(self.app).get('/v1/chat/anp/peers',headers={'origin':'https://untrusted.example'})
        self.assertEqual(response.status_code,403)

    def test_conversation_history_is_loopback_only_and_reads_local_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=root/'anp_groups/parent.json';registry.parent.mkdir()
            registry.write_text(json.dumps({'members':{'parent':{},'child':{}}}))
            (root/'agents/parent').mkdir(parents=True)
            (root/'agents/child').mkdir(parents=True)
            (root/'agents/child/agent_manifest.json').write_text(json.dumps({'name':'Agent 2'}))
            mailbox=Mailbox(root/'agents/parent/anp_messages.sqlite3')
            mailbox.begin_conversation('conversation-1','received','child','hello')
            mailbox.finish_conversation('conversation-1','received','hi')
            with patch.dict(os.environ,{'OCTOPUS_GROUP_FILE':str(registry),'OCTOPUS_INSTANCE_ID':'parent'}):
                verifier=AsyncMock(return_value={'token_type':'test'})
                with patch('octopus.api.auth_middleware.verify_auth_header',new=verifier):
                    response=TestClient(self.app).get('/v1/chat/anp/conversations')
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(response.json()['conversations'][0]['peer_name'],'Agent 2')
                    self.assertEqual(response.json()['conversations'][0]['response'],'hi')
                    remote=TestClient(self.app,client=('192.0.2.10',1234)).get('/v1/chat/anp/conversations')
                    self.assertEqual(remote.status_code,403)


if __name__=='__main__':unittest.main()
