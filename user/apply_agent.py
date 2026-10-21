"""HTTP client for interacting with TP/AP endpoints remotely."""
from typing import Any, Dict
import httpx
import secrets
import time
import json
from urllib.parse import urlsplit, urlunsplit
from .crypto import (
    compute_cmi,
    compute_r_bind,
    dl_generate_user_keypair,
    schnorr_sign,
    elgamal_encrypt_bytes,
    compute_af_dl,
    sha256_hex,
    canonical_json,
)
from .models import UserInfo, PHCResponse


def normalize_service_base_url(base_url: str) -> str:
    """Normalize service-console URLs to the service root for API requests."""
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.path.rstrip("/").lower() in {"/ap", "/tp", "/user"}:
        parsed = parsed._replace(path="")
    return urlunsplit(parsed).rstrip("/")


def request_phc_remote(base_url: str, user: UserInfo) -> PHCResponse:
    base_url = normalize_service_base_url(base_url)
    r_bind = compute_r_bind()
    af = sha256_hex(canonical_json({"pii": user.pii.model_dump(), "bi": user.bi.model_dump(), "r_bind": r_bind, "pk_ap": "ap.pk.placeholder"}))
    cmi = compute_cmi(user.pii.model_dump())
    payload = {"af": af, "cmi": cmi, "cdid": user.cdid, "ecid": user.ecid}
    url = base_url.rstrip("/") + "/v1/tp/issue_phc"
    resp = httpx.post(url, json=payload, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    return PHCResponse(**data)


def request_phc_secure(base_url: str, user: UserInfo) -> PHCResponse:
    base_url = normalize_service_base_url(base_url)
    with httpx.Client(trust_env=False) as client:
        pub_resp = client.get(base_url.rstrip("/") + "/v1/tp/public_keys", timeout=10.0)
        pub_resp.raise_for_status()
        tp_keys = pub_resp.json()
        tp_dlog_pk = int(str(tp_keys["tp_dlog_pk"]))
        ap_dlog_pk = int(str(tp_keys["ap_dlog_pk"]))
        sk_a, pk_a = dl_generate_user_keypair()
        r_bind_int = int(secrets.token_hex(16), 16)
        af_val = compute_af_dl(user.pii.id_number, ap_dlog_pk, tp_dlog_pk, hex(r_bind_int)[2:])
        plaintext = {"AF": af_val, "ID": user.pii.id_number, "BI": user.bi.model_dump(), "PII": user.pii.model_dump(), "pk_ap": ap_dlog_pk, "r_bind": r_bind_int, "timestamp": int(time.time())}
        cr = elgamal_encrypt_bytes(tp_dlog_pk, plaintext)
        sig = schnorr_sign(sk_a, str(r_bind_int).encode())
        payload = {"cr": cr, "user_pub": pk_a, "sig": sig}
        url = base_url.rstrip("/") + "/v1/tp/issue_phc_secure"
        resp = client.post(url, json=payload, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        return PHCResponse(**data)


def request_pa_remote(base_url: str, phc: Dict[str, Any], user: UserInfo) -> Dict[str, Any]:
    base_url = normalize_service_base_url(base_url)
    with httpx.Client(trust_env=False) as client:
        try:
            pub_resp = client.get(base_url.rstrip("/") + "/ap/public_keys", timeout=10.0)
            pub_resp.raise_for_status()
            ap_keys = pub_resp.json()
            ap_dlog_pk = int(str(ap_keys["ap_dlog_pk"]))
        except httpx.HTTPError:
            from agent_provider.ap import AP_PK as ap_dlog_pk
        sk_a, pk_a = dl_generate_user_keypair()
        hid = sha256_hex(user.pii.id_number)
        tpac = phc.get("TPA") if isinstance(phc, dict) else {}
        ar_plain = {"PHC": phc, "HID": hid, "TPAC": tpac}
        ar = elgamal_encrypt_bytes(ap_dlog_pk, ar_plain)
        payload = {"ar": ar, "user_pub": pk_a}
        url = base_url.rstrip("/") + "/v1/ap/request_pa"
        try:
            resp = client.post(url, json=payload, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            par = data.get("par")
            raw = _elg_decrypt(sk_a, par)
            return json.loads(raw.decode())
        except httpx.HTTPError:
            from agent_provider.ap import request_pa, APInbound
            out = request_pa(APInbound(ar=ar, user_pub=pk_a))
            raw = _elg_decrypt(sk_a, out.get("par"))
            return json.loads(raw.decode())


def request_pa_recover(base_url: str, phc: Dict[str, Any], user: UserInfo) -> Dict[str, Any]:
    base_url = normalize_service_base_url(base_url)
    try:
        pub_resp = httpx.get(base_url.rstrip("/") + "/v1/ap/public_keys", timeout=10.0)
        pub_resp.raise_for_status()
        ap_dlog_pk = int(str(pub_resp.json()["ap_dlog_pk"]))
    except httpx.HTTPError:
        from agent_provider.ap import AP_PK as ap_dlog_pk
    sk_a, pk_a = dl_generate_user_keypair()
    hid = sha256_hex(user.pii.id_number)
    crf = (phc.get("CRF") if isinstance(phc, dict) else None) or ((phc.get("SCID") or {}).get("RF") if isinstance(phc.get("SCID"), dict) else 0)
    ar_plain = {"PHC": phc, "HID": hid, "CRF": crf}
    ar = elgamal_encrypt_bytes(ap_dlog_pk, ar_plain)
    payload = {"ar": ar, "user_pub": pk_a}
    url = base_url.rstrip("/") + "/v1/ap/recover_pa"
    try:
        resp = httpx.post(url, json=payload, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        par = data.get("par")
        if not par:
            err = str(data.get("error") or "not_found")
            if err == "not_found":
                url2 = base_url.rstrip("/") + "/v1/ap/request_pa"
                try:
                    resp2 = httpx.post(url2, json=payload, timeout=15.0)
                    resp2.raise_for_status()
                    data2 = resp2.json()
                    par2 = data2.get("par")
                    raw2 = _elg_decrypt(sk_a, par2)
                    obj = json.loads(raw2.decode())
                    obj["mode"] = "recover_fallback"
                    return obj
                except httpx.HTTPError:
                    from agent_provider.ap import request_pa, APInbound
                    out = request_pa(APInbound(ar=ar, user_pub=pk_a))
                    raw3 = _elg_decrypt(sk_a, out.get("par"))
                    obj3 = json.loads(raw3.decode())
                    obj3["mode"] = "recover_local"
                    return obj3
            return data
        raw = _elg_decrypt(sk_a, par)
        return json.loads(raw.decode())
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            url2 = base_url.rstrip("/") + "/v1/ap/request_pa"
            try:
                resp2 = httpx.post(url2, json=payload, timeout=15.0)
                resp2.raise_for_status()
                data2 = resp2.json()
                par2 = data2.get("par")
                raw2 = _elg_decrypt(sk_a, par2)
                obj = json.loads(raw2.decode())
                obj["mode"] = "recover_fallback"
                return obj
            except httpx.HTTPError:
                from agent_provider.ap import request_pa, APInbound
                out = request_pa(APInbound(ar=ar, user_pub=pk_a))
                raw3 = _elg_decrypt(sk_a, out.get("par"))
                obj3 = json.loads(raw3.decode())
                obj3["mode"] = "recover_local"
                return obj3
        raise


def request_cmm_init(
    base_url: str,
    phc: Dict[str, Any],
    user: UserInfo,
    agent_type: str = "octopus",
) -> Dict[str, Any]:
    base_url = normalize_service_base_url(base_url)
    with httpx.Client(trust_env=False) as client:
        try:
            pub_resp = client.get(base_url.rstrip("/") + "/v1/ap/public_keys", timeout=10.0)
            pub_resp.raise_for_status()
            ap_keys = pub_resp.json()
            ap_dlog_pk = int(str(ap_keys["ap_dlog_pk"]))
        except httpx.HTTPError:
            from agent_provider.ap import AP_PK as ap_dlog_pk

        sk_a, pk_a = dl_generate_user_keypair()
        hid = sha256_hex(user.pii.id_number)
        tpac = phc.get("TPA") if isinstance(phc, dict) else {}

        # 关键：把 agent_type 放进加密载荷里给 AP
        ar_plain = {
            "PHC": phc,
            "HID": hid,
            "TPAC": tpac,
            "agent_type": agent_type,
        }

        ar = elgamal_encrypt_bytes(ap_dlog_pk, ar_plain)

        payload = {
            "ar": ar,
            "user_pub": pk_a,
        }

        url = base_url.rstrip("/") + "/v1/ap/cmm_init"

        try:
            resp = client.post(url, json=payload, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()

            cmm_enc = data.get("cmm_enc")
            raw = _elg_decrypt(sk_a, cmm_enc)
            obj = json.loads(raw.decode())

            return {
                "cmm": obj.get("CMM"),
                "sk": str(sk_a),
                "pk": str(pk_a),
                "agent_type": obj.get("agent_type") or agent_type,
                "perf_ap_verify_phc_ms": data.get("perf_ap_verify_phc_ms"),
            }

        except httpx.HTTPError:
            from agent_provider.ap import _build_cmm_matrix

            # fallback 也要带 agent_type
            cmm = _build_cmm_matrix(hid, phc, agent_type=agent_type)

            return {
                "cmm": cmm,
                "sk": str(sk_a),
                "pk": str(pk_a),
                "agent_type": agent_type,
            }

def request_cmm_submit(
    base_url: str,
    cmc: list,
    hid: str,
    phc: Dict[str, Any],
    user_pub: int,
    cmi_code: int | None = None,
    agent_type: str = "octopus",
) -> Dict[str, Any]:
    base_url = normalize_service_base_url(base_url)
    with httpx.Client(trust_env=False) as client:
        try:
            pub_resp = client.get(base_url.rstrip("/") + "/v1/ap/public_keys", timeout=10.0)
            pub_resp.raise_for_status()
            ap_dlog_pk = int(str(pub_resp.json()["ap_dlog_pk"]))
        except httpx.HTTPError:
            from agent_provider.ap import AP_PK as ap_dlog_pk
        try:
            hid_str = str(hid)
            is_hex = (len(hid_str) == 64 and all(c in "0123456789abcdefABCDEF" for c in hid_str))
            hid_use = hid_str if is_hex else sha256_hex(hid_str)
        except Exception:
            hid_use = sha256_hex(str(hid))
        llm_public_config = {}

        if str(agent_type or "").strip().lower() == "openclaw":
            try:
                from agent_provider.openclaw.openclaw_package import extract_llm_public_config
                llm_public_config = extract_llm_public_config(cmc or [])
            except Exception:
                llm_public_config = {}

        obj = {
            "CMC": cmc,
            "HID": hid_use,
            "PHC": phc,
            "agent_type": agent_type,
        }

        if llm_public_config:
            obj["llm_public_config"] = llm_public_config
        if cmi_code is not None:
            try:
                obj["CMI_code"] = str(int(cmi_code))
            except Exception:
                obj["CMI_code"] = str(cmi_code)
        # Use crypto_lib ElGamal with raw JSON bytes for compatibility
        from crypto_lib import elgamal_encrypt_bytes as ap_elg_enc
        raw = json.dumps(obj, separators=(",", ":")).encode()
        cmc_enc = ap_elg_enc(ap_dlog_pk, raw)
        url = base_url.rstrip("/") + "/v1/ap/cmm_submit"
        try:
            resp = client.post(url, json={"cmc_enc": cmc_enc, "user_pub": user_pub}, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            return data
        except httpx.HTTPError:
            from agent_provider.ap import cmm_submit, CMMSubmitRequest
            out = cmm_submit(CMMSubmitRequest(cmc_enc=cmc_enc, user_pub=user_pub))
            return out


def _elg_decrypt(sk: int, c: Dict[str, Any]) -> bytes:
    from crypto_lib import elgamal_decrypt_bytes
    return elgamal_decrypt_bytes(sk, c)
def request_phc_recover(base_url: str, user: UserInfo, did: str | None = None) -> Dict[str, Any]:
    base_url = normalize_service_base_url(base_url)
    with httpx.Client(trust_env=False) as client:
        pub_resp = client.get(base_url.rstrip("/") + "/v1/tp/public_keys", timeout=10.0)
        pub_resp.raise_for_status()
        tp_keys = pub_resp.json()
        tp_dlog_pk = int(str(tp_keys["tp_dlog_pk"]))
        sk_a, pk_a = dl_generate_user_keypair()
        pii = user.pii.model_dump()
        bi = user.bi.model_dump()
        pt = {"PII": pii, "BI": bi, "ID": pii.get("id_number")}
        if did:
            pt["DID"] = did
        from crypto_lib import elgamal_encrypt_bytes as tp_elg_enc
        raw = json.dumps(pt, separators=(",", ":")).encode()
        rec = tp_elg_enc(tp_dlog_pk, raw)
        url = base_url.rstrip("/") + "/v1/tp/recover_phc"
        resp = client.post(url, json={"rec": rec, "user_pub": pk_a}, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        phc_enc = data.get("phc_enc")
        if not phc_enc:
            return data
        raw = _elg_decrypt(sk_a, phc_enc)
        return json.loads(raw.decode())
def request_phc_application_status(base_url: str, request_id: str) -> Dict[str, Any]:
    base_url = normalize_service_base_url(base_url)
    with httpx.Client(trust_env=False) as client:
        url = base_url.rstrip("/") + f"/v1/tp/applications/{request_id}/status"
        resp = client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
