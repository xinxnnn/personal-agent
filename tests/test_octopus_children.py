import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import experience_subagents as sub
from app import experience_runtime as rt

class OctopusChildrenTests(unittest.TestCase):
    def test_openclaw_cannot_create_children(self):
        import asyncio
        with tempfile.TemporaryDirectory() as tmp:
            agents=Path(tmp)
            parent=agents/'phc_parent'
            (parent/'openclaw_package').mkdir(parents=True)
            (parent/'agent_manifest.json').write_text('{}')
            app=FastAPI();app.include_router(sub.router)
            with patch.object(rt,'AGENTS',agents),patch.object(rt.auth,'current_session',return_value={'username':'user'}),patch('app.deletion_review.frozen',return_value=False):
                response=TestClient(app).post('/user/children/create',json={'parent_phc_id':'phc_parent','agent_type':'openclaw','name':'child','capabilities':['webchat']})
                self.assertEqual(response.status_code,400)
                self.assertIn('OpenClaw',response.json()['detail'])
            result=asyncio.run(sub.legacy.create_sub_agent(sub.legacy.SubAgentConfig(name='child',parent_phc_id='phc_parent')))
            self.assertFalse(result['success'])

    def test_missing_historical_ntfs_stream_is_not_a_group(self):
        with patch.object(Path, 'exists', side_effect=[False, True]), patch('builtins.open', side_effect=FileNotFoundError):
            self.assertIsNone(sub.legacy.load_agent_group('group_phc:missing'))

    def test_create_append_and_isolate_model_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);agents=root/'local_store/agents';parent=agents/'phc_parent'
            (parent/'octopus_build').mkdir(parents=True)
            (parent/'agent_manifest.json').write_text('{}')
            (parent/'octopus_build/.env').write_text('OPENAI_API_KEY=private-test-key\nOPENAI_MODEL=test-model\nDID_PRIVATE_KEY_PATH=do-not-inherit\n')
            source=root/'agent_provider/octopus';source.mkdir(parents=True)
            (source/'pyproject.toml').write_text('[project]\nname="test"')
            (source/'.env').write_text('DO_NOT_COPY=secret')
            groups=root/'groups';groups.mkdir()
            app=FastAPI();app.include_router(sub.router)
            with patch.object(rt,'ROOT',root),patch.object(rt,'AGENTS',agents),patch.object(sub.legacy,'AGENT_GROUPS_DIR',groups),patch.object(rt.auth,'current_session',return_value={'username':'user'}),patch('app.deletion_review.frozen',return_value=False):
                client=TestClient(app);ids=[]
                for _ in range(2):
                    response=client.post('/user/children/create',json={'parent_phc_id':'phc:parent','agent_type':'octopus','name':'Research','capabilities':['text-processing','webchat']})
                    self.assertEqual(response.status_code,200,response.text)
                    child=response.json()['child'];ids.append(child['phc_id'])
                    path=agents/child['phc_id']
                    manifest=json.loads((path/'agent_manifest.json').read_text())
                    self.assertEqual(manifest['agent_type'],'octopus')
                    self.assertEqual(rt.read_env(path/'octopus_build/.env'),{'OPENAI_API_KEY':'private-test-key','OPENAI_MODEL':'test-model'})
                    self.assertEqual(json.loads((path/'active_agents.json').read_text())['allowed_agents'],['text_processor'])
                self.assertNotEqual(*ids)
                listing=client.get('/user/children/phc:parent')
                self.assertEqual(len(listing.json()['children']),2)
                self.assertNotIn('private-test-key',listing.text)
                response=client.post('/user/children/create',json={'parent_phc_id':'phc:parent','name':'Bad','capabilities':['shell']})
                self.assertEqual(response.status_code,400)

if __name__=='__main__':unittest.main()
