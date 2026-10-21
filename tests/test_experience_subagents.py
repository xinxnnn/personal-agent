import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import experience_subagents as sub
from app import experience_runtime as rt

class ChildrenTests(unittest.TestCase):
    def test_existing_builder_appends_children_and_runtime_manifests(self):
        cwd=os.getcwd()
        with tempfile.TemporaryDirectory() as temp:
            os.chdir(temp)
            try:
                agents=Path(temp)/'local_store/agents'
                parent=agents/'phc_parent'
                (parent/'openclaw_package').mkdir(parents=True)
                (parent/'agent_manifest.json').write_text('{}')
                (parent/'openclaw_package/.env').write_text('OPENAI_API_KEY=private-parent-key\nOPENCLAW_MODEL=openai/test\n')
                groups=Path(temp)/'groups';groups.mkdir()
                def build(**kwargs):
                    pkg=Path(kwargs['root'])/'openclaw_package'
                    (pkg/'state').mkdir(parents=True)
                    config=pkg/'state/openclaw.json'
                    config.write_text('{}')
                    return {'config_path':str(config)}
                app=FastAPI();app.include_router(sub.router)
                client=TestClient(app)
                with patch.object(rt,'AGENTS',agents),patch.object(sub.legacy,'AGENT_GROUPS_DIR',groups),patch.object(rt.auth,'current_session',return_value={'username':'user'}),patch('agent_provider.openclaw.openclaw_package.build_openclaw_agent_files',side_effect=build):
                    ids=[]
                    for _ in range(2):
                        response=client.post('/user/children/create',json={'parent_phc_id':'phc:parent','name':'research','capabilities':['memory']})
                        self.assertEqual(response.status_code,200,response.text)
                        child=response.json()['child'];ids.append(child['phc_id'])
                        self.assertTrue((agents/child['phc_id']/'agent_manifest.json').is_file())
                        self.assertEqual(rt.read_env(agents/child['phc_id']/'openclaw_package/.env')['OPENAI_API_KEY'],'private-parent-key')
                    self.assertNotEqual(ids[0],ids[1])
                    self.assertTrue((groups/'group_phc_parent.json').is_file())
                    self.assertEqual(len(sub.legacy.load_agent_group('group_phc:parent').sub_agents),2)
                    result=client.get('/user/children/phc:parent')
                    self.assertEqual(len(result.json()['children']),2)
                    self.assertNotIn('private-parent-key',result.text)
                    self.assertNotIn('token',result.text)
                    self.assertEqual(client.post('/user/children/create',json={'parent_phc_id':'phc_parent','name':'../escape'}).status_code,400)
            finally:
                os.chdir(cwd)

    def test_legacy_colon_group_is_recovered_without_removing_original(self):
        with tempfile.TemporaryDirectory() as temp:
            groups=Path(temp)
            old=groups/'group_phc:legacy.json'
            data={'group_id':'group_phc:legacy','group_name':'Legacy',
                  'parent_agent_id':'phc:legacy','sub_agents':[],
                  'communication_config':{},'created_at':'2026-01-01T00:00:00Z'}
            old.write_text(json.dumps(data),encoding='utf-8')
            with patch.object(sub.legacy,'AGENT_GROUPS_DIR',groups):
                result=sub.legacy.list_agent_groups('phc:legacy')
                self.assertEqual(len(result),1)
                self.assertTrue(old.exists())
                self.assertTrue((groups/'group_phc_legacy.json').is_file())
                self.assertEqual(len(sub.legacy.list_agent_groups('phc:legacy')),1)

if __name__=='__main__': unittest.main()
