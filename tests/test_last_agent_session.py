import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request
from app import auth_common as auth
from app import user_app


class LastAgentSessionTests(unittest.TestCase):
    def test_cookie_session_saves_and_restores_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            for username in ('user', 'another-user'):
                token = auth.create_token({'username': username, 'role': 'user', 'display': username})
                request = Request({'type': 'http', 'headers': [
                    (b'cookie', (auth.COOKIE_USER+'='+token).encode())]})
                payload = {'agent_type': 'octopus', 'phc': {'id': 'test-'+username}}
                with patch.object(user_app.os, 'getcwd', return_value=tmp):
                    self.assertEqual(user_app.user_save_last_agent(request, payload), {'success': True})
                    self.assertEqual(user_app.user_get_last_agent(request), {'success': True, 'agent': payload})
                    expected = Path(tmp)/'local_store/user_state'
                    if username != 'user':
                        expected /= hashlib.sha256(username.encode()).hexdigest()
                    self.assertEqual(Path(user_app._last_agent_path(request)), expected/'last_agent.json')


if __name__ == '__main__':
    unittest.main()
