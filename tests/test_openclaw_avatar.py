"""Octopus and OpenClaw avatars of one identity are stored side by side."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request
from app import user_app
from agent_provider import ap


def _request():
    return Request({'type': 'http', 'headers': []})


class LastAgentPerTypeTests(unittest.TestCase):
    def test_each_type_keeps_its_own_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(user_app.os, 'getcwd', return_value=tmp):
            octopus = {'agent_type': 'octopus', 'phc': {'id': 'phc:a'}}
            openclaw = {'agent_type': 'openclaw', 'phc': {'id': 'phc:a'}, 'instance_id': 'phc_a_openclaw'}
            self.assertTrue(user_app.user_save_last_agent(_request(), octopus)['success'])
            self.assertTrue(user_app.user_save_last_agent(_request(), openclaw)['success'])
            self.assertEqual(user_app.user_get_last_agent(_request())['agent'], octopus)
            self.assertEqual(user_app.user_get_last_agent(_request(), 'openclaw')['agent'], openclaw)

    def test_legacy_openclaw_snapshot_moves_before_octopus_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(user_app.os, 'getcwd', return_value=tmp):
            legacy = Path(tmp) / 'local_store/user_state/last_agent.json'
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({'agent_type': 'openclaw', 'phc': {'id': 'phc:old'}}), encoding='utf-8')
            # 旧版 OpenClaw 主实例直接放在 <phc_id> 目录下。
            (Path(tmp) / 'local_store/agents/phc_old/openclaw_package').mkdir(parents=True)
            self.assertFalse(user_app.user_get_last_agent(_request())['success'])
            self.assertEqual(user_app.user_get_last_agent(_request(), 'openclaw')['agent']['phc']['id'], 'phc:old')
            user_app.user_save_last_agent(_request(), {'agent_type': 'octopus', 'phc': {'id': 'phc:old'}})
            moved = user_app.user_get_last_agent(_request(), 'openclaw')['agent']
            self.assertEqual(moved['instance_id'], 'phc_old')
            self.assertEqual(user_app.user_get_last_agent(_request())['agent']['agent_type'], 'octopus')


class InstanceRootTests(unittest.TestCase):
    def test_openclaw_uses_its_own_directory_and_keeps_legacy_main(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(user_app.os, 'getcwd', return_value=tmp):
            phc = {'id': 'phc:x'}
            self.assertEqual(user_app._instance_root(phc, 'octopus')[0], 'phc_x')
            self.assertEqual(user_app._instance_root(phc, 'openclaw')[0], 'phc_x_openclaw')
            legacy = Path(tmp) / 'local_store/agents/phc_x/openclaw_package'
            legacy.mkdir(parents=True)
            self.assertEqual(user_app._instance_root(phc, 'openclaw')[0], 'phc_x')
            # An Octopus instance with a stray package written by an older AP is not a legacy OpenClaw main.
            (legacy.parent / 'octopus_build').mkdir()
            self.assertEqual(user_app._instance_root(phc, 'openclaw')[0], 'phc_x_openclaw')


class APRecordKeyTests(unittest.TestCase):
    def test_records_are_split_by_type_with_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as root, patch.object(ap, '_apdb_root', return_value=root):
            ap._apdb_put('hid', {'agent_type': 'octopus', 'CMI': '1'})
            self.assertIsNone(ap._apdb_get_for('hid', 'openclaw'))
            ap._apdb_put(ap._ap_record_key('hid', 'openclaw'), {'agent_type': 'openclaw', 'CMI': '2'})
            self.assertEqual(ap._apdb_get_for('hid', 'octopus')['CMI'], '1')
            self.assertEqual(ap._apdb_get_for('hid', 'openclaw')['CMI'], '2')
            self.assertEqual(sorted(os.listdir(root)), ['hid.json', 'hid_openclaw.json'])
            ap._apdb_put('old', {'agent_type': 'openclaw', 'CMI': '3'})
            self.assertEqual(ap._apdb_get_for('old', 'openclaw')['CMI'], '3')

    def test_update_init_returns_matrix_for_requested_type(self):
        payload = ap.UpdateInitRequest(ar={}, user_pub=1)
        decrypted = json.dumps({'PHC': {'id': 'phc:x'}, 'HID': 'hid', 'agent_type': 'openclaw'}).encode()
        with patch.object(ap, 'elgamal_decrypt_bytes', return_value=decrypted), \
             patch.object(ap, '_encrypt_to_user', side_effect=lambda _pub, data: data):
            result = ap.update_init(payload)
        self.assertEqual(result['cmm_enc']['agent_type'], 'openclaw')
        self.assertEqual(result['cmm_enc']['CMM'], ap._build_openclaw_cmm_matrix())


if __name__ == '__main__':
    unittest.main()
