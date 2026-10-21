import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_provider import ap


class CapabilityStateTests(unittest.TestCase):
    def test_capability_state_is_persisted_and_returned(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_file = Path(temporary_directory) / "ap_capability_states.json"
            with patch.object(ap, "_CAP_STATE_FILE", state_file):
                result = ap.set_capability_state(
                    ap.CapabilityStatePayload(
                        agent_type="octopus",
                        group_index=0,
                        state="maintenance",
                    )
                )

                self.assertTrue(result["success"])
                self.assertEqual(
                    json.loads(state_file.read_text(encoding="utf-8")),
                    {"octopus:0": "maintenance"},
                )
                self.assertEqual(
                    ap.ap_capabilities("octopus")["states"],
                    [{"group_index": 0, "state": "maintenance"}],
                )
                self.assertEqual(ap.ap_capabilities("openclaw")["states"], [])

    def test_capability_state_rejects_invalid_values(self):
        invalid_payloads = (
            (
                {"agent_type": "unknown", "group_index": 0, "state": "active"},
                "invalid_agent_type",
            ),
            (
                {"agent_type": "octopus", "group_index": 0, "state": "unknown"},
                "invalid_state",
            ),
            (
                {"agent_type": "octopus", "group_index": -1, "state": "active"},
                "invalid_group_index",
            ),
            (
                {"agent_type": "octopus", "group_index": 99, "state": "active"},
                "invalid_group_index",
            ),
        )
        for payload, expected_detail in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(HTTPException) as error:
                    ap.set_capability_state(ap.CapabilityStatePayload(**payload))
                self.assertEqual(error.exception.status_code, 400)
                self.assertEqual(error.exception.detail, expected_detail)

    def test_capability_state_write_endpoint_requires_authentication(self):
        from app.ap_app import AP_PUBLIC_PATHS, app
        from app.auth_common import match_path

        self.assertFalse(match_path("/v1/ap/capabilities/state", AP_PUBLIC_PATHS))
        with patch.dict(os.environ, {"ENABLE_AUTH": "1"}):
            with TestClient(app) as client:
                response = client.post(
                    "/v1/ap/capabilities/state",
                    json={"agent_type": "octopus", "group_index": 0, "state": "active"},
                )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
