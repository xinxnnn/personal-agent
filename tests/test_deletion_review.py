import tempfile
import unittest
import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import deletion_review as deletion
from app import user_app as legacy

class DeletionTests(unittest.TestCase):
    def test_octopus_matching_does_not_stop_siblings_or_command_mentions(self):
        source=Path('D:/agents/phc_main')
        exe=source/'octopus_build/.web-venv/Scripts/python.exe'
        self.assertTrue(deletion.owns_octopus_process(source, {'CommandLine':f'"{exe}" runtime.py'}))
        self.assertFalse(deletion.owns_octopus_process(source, {'CommandLine':f'python diagnostic.py "{exe}"'}))
        self.assertFalse(deletion.owns_octopus_process(source, {'ExecutablePath':str(exe).replace('phc_main','phc_main_sub_1')}))

    def test_octopus_orphans_stopped_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp);(source/'octopus_build').mkdir()
            exe=source/'octopus_build/.web-venv/Scripts/python.exe'
            rows=[{'ProcessId':123456,'ExecutablePath':str(exe)},
                  {'ProcessId':234567,'ExecutablePath':'D:/other/python.exe'}]
            with patch.object(deletion.subprocess,'run',side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps(rows)),SimpleNamespace(returncode=0)]) as run:
                deletion.stop_orphan_octopus(source)
                self.assertEqual(run.call_args.args[0],['taskkill','/PID','123456','/T','/F'])

    def test_archive_retries_transient_windows_lock(self):
        from unittest.mock import MagicMock
        source=MagicMock()
        source.rename.side_effect=[PermissionError('busy'),None]
        with patch.object(deletion.time,'sleep'):
            deletion.archive_instance(source,Path('archive'))
        self.assertEqual(source.rename.call_count,2)

    def test_orphan_stop_matches_only_exact_instance_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'instance'
            entry=source/'openclaw_package/state/npm/node_modules/openclaw/openclaw.mjs'
            entry.parent.mkdir(parents=True);entry.touch()
            rows=[{'ProcessId':100,'CommandLine':f'node "{entry}" gateway run --port 56105'},
                  {'ProcessId':200,'CommandLine':'node D:\\other\\openclaw.mjs gateway run'},
                  {'ProcessId':300,'CommandLine':f'node "{entry}" --version'}]
            with patch.object(deletion.subprocess,'run',side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps(rows)),SimpleNamespace(returncode=0)]) as run:
                deletion.stop_orphan_gateway(source)
                self.assertEqual(run.call_count,2)
                self.assertEqual(run.call_args.args[0],['taskkill','/PID','100','/T','/F'])

    def test_approval_required_and_archive_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root=Path(tmp);agents=root/'local_store/agents';agent=agents/'phc_test'
            agent.mkdir(parents=True);(agent/'agent_manifest.json').write_text('{}')
            (agent/'data.txt').write_text('keep me')
            stack.enter_context(patch.object(deletion,'DB',root/'review.sqlite'))
            stack.enter_context(patch.object(deletion.rt,'ROOT',root))
            stack.enter_context(patch.object(deletion.rt,'AGENTS',agents))
            stack.enter_context(patch.object(legacy,'list_agent_groups',return_value=[]))
            stack.enter_context(patch.object(legacy,'_last_agent_path',return_value=str(root/'snapshot.json')))
            stack.enter_context(patch.object(deletion.auth,'current_session',side_effect=lambda r,c,role:{'username':role}))
            app=FastAPI();app.include_router(deletion.user_router);app.include_router(deletion.tp_router)
            c=TestClient(app)
            rid=c.post('/user/deletions',json={'agent_id':'phc_test','reason':'test'}).json()['request_id']
            self.assertEqual(c.post(f'/user/deletions/{rid}/execute').status_code,409)
            self.assertTrue(agent.exists())
            self.assertEqual(c.post(f'/v1/tp/deletions/{rid}/review',json={'decision':'rejected','comment':'mistake'}).status_code,200)
            self.assertEqual(c.post(f'/user/deletions/{rid}/execute').status_code,409)
            rejected_id=rid
            response=c.post(f'/v1/tp/deletions/{rid}/reopen')
            self.assertEqual(response.status_code,200,response.text)
            rid=response.json()['request_id']
            self.assertNotEqual(rid,rejected_id)
            self.assertEqual(c.post(f'/v1/tp/deletions/{rejected_id}/reopen').json()['request_id'],rid)
            self.assertEqual(c.post('/user/deletions',json={'agent_id':'phc_test','reason':'again'}).json()['request_id'],rid)
            self.assertEqual(c.post(f'/user/deletions/{rid}/execute').status_code,409)
            self.assertEqual(c.post(f'/v1/tp/deletions/{rid}/reopen').status_code,409)
            old=next(x for x in c.get('/v1/tp/deletions').json()['items'] if x['id']==rejected_id)
            self.assertEqual(old['status'],'rejected')
            self.assertEqual(old['comment'],'mistake')
            self.assertEqual(c.post(f'/v1/tp/deletions/{rid}/review',json={'decision':'approved'}).status_code,200)
            self.assertEqual(c.post(f'/user/deletions/{rid}/execute').status_code,200)
            self.assertFalse(agent.exists())
            self.assertEqual((root/'local_store/deleted_agents'/rid/'data.txt').read_text(),'keep me')
            self.assertEqual(c.post(f'/user/deletions/{rid}/execute').status_code,200)
            self.assertEqual(c.post(f'/v1/tp/deletions/{rid}/review',json={'decision':'rejected'}).status_code,409)
            with patch.object(deletion.auth,'current_session',return_value=None):
                self.assertEqual(c.get('/v1/tp/deletions').status_code,401)

if __name__=='__main__':unittest.main()
