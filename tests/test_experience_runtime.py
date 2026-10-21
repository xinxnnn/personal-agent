import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import experience_runtime as rt


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agent = self.root / 'phc_test'
        self.pkg = self.agent / 'openclaw_package'
        (self.pkg / 'state').mkdir(parents=True)
        (self.agent / 'agent_manifest.json').write_text('{}')
        (self.pkg / '.env').write_text('OPENAI_API_KEY=test-secret\nOPENAI_BASE_URL=https://example.com/v1\nOPENCLAW_MODEL=openai/test\n')
        (self.pkg / 'state/openclaw.json').write_text(json.dumps({'gateway':{'auth':{'token':'test-token'}}, 'models':{'providers':{'openai':{}}}}))
        self.root_patch = patch.object(rt, 'AGENTS', self.root)
        self.root_patch.start()
        rt.JOBS.clear()
        rt.STOPPING.clear()
        app = FastAPI()
        app.include_router(rt.router)
        self.client = TestClient(app)
        self.auth = patch.object(rt.auth, 'current_session', return_value={'username':'user'})
        self.auth.start()
        self.gateway_patch=patch.object(rt,'prepare_gateway')
        self.gateway_patch.start()
        self.anp_patch=patch('app.group_anp.prepare',side_effect=RuntimeError('ANP unavailable'))
        self.anp_patch.start()

    def tearDown(self):
        self.anp_patch.stop()
        self.gateway_patch.stop()
        self.auth.stop()
        self.root_patch.stop()
        rt.JOBS.clear()
        self.tmp.cleanup()

    def test_auth_origin_and_invalid_id(self):
        with patch.object(rt.auth, 'current_session', return_value=None):
            self.assertEqual(self.client.post('/user/runtime/phc_test/start').status_code, 401)
        self.assertEqual(self.client.post('/user/runtime/phc_test/start', headers={'origin':'https://foreign.test'}).status_code, 403)
        self.assertEqual(self.client.get('/user/runtime/invalid%3Bid/status').status_code, 400)

    def test_status_and_config_never_return_secrets(self):
        response = self.client.get('/user/runtime/phc_test/status')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('test-secret', response.text)
        self.assertNotIn('test-token', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        response = self.client.post('/user/runtime/phc_test/model', json={'base_url':'https://example.com/v1','model':'new-model','api_key':''})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(rt.read_env(self.pkg/'.env')['OPENAI_API_KEY'], 'test-secret')
        config = json.loads((self.pkg/'state/openclaw.json').read_text())
        self.assertEqual(config['models']['providers']['openai']['apiKey'], '${OPENAI_API_KEY}')
        self.assertEqual(self.client.post('/user/runtime/phc_test/model',json={'model':'bad\nINJECT=true','base_url':'https://example.com'}).status_code,400)

    def test_start_is_idempotent_and_config_locked(self):
        with patch.object(rt.threading, 'Thread') as thread:
            for _ in range(2):
                self.assertEqual(self.client.post('/user/runtime/phc_test/start').status_code, 200)
            self.assertEqual(thread.call_count, 1)
            self.assertEqual(self.client.post('/user/runtime/phc_test/model', json={'model':'x','base_url':'https://example.com'}).status_code,409)
            self.assertEqual(self.client.post('/user/runtime/phc_test/stop').status_code,409)

    def test_missing_dependencies_report_error(self):
        job = {}
        with patch.object(rt, 'tools', return_value=(None,None)):
            rt.launch('phc_test', job)
        self.assertEqual(job['stage'], 'error')
        self.assertIn('Node.js', job['message'])

    def test_ready_only_after_http_and_process_alive(self):
        prefix = self.pkg/'state/npm/node_modules'
        for name in ('openclaw/openclaw.mjs','@openai/codex/bin/codex.js'):
            p = prefix/name
            p.parent.mkdir(parents=True,exist_ok=True)
            p.touch()
        process = MagicMock()
        process.poll.return_value = None
        job = {}
        with patch.object(rt, 'record_agent_lifecycle'), patch.object(rt, 'tools', return_value=('node',Path('npm-cli.js'))), patch.object(rt.shutil,'which',return_value='git'), patch.object(rt.subprocess,'Popen',return_value=process) as spawn, patch.object(rt.httpx,'Client') as client:
            client.return_value.__enter__.return_value.get.return_value.status_code=200
            client.return_value.__enter__.return_value.get.return_value.json.return_value={'ready':True}
            client.return_value.__enter__.return_value.get.return_value.json.side_effect=[{'ready':False},{'ready':True}]
            rt.launch('phc_test',job)
            self.assertEqual(job['stage'],'ready')
            self.assertIn('#token=test-token',job['url'])
            self.assertFalse(spawn.call_args.kwargs.get('shell',False))
            self.assertEqual(client.return_value.__enter__.return_value.get.call_count,2)
            self.assertTrue(client.return_value.__enter__.return_value.get.call_args.args[0].endswith('/readyz'))
            self.assertEqual(spawn.call_args.args[0][:2], ['node', str(prefix/'openclaw/openclaw.mjs')])
            rt.JOBS['phc_test']=job
            process.poll.return_value=1
            self.assertEqual(rt.snapshot('phc_test')['stage'],'error')
            self.assertIsNone(rt.snapshot('phc_test')['url'])

    def test_exit_reason_reports_port_conflict_without_raw_log(self):
        (self.pkg/'web-runtime.log').write_text('EADDRINUSE token=private-value')
        message=rt.runtime_failure(self.pkg,1)
        self.assertIn('端口',message)
        self.assertNotIn('private-value',message)

if __name__ == '__main__':
    unittest.main()
