import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent_provider import ap
from trust_provider import issue_phc


class CredentialHistoryStorageTests(unittest.TestCase):
    def test_ap_history_write_is_readable_and_preserves_phc_id(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(ap, "_apdb_root", return_value=root):
                ap._apdb_put("test-hid", {"phc_id": "phc:test", "CMI": "123"})
                record = ap._apdb_get("test-hid")

            self.assertEqual(record["phc_id"], "phc:test")
            self.assertEqual(record["CMI"], "123")
            self.assertEqual(os.listdir(root), ["test-hid.json"])

    def test_tp_history_write_is_readable(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(issue_phc, "_tpdb_root", return_value=root):
                issue_phc._tpdb_put("test-hid", {"phc": {"id": "phc:test"}})
                record = issue_phc._tpdb_get("test-hid")

            self.assertEqual(record["phc"]["id"], "phc:test")
            self.assertEqual(os.listdir(root), ["test-hid.json"])

    def test_ap_recovery_rejects_history_for_another_phc(self):
        payload = ap.RecoverInbound(ar={"encrypted": True}, user_pub=123)
        requested_phc = {"id": "phc:requested"}
        stored_record = {"phc_id": "phc:other", "PHC": {"id": "phc:other"}}
        with patch.object(
            ap,
            "elgamal_decrypt_bytes",
            return_value=json.dumps({"PHC": requested_phc, "HID": "test-hid"}).encode(),
        ), patch.object(ap, "_apdb_get", return_value=stored_record):
            result = ap.recover_pa(payload)

        self.assertEqual(result, {"success": False, "error": "phc_history_mismatch"})


if __name__ == "__main__":
    unittest.main()
