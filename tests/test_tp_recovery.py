import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from trust_provider import issue_phc


class TPRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.pii = {
            "name": "Test User",
            "id_number": "identity-123",
            "id_card_number": "",
            "email": "",
        }
        self.bi = {
            "last_login_ip": "127.0.0.1",
            "pic_string": "registered-photo-record",
        }
        self.payload = issue_phc.RecoverPHCInbound(rec={}, user_pub=123)
        self.secinfo = {"PII": self.pii, "BI": self.bi}

    def invoke_recovery(self, secinfo):
        record = {"rf": "1", "cid": "test-cid", "phc": {"id": "test-phc"}}
        patches = (
            patch.object(issue_phc, "elgamal_decrypt_bytes", return_value=json.dumps({"PII": self.pii, "BI": self.bi}).encode()),
            patch.object(issue_phc, "_tpdb_get", return_value=record),
            patch.object(issue_phc, "kdf_s1", return_value="test-key"),
            patch.object(issue_phc, "ipfs_get", return_value=b"encrypted"),
            patch.object(issue_phc, "sym_decrypt", return_value=json.dumps(secinfo).encode()),
            patch("crypto_lib.elgamal_encrypt_bytes", return_value={"encrypted": True}),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return issue_phc.recover_phc(self.payload)

    def test_returns_phc_only_after_exact_identity_record_match(self):
        result = self.invoke_recovery(self.secinfo)
        self.assertTrue(result["success"])
        self.assertEqual(result["phc_enc"], {"encrypted": True})

    def test_rejects_identity_record_mismatch(self):
        changed_bi = {**self.bi, "pic_string": "different-photo-record"}
        with self.assertRaises(HTTPException) as raised:
            self.invoke_recovery({"PII": self.pii, "BI": changed_bi})
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "verify_failed")

    def test_allows_unprovided_optional_identity_fields(self):
        recorded_pii = {
            **self.pii,
            "id_card_number": "registered-card-number",
            "email": "registered@example.com",
        }
        submitted_pii = {"name": self.pii["name"], "id_number": self.pii["id_number"]}
        submitted_bi = {"pic_string": self.bi["pic_string"]}
        self.assertTrue(issue_phc._recovery_identity_matches(
            {"PII": recorded_pii, "BI": self.bi}, submitted_pii, submitted_bi
        ))

    def test_rejects_incorrect_optional_identity_field(self):
        submitted_pii = {**self.pii, "email": "different@example.com"}
        self.assertFalse(issue_phc._recovery_identity_matches(
            self.secinfo, submitted_pii, self.bi
        ))

    def test_ignores_volatile_login_ip_but_requires_matching_photo(self):
        submitted_bi = {
            "last_login_ip": "192.0.2.10",
            "pic_string": self.bi["pic_string"],
        }
        self.assertTrue(issue_phc._recovery_identity_matches(
            self.secinfo, self.pii, submitted_bi
        ))
        submitted_bi["pic_string"] = "different-photo-record"
        self.assertFalse(issue_phc._recovery_identity_matches(
            self.secinfo, self.pii, submitted_bi
        ))


if __name__ == "__main__":
    unittest.main()
