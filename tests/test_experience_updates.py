import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crypto_lib import sha256_hex, compute_af_formal, canonical_json, schnorr_sign, ch_compute, dir_code_cmi_hid
from app import user_app
from app import experience_subagents as sub
from app import experience_runtime as runtime
from agent_provider import ap as ap_service
from trust_provider import issue_phc as tp
from trust_provider.phc import build_phc, verify_phc
from crypto_lib.keys import AP_SK, AP_PK, TP_DL_SK, TP_DL_PK
from user.models import UserInfo
from user.apply_agent import normalize_service_base_url


class UpdateTests(unittest.TestCase):
    def test_service_base_url_strips_console_path(self):
        self.assertEqual(
            normalize_service_base_url("http://127.0.0.1:8112/ap/"),
            "http://127.0.0.1:8112",
        )
        self.assertEqual(
            normalize_service_base_url("http://127.0.0.1:8111/tp"),
            "http://127.0.0.1:8111",
        )
        self.assertEqual(
            normalize_service_base_url("https://example.test/proxy/ap"),
            "https://example.test/proxy/ap",
        )

    def test_ap_recovery_candidate_matches_regenerated_pa(self):
        hid = "recovery-hid"
        phc = {
            "id": "phc:recovery",
            "DID": "did:recovery",
            "SCID": {"RF": "7"},
            "TPA": {"TPid": str(TP_DL_PK), "TPproof": {}},
            "ASO": {"TPM": {"AF": "old"}, "APM": {"CMI": "old"}},
            "APA": {},
            "PROOF": {"APCH": "0", "APCH_r": "1", "TPCH": "0", "CHproof": {}},
        }
        request_data = {"PHC": phc, "HID": hid, "CRF": "7"}

        with patch.object(
            ap_service, "elgamal_decrypt_bytes", return_value=json.dumps(request_data).encode()
        ), patch.object(
            ap_service,
            "_apdb_get",
            return_value={
                "phc_id": phc["id"],
                "PHC": phc,
                "CMC": [],
                "CMI": "42",
                "agent_type": "octopus",
                "r_bind2": "3",
            },
        ), patch.object(
            ap_service, "_encrypt_to_user", side_effect=lambda _pub, data: data
        ):
            result = ap_service.recover_pa(
                ap_service.RecoverInbound(ar={}, user_pub=1)
            )

        self.assertTrue(result["success"])
        recovered = result["par"]
        pa = recovered["PA"]
        recovered_phc = recovered["PHC"]
        self.assertEqual(recovered_phc["ASO"]["APM"], pa["APM"])
        self.assertEqual(recovered_phc["APA"], pa["APA"])
        self.assertFalse(recovered["verified_tp"])
        self.assertEqual(recovered_phc["ASO"]["TPM"]["AF"], str(compute_af_formal(
            hid, AP_PK, TP_DL_PK, 42, 7, 3
        )))

    def test_pa_recovery_resigns_invalid_local_phc_with_tp(self):
        apm = {"CMI": "42", "Time": "recovered"}
        apa = {"APid": "ap", "APproof": {"r": "1", "e": "2", "s": "3"}}
        candidate = {
            "id": "phc:recovery",
            "SCID": {"RF": "7"},
            "ASO": {"TPM": {"AF": "900"}, "APM": apm},
            "APA": apa,
        }
        result_obj = {
            "PHC": candidate,
            "PA": {"APM": apm, "APA": apa},
            "r_bind2": "3",
            "r_ap": "5",
            "ap_pk": "11",
            "tp_pk": "13",
            "CH": "17",
            "CCH": "19",
            "verified_tp": False,
            "verified_ch": True,
            "verified_af": True,
            "verified_cmi": True,
        }
        user = UserInfo(
            pii={"name": "Test", "id_number": "person-recovery"},
            bi={"last_login_ip": "127.0.0.1"},
        )

        class Response:
            status_code = 200

            def json(self):
                return {"phc": candidate}

            def raise_for_status(self):
                return None

        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp:
            os.chdir(temp)
            try:
                with patch.object(user_app.httpx, "post", return_value=Response()) as post, \
                     patch.object(user_app, "compute_af_formal", return_value=900), \
                     patch.object(user_app, "ch_compute", return_value=17), \
                     patch.object(user_app, "cch_compute", return_value=19), \
                     patch("trust_provider.phc.verify_phc", return_value=True), \
                     patch("user.crypto.dl_generate_user_keypair", return_value=("secret", "public")), \
                     patch("user.crypto.elgamal_encrypt_bytes", return_value={"encrypted": True}):
                    recovered = user_app._verify_and_restore_pa(
                        result_obj, user, "octopus", "http://127.0.0.1:8111"
                    )
                self.assertTrue(recovered["verified_tp"])
                self.assertTrue(recovered["verified_phc_user"])
                self.assertIs(recovered["PHC"], candidate)
                self.assertEqual(
                    post.call_args.args[0],
                    "http://127.0.0.1:8111/v1/tp/reissue_updated_phc",
                )
                self.assertEqual(
                    post.call_args.kwargs["json"]["candidate_phc"],
                    candidate,
                )
            finally:
                os.chdir(old_cwd)

    def test_pa_recovery_does_not_reissue_when_local_cmi_mismatches(self):
        phc = {
            "id": "phc:cmi-check",
            "SCID": {"RF": "7"},
            "ASO": {"TPM": {"AF": "900"}, "APM": {"CMI": "42"}},
        }
        pa = {"APM": {"CMI": "42"}, "APA": {}}
        result_obj = {
            "PHC": phc,
            "PA": pa,
            "r_bind2": "3",
            "r_ap": "5",
            "ap_pk": "11",
            "tp_pk": "13",
            "CH": "17",
            "CCH": "19",
            "verified_tp": False,
            "verified_ch": True,
            "verified_af": True,
            "verified_cmi": True,
        }
        user = UserInfo(
            pii={"name": "Test", "id_number": "person-cmi-check"},
            bi={"last_login_ip": "127.0.0.1"},
        )
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp:
            os.chdir(temp)
            package = Path("local_store/agents/phc_cmi-check/octopus_build")
            package.mkdir(parents=True)
            try:
                with patch.object(user_app.httpx, "post") as reissue, \
                     patch.object(user_app, "compute_af_formal", return_value=900), \
                     patch.object(user_app, "ch_compute", return_value=17), \
                     patch.object(user_app, "cch_compute", return_value=19), \
                     patch("crypto_lib.dir_code_cmi_hid", return_value=41):
                    with self.assertRaisesRegex(ValueError, "CMI"):
                        user_app._verify_and_restore_pa(
                            result_obj, user, "octopus", "http://127.0.0.1:8111"
                        )
                reissue.assert_not_called()
            finally:
                os.chdir(old_cwd)

    def test_openclaw_branch_has_its_own_tools_and_rejects_octopus_update(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agents = root / 'agents'
            child = agents / 'phc_parent_exec_one'
            (child / 'openclaw_package').mkdir(parents=True)
            (child / 'agent_manifest.json').write_text(json.dumps({
                'id': child.name, 'parent_phc_id': 'phc:parent',
                'credential_mode': 'inherited_from_parent', 'capabilities': ['browser', 'shell'],
            }), encoding='utf-8')
            account = root / 'last_agent.json'
            account.write_text(json.dumps({'phc': {'id': 'phc:parent'}}), encoding='utf-8')
            app = FastAPI(); app.include_router(sub.router)
            client = TestClient(app)
            with patch.object(runtime, 'AGENTS', agents), \
                 patch.object(runtime.auth, 'current_session', return_value={'username': 'user'}), \
                 patch.object(sub.legacy, '_last_agent_path', return_value=str(account)):
                options = client.get(f'/user/children/instance/{child.name}/update-options')
                self.assertEqual(options.status_code, 200, options.text)
                self.assertEqual(options.json()['agent_type'], 'openclaw')
                self.assertEqual({item['id'] for item in options.json()['options']}, set(sub.OPENCLAW_BRANCH_CAPABILITIES))
                self.assertEqual(client.post(f'/user/children/instance/{child.name}/update',
                                             json={'capabilities': ['browser']}).status_code, 400)

    def test_child_update_uses_only_its_supported_capabilities(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agents = root / 'agents'
            child = agents / 'phc_parent_sub_one'
            (child / 'octopus_build/octopus/agents').mkdir(parents=True)
            (child / 'agent_manifest.json').write_text(json.dumps({
                'id': child.name, 'name': '研究助手', 'parent_phc_id': 'phc:parent',
                'credential_mode': 'inherited_from_parent', 'capabilities': ['webchat'],
            }), encoding='utf-8')
            (child / 'active_agents.json').write_text(json.dumps({'allowed_agents': [], 'theme': 'green'}), encoding='utf-8')
            account = root / 'last_agent.json'
            account.write_text(json.dumps({'phc': {'id': 'phc:parent'}, 'pa': {'id': 'pa:parent'}}), encoding='utf-8')
            app = FastAPI(); app.include_router(sub.router)
            client = TestClient(app)
            with patch.object(runtime, 'AGENTS', agents), \
                 patch.object(runtime, 'snapshot', return_value={'stage': 'idle'}), \
                 patch.object(runtime.auth, 'current_session', return_value={'username': 'user'}), \
                 patch.object(sub.legacy, '_last_agent_path', return_value=str(account)):
                options = client.get(f'/user/children/instance/{child.name}/update-options')
                self.assertEqual(options.status_code, 200, options.text)
                self.assertEqual({item['id'] for item in options.json()['options']}, set(sub.OCTOPUS_CHILD_CAPABILITIES))
                denied = client.post(f'/user/children/instance/{child.name}/update', json={'capabilities': ['shell']})
                self.assertEqual(denied.status_code, 400)
                updated = client.post(f'/user/children/instance/{child.name}/update', json={'capabilities': ['text-processing', 'webchat']})
                self.assertEqual(updated.status_code, 200, updated.text)
                self.assertEqual(updated.json()['allowed_agents'], ['text_processor'])
                self.assertTrue((child / 'octopus_build/octopus/agents/text_processor_agent.py').is_file())
                self.assertEqual(json.loads((child / 'active_agents.json').read_text())['theme'], 'green')
                self.assertEqual(json.loads((child / 'agent_manifest.json').read_text())['capabilities'], ['text-processing', 'webchat'])
                account.write_text(json.dumps({'phc': {'id': 'other'}}), encoding='utf-8')
                self.assertEqual(client.get(f'/user/children/instance/{child.name}/update-options').status_code, 403)

    def test_octopus_update_verifies_the_code_bound_cmi_it_sent_to_ap(self):
        request = user_app.RequestUpdateSubmit(
            base_url="http://127.0.0.1:8112",
            cmc=[[{"label": "web-browsing"}]],
            hid="person-1",
            phc={"id": "phc:test", "SCID": {"RF": "1"}},
            user_sk="2",
            user_pk="3",
            agent_type="octopus",
        )
        submitted = {}

        class Response:
            def __init__(self, data):
                self.data = data
                self.status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return self.data

        def fake_copytree(_source, target, **_kwargs):
            Path(target, "octopus", "agents").mkdir(parents=True)
            Path(target, "octopus", "agents", "web_browsing_agent.py").write_text("enabled=True\n", encoding="utf-8")

        def fake_post(url, json, **_kwargs):
            if url.endswith('/v1/tp/reissue_updated_phc'):
                return Response({'phc': json['candidate_phc']})
            submitted.update(json["cmc_enc"])
            return Response({"par": "encrypted-response"})

        def fake_decrypt(_key, _ciphertext):
            af = compute_af_formal(submitted['HID'], 1, 1, int(submitted['CMI_code']), 1, 1)
            return json.dumps({
                "PHC": {"id": "phc:test", "SCID": {"RF": "1"}, "ASO": {"TPM": {"AF": str(af)}}},
                "PA": {"APM": {"CMI": submitted["CMI_code"]}},
                "ap_pk": "1", "tp_pk": "1", "r_bind2": "1",
            }).encode()

        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp:
            os.chdir(temp)
            try:
                runtime_python = Path('local_store/agents/phc_test/octopus_build/.web-venv/Scripts/python.exe')
                runtime_python.parent.mkdir(parents=True)
                runtime_python.write_bytes(b'existing-runtime')
                with patch("httpx.get", return_value=Response({"ap_dlog_pk": "1"})), \
                     patch("httpx.post", side_effect=fake_post), \
                     patch("shutil.copytree", side_effect=fake_copytree), \
                     patch("trust_provider.phc.verify_phc", return_value=True), \
                     patch.object(user_app, "elgamal_decrypt_bytes", side_effect=fake_decrypt):
                    result = user_app.user_update_submit(request)
                self.assertTrue(result["verified_cmi"])
                self.assertTrue(result["verified_phc_user"])
                self.assertEqual(submitted["HID"], sha256_hex("person-1"))
                self.assertEqual(result["PA"]["APM"]["CMI"], submitted["CMI_code"])
                self.assertIn("web_browsing", result["allowed_agents"])
                self.assertEqual(runtime_python.read_bytes(), b'existing-runtime')
            finally:
                os.chdir(old_cwd)

    def test_code_cmi_ignores_runtime_install_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'octopus.py').write_text('agent = 1', encoding='utf-8')
            before = dir_code_cmi_hid(str(root), 'person-1')
            (root / '.web-venv/Scripts').mkdir(parents=True)
            (root / '.web-venv/Scripts/python.exe').write_bytes(b'runtime')
            (root / '.web-dependencies-ready').touch()
            (root / 'web-install.log').write_text('installed', encoding='utf-8')
            (root / '.env').write_text('OPENAI_API_KEY=local', encoding='utf-8')
            self.assertEqual(dir_code_cmi_hid(str(root), 'person-1'), before)

    def test_tp_resigns_only_an_approved_matching_agent_update(self):
        hid = sha256_hex('person-2')
        old_tpm = {'Time': 'old', 'CDID': 'did:test', 'AF': '0', 'ECID': 'g'}
        old_apm = {'Time': 'old', 'CMI': '1'}
        tp_sig = schnorr_sign(TP_DL_SK, canonical_json({'TPM': old_tpm, 'TPid': str(TP_DL_PK)}).encode())
        ap_sig = schnorr_sign(AP_SK, canonical_json({'APM': old_apm, 'APid': str(AP_PK)}).encode())
        tpa = {'TPid': str(TP_DL_PK), 'TPproof': {key: str(tp_sig[key]) for key in ('r', 'e', 's')}}
        apa = {'APid': str(AP_PK), 'APproof': {key: str(ap_sig[key]) for key in ('r', 'e', 's')}}
        original = build_phc({'TPM': old_tpm, 'APM': old_apm}, tpa, apa, TP_DL_SK, TP_DL_PK, AP_PK)
        original['SCID'] = {'RF': '7'}
        original['DID'] = 'did:test'
        new_apm = {'Time': 'new', 'CMI': '42'}
        new_sig = schnorr_sign(AP_SK, canonical_json({'APM': new_apm, 'APid': str(AP_PK)}).encode())
        new_apa = {'APid': str(AP_PK), 'APproof': {key: str(new_sig[key]) for key in ('r', 'e', 's')}}
        af = compute_af_formal(hid, AP_PK, TP_DL_PK, 42, 7, 3)
        candidate = {'id': original['id'], 'SCID': original['SCID'], 'DID': original['DID'], 'ASO': {'TPM': {'AF': str(af)}, 'APM': new_apm}, 'APA': new_apa}
        record = {'phc': original, 'request_id': 'approved-request'}
        saved = []
        with patch.object(tp, '_tpdb_get', return_value=record), \
             patch.object(tp, '_tpapp_get', return_value={'status': 'issued'}), \
             patch.object(tp, '_tpdb_put', side_effect=lambda _hid, value: saved.append(value)):
            result = tp.reissue_updated_phc(tp.UpdatedPHCRequest(hid=hid, candidate_phc=candidate, pa={'APM': new_apm, 'APA': new_apa}, r_bind2=3))
        phc = result['phc']
        self.assertTrue(verify_phc(phc))
        self.assertEqual(phc['id'], original['id'])
        self.assertEqual(phc['ASO']['TPM']['AF'], str(af))
        self.assertEqual(phc['PROOF']['APCH'], str(ch_compute(AP_PK, new_apm, new_apa, int(phc['PROOF']['APCH_r']))))
        self.assertEqual(saved[0]['phc'], phc)
        with patch.object(tp, '_tpdb_get', return_value=record), \
             patch.object(tp, '_tpapp_get', return_value={'status': 'pending'}):
            with self.assertRaises(HTTPException) as denied:
                tp.reissue_updated_phc(tp.UpdatedPHCRequest(hid=hid, candidate_phc=candidate, pa={'APM': new_apm, 'APA': new_apa}, r_bind2=3))
        self.assertEqual(denied.exception.status_code, 403)

        for field, changed_value, expected_detail in (
            ('id', 'phc:other', 'identity_id_mismatch'),
            ('SCID', {'RF': 'different'}, 'identity_scid_mismatch'),
            ('DID', 'did:other', 'identity_did_mismatch'),
        ):
            changed_candidate = json.loads(json.dumps(candidate))
            changed_candidate[field] = changed_value
            with patch.object(tp, '_tpdb_get', return_value=record), \
                 patch.object(tp, '_tpapp_get', return_value={'status': 'issued'}):
                with self.assertRaises(HTTPException) as mismatch:
                    tp.reissue_updated_phc(tp.UpdatedPHCRequest(
                        hid=hid,
                        candidate_phc=changed_candidate,
                        pa={'APM': new_apm, 'APA': new_apa},
                        r_bind2=3,
                    ))
            self.assertEqual(mismatch.exception.detail, expected_detail)


if __name__ == "__main__":
    unittest.main()
