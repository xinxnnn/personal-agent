import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import experience_subagents as sub
from app import experience_runtime as rt


class ExecutionBranchRemovedTests(unittest.TestCase):
    """Octopus children may only be Octopus; legacy OpenClaw branches stay hidden."""

    def test_openclaw_child_is_rejected_and_legacy_branch_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); agents=root/'agents'; parent=agents/'phc_parent'
            (parent/'octopus_build').mkdir(parents=True)
            (parent/'agent_manifest.json').write_text('{}')
            legacy_branch=agents/'phc_parent_exec_old'
            (legacy_branch/'openclaw_package').mkdir(parents=True)
            (legacy_branch/'agent_manifest.json').write_text(json.dumps({'id':legacy_branch.name,'parent_phc_id':'phc_parent','credential_mode':'inherited_from_parent'}))
            groups=root/'groups';groups.mkdir()
            group=sub.legacy.MultiAgentGroup(group_id='group_phc_parent',group_name='g',parent_agent_id='phc_parent',
                sub_agents=[sub.legacy.SubAgentInfo(id=legacy_branch.name,name='old',phc_id=legacy_branch.name,status='created',created_at='2026-01-01T00:00:00Z')],
                communication_config={},created_at='2026-01-01T00:00:00Z')
            app=FastAPI();app.include_router(sub.router)
            with patch.object(rt,'AGENTS',agents), patch.object(sub.legacy,'AGENT_GROUPS_DIR',groups), patch.object(rt.auth,'current_session',return_value={'username':'user'}), patch('app.deletion_review.frozen',return_value=False):
                sub.legacy.save_agent_group(group)
                client=TestClient(app)
                result=client.post('/user/children/create',json={'parent_phc_id':'phc_parent','agent_type':'openclaw','name':'Executor','capabilities':['webchat']})
                self.assertEqual(result.status_code,400,result.text)
                self.assertFalse(any(p.name.startswith('phc_parent_exec_') and p!=legacy_branch for p in agents.iterdir()))
                listing=client.get('/user/children/phc_parent')
                self.assertEqual(listing.status_code,200,listing.text)
                self.assertEqual(listing.json()['children'],[])

    def test_openclaw_avatar_cannot_create_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents=Path(tmp)/'agents'; parent=agents/'phc_parent_openclaw'
            (parent/'openclaw_package').mkdir(parents=True)
            (parent/'agent_manifest.json').write_text(json.dumps({'agent_type':'openclaw'}))
            app=FastAPI();app.include_router(sub.router)
            with patch.object(rt,'AGENTS',agents), patch.object(rt.auth,'current_session',return_value={'username':'user'}), patch('app.deletion_review.frozen',return_value=False):
                response=TestClient(app).post('/user/children/create',json={'parent_phc_id':parent.name,'name':'research','capabilities':['webchat']})
            self.assertEqual(response.status_code,400,response.text)


if __name__ == '__main__':
    unittest.main()
