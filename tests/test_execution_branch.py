import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import experience_subagents as sub
from app import experience_runtime as rt


class ExecutionBranchTests(unittest.TestCase):
    def test_create_real_package_and_inherit_parent_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); agents=root/'agents'; parent=agents/'phc_parent'
            (parent/'octopus_build').mkdir(parents=True)
            (parent/'agent_manifest.json').write_text('{}')
            (parent/'octopus_build/.env').write_text('OPENAI_API_KEY=test-only-key\nOPENAI_MODEL=test-model\nOPENAI_BASE_URL=https://example.invalid/v1\n')
            groups=root/'groups';groups.mkdir()
            app=FastAPI();app.include_router(sub.router)
            with patch.object(rt,'AGENTS',agents), patch.object(sub.legacy,'AGENT_GROUPS_DIR',groups), patch.object(rt.auth,'current_session',return_value={'username':'user'}), patch('app.deletion_review.frozen',return_value=False):
                client=TestClient(app)
                result=client.post('/user/children/create',json={'parent_phc_id':'phc_parent','agent_type':'openclaw','name':'Executor','capabilities':['webchat','browser']})
                self.assertEqual(result.status_code,200,result.text)
                child=result.json()['child']; path=agents/child['phc_id']
                self.assertTrue((path/'openclaw_package/state/openclaw.json').exists())
                manifest=json.loads((path/'agent_manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(manifest['role'],'executor')
                binding=json.loads((path/'openclaw_package/openclaw_binding.json').read_text(encoding='utf-8'))
                self.assertEqual(binding['phc_id'],'phc_parent')
                self.assertEqual(binding['credential_mode'],'inherited_from_parent')
                values,source=rt.model_env(path)
                self.assertEqual(source,'parent')
                self.assertEqual(values['OPENAI_MODEL'],'test-model')
                listing=client.get('/user/children/phc_parent')
                self.assertEqual(listing.json()['children'][0]['agent_type'],'openclaw')
                self.assertNotIn('test-only-key',listing.text+result.text)
                blocked=client.post('/user/children/create',json={'parent_phc_id':child['phc_id'],'agent_type':'octopus','name':'No descendants'})
                self.assertEqual(blocked.status_code,400)

