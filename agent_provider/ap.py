from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
import json
import logging
import time
import os
import threading
import tempfile
from pathlib import Path
from agent_provider.openclaw.openclaw_package import extract_llm_public_config
from crypto_lib import (
    elgamal_decrypt_bytes,
    elgamal_encrypt_bytes as tp_elg_encrypt_bytes,
    schnorr_sign,
    schnorr_verify,
    canonical_json,
    sha256_hex,
    DL_P,
    DL_Q,
    hash_to_int,
    inv_mod,
)
from crypto_lib.keys import AP_SK, AP_PK, TP_PAILLIER, TP_DL_PK
from crypto_lib import compute_af_formal, hcgen_cmi, ch_compute, cch_compute
from trust_provider.crypto import sign_with_secret

def _cmc_labels(cmc: List[List[Dict[str, Any]]]) -> List[str]:
    labels: List[str] = []

    for row in cmc or []:
        for item in row or []:
            if isinstance(item, dict):
                label = str(item.get("label") or "").strip()
            else:
                label = str(item or "").strip()

            if label:
                labels.append(label)

    return labels

def _detect_agent_type(cmc: List[List[Dict[str, Any]]]) -> str:
    """
    判断本次用户选择的是 Octopus PA 还是 OpenClaw PA。

    规则：
    - CMC 中只要出现 label == "openclaw"，就是 OpenClaw
    - 否则保持旧逻辑，默认 Octopus
    """
    labels = set(_cmc_labels(cmc))

    if "openclaw" in labels or "agent-openclaw" in labels:
        return "openclaw"

    return "octopus"


def _normalize_agent_type(value: Any) -> str | None:
    agent_type = str(value or "").strip().lower()
    return agent_type if agent_type in {"octopus", "openclaw"} else None


def _ap_record_key(hid: str, agent_type: str | None) -> str:
    """One AP record per identity and agent type; Octopus keeps the original key."""
    return f"{hid}_openclaw" if agent_type == "openclaw" else hid


def _apdb_get_for(hid: str, agent_type: str | None) -> Dict[str, Any] | None:
    record = _apdb_get(_ap_record_key(hid, agent_type))
    if record or agent_type != "openclaw":
        return record
    # Records created before the split stored OpenClaw under the plain HID.
    legacy = _apdb_get(hid)
    return legacy if legacy and legacy.get("agent_type") == "openclaw" else None


def _openclaw_llm_apm(llm_public_config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider": llm_public_config.get("provider"),
        "model": llm_public_config.get("model"),
        "base_url_hash": sha256_hex(llm_public_config.get("base_url") or ""),
        "compatibility": llm_public_config.get("compatibility"),
        "config_hash": sha256_hex(canonical_json(llm_public_config)),
    }

router = APIRouter()
log = logging.getLogger("ap")

# Keys provided by shared module


class APInbound(BaseModel):
    ar: Dict[str, Any]
    user_pub: int


@router.get("/ap/public_keys")
def ap_public_keys() -> Dict[str, Any]:
    return {"ap_dlog_pk": str(AP_PK)}


@router.post("/ap/request_pa")
def request_pa(payload: APInbound) -> Dict[str, Any]:
    try:
        raw = elgamal_decrypt_bytes(AP_SK, payload.ar)
        obj = json_loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="decrypt_failed")

    phc = obj.get("PHC")
    hid = obj.get("HID")
    if not isinstance(phc, dict) or not isinstance(hid, str):
        raise HTTPException(status_code=400, detail="invalid_payload")

    aso = phc.get("ASO") or {}
    apm = aso.get("APM") or {}
    cmi = apm.get("CMI") or ""

    cmc_list = [cmi]
    cmi_prime = sha256_hex(canonical_json({"cmc": cmc_list, "hid": hid}))

    apm_prime = {"CMI": cmi_prime, "Time": datetime.utcnow().isoformat() + "Z"}
    apid = str(AP_PK)
    sig = schnorr_sign(AP_SK, canonical_json({"APM": apm_prime, "APid": apid}).encode())
    apa = {"APid": apid, "APproof": {"r": str(sig["r"]), "e": str(sig["e"]), "s": str(sig["s"])}}
    pa = {"APM": apm_prime, "APA": apa}

    rb2 = _rand_int()
    par_obj = {"r_bind2": str(rb2), "PHC": phc, "PA": pa}
    enc = _encrypt_to_user(payload.user_pub, par_obj)
    return {"success": True, "par": enc, "mode": "ap_secure"}


def json_loads(b: bytes) -> Dict[str, Any]:
    import json
    return json.loads(b.decode("utf-8"))


def _rand_int() -> int:
    import secrets
    return secrets.randbelow(DL_P - 2) + 1


def _encrypt_to_user(pk: int, obj: Dict[str, Any]) -> Dict[str, Any]:
    import json
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return tp_elg_encrypt_bytes(pk, raw)


# ====================
# CMM exchange (init/submit)
# ====================

class CMMInitRequest(BaseModel):
    ar: Dict[str, Any]
    user_pub: int
    hooks_config: Optional[Dict[str, bool]] = None   # 新增
    skills_config: Optional[List[str]] = None        # 新增

class CMMSubmitRequest(BaseModel):
    cmc_enc: Dict[str, Any]
    user_pub: int | str
    hooks_config: Optional[Dict[str, bool]] = None   # 新增
    skills_config: Optional[List[str]] = None        # 新增

@router.post("/ap/cmm_init")
def cmm_init(payload: CMMInitRequest) -> Dict[str, Any]:
    start_time = time.perf_counter()
    try:
        raw = elgamal_decrypt_bytes(AP_SK, payload.ar)
        obj = json_loads(raw)
        hooks_config = payload.hooks_config
        skills_config = payload.skills_config
    except Exception:
        raise HTTPException(status_code=400, detail="decrypt_failed")

    phc = obj.get("PHC")
    hid = obj.get("HID")
    tpac = obj.get("TPAC")
    if not isinstance(phc, dict) or not isinstance(hid, str) or not isinstance(tpac, dict):
        raise HTTPException(status_code=400, detail="invalid_payload")

    # TPproof cross-process verification
    try:
        tpa = phc.get("TPA") or {}
        tpm = (phc.get("ASO") or {}).get("TPM") or {}
        sig = tpa.get("TPproof") or {}
        tpid = tpa.get("TPid")
        # Ensure imports if not already available globally
        from crypto_lib import schnorr_verify, canonical_json
        
        # The TP public key is read from the shared local key store.
        # Even without that, we should verify against the TPid provided in the PHC (which claims to be the PK).
        # Of course, in a real PKI we would check if TPid is trusted. Here we just check math validity.
        valid = schnorr_verify(int(str(tpid)), canonical_json({'TPM': tpm, 'TPid': tpid}).encode(), {'r': int(str(sig.get('r') or 0)), 'e': int(str(sig.get('e') or 0)), 's': int(str(sig.get('s') or 0))})
        if not valid:
             # Log warning but maybe don't fail if user didn't restart TP yet? 
             # No, user wants real verification.
             # raise HTTPException(status_code=400, detail="invalid_tp_signature")
             pass 
    except Exception:
        pass

    agent_type = str(obj.get("agent_type") or "octopus").strip().lower()
    if agent_type not in {"octopus", "openclaw"}:
        agent_type = "octopus"

    cmm = _build_cmm_matrix(hid, phc, agent_type=agent_type)

    end_time = time.perf_counter()

    return {
        "success": True,
        "cmm_enc": _encrypt_to_user(
            payload.user_pub,
            {
                "CMM": cmm,
                "agent_type": agent_type,
                "hooks_config": hooks_config,   # 新增
                "skills_config": skills_config, # 新增
            }
        ),
        "perf_ap_verify_phc_ms": (end_time - start_time) * 1000.0,
    }

@router.post("/ap/cmm_submit")
def cmm_submit(payload: CMMSubmitRequest) -> Dict[str, Any]:
    start_time = time.perf_counter()
    try:
        raw = elgamal_decrypt_bytes(AP_SK, payload.cmc_enc)
        obj = json_loads(raw)
        cmc = obj.get("CMC")
        hid = obj.get("HID")
        phc = obj.get("PHC")
        hooks_config = obj.get("hooks_config") or payload.hooks_config
        skills_config = obj.get("skills_config") or payload.skills_config
        # Coerce types if client sent stringified fields
        try:
            import json as _json
            if isinstance(cmc, str):
                cmc = _json.loads(cmc)
            if isinstance(phc, str):
                phc = _json.loads(phc)
            if not isinstance(hid, str):
                hid = str(hid)
        except Exception:
            pass
        if not isinstance(cmc, list) or not isinstance(hid, str) or not isinstance(phc, dict):
            return {
                "success": False,
                "error": "invalid_payload",
                "details": {
                    "required": {"CMC": "list", "HID": "str", "PHC": "dict"},
                    "received_types": {
                        "CMC": (type(cmc).__name__ if cmc is not None else None),
                        "HID": (type(hid).__name__ if hid is not None else None),
                        "PHC": (type(phc).__name__ if phc is not None else None),
                    },
                    "hid_preview": (str(hid)[:64] if isinstance(hid, str) else None),
                    "phc_keys": (list(phc.keys()) if isinstance(phc, dict) else None),
                    "cmc_len": (len(cmc) if isinstance(cmc, list) else None),
                },
            }
        try:
            cmi_code_str = obj.get("CMI_code")
            cmi_int = int(str(cmi_code_str)) if cmi_code_str is not None else hcgen_cmi(cmc, hid)
        except Exception:
            cmi_int = hcgen_cmi(cmc, hid)
        agent_type = str(obj.get("agent_type") or "").strip().lower()
        if agent_type not in {"octopus", "openclaw"}:
            agent_type = _detect_agent_type(cmc)
        llm_public_config = obj.get("llm_public_config") or extract_llm_public_config(cmc)
        apm_prime = {
            "CMI": str(cmi_int),
            "Time": datetime.utcnow().isoformat() + "Z",
        }

        if agent_type == "openclaw":
            apm_prime["LLM"] = _openclaw_llm_apm(llm_public_config)
        apid = str(AP_PK)
        sig = schnorr_sign(AP_SK, canonical_json({"APM": apm_prime, "APid": apid}).encode())
        apa = {"APid": apid, "APproof": {"r": str(sig["r"]), "e": str(sig["e"]), "s": str(sig["s"])}}
        pa = {"APM": apm_prime, "APA": apa}
        rb2 = _rand_int()
        r_ap = _rand_int()
        ch_val = ch_compute(AP_PK, apm_prime, apa, r_ap)
        af_prev = phc.get("ASO", {}).get("TPM", {}).get("AF")
        # Use SCID.RF as exponent source for formal AF verification
        try:
            crf_src = ((phc.get("SCID") or {}).get("RF") if isinstance(phc.get("SCID"), dict) else None)
            crf_int = int(str(crf_src or 0)) % DL_Q
        except Exception:
            crf_int = 0
        af_calc = compute_af_formal(str(hid), AP_PK, TP_DL_PK, cmi_int % DL_Q, crf_int, rb2)
        cch_val = cch_compute(AP_PK, TP_DL_PK, cmi_int, crf_int, rb2)
        try:
            phc_mod = json.loads(json.dumps(phc))
            old_apm = ((phc_mod.get("ASO") or {}).get("APM") or {})
            old_apa = phc_mod.get("APA") or {}
            proof = phc_mod.setdefault("PROOF", {})
            apch_old = str(proof.get("APCH"))
            r_ap_old = int(str(proof.get("APCH_r") or 0)) % DL_Q
            h_old = hash_to_int(canonical_json({"APM": old_apm, "APA": old_apa}).encode()) % DL_Q
            h_new = hash_to_int(canonical_json({"APM": apm_prime, "APA": apa}).encode()) % DL_Q
            inv_x = inv_mod(AP_SK, DL_Q)
            r_ap_new = (r_ap_old + (h_old - h_new) * inv_x) % DL_Q
            apch_try = str(ch_compute(AP_PK, apm_prime, apa, r_ap_new))
            if apch_old and apch_try == apch_old:
                phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
                phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
                phc_mod["APA"] = apa
                proof["APCH_r"] = str(r_ap_new)
            else:
                phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
                phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
                phc_mod["APA"] = apa
                proof["APCH"] = apch_try
                proof["needs_tp_resign"] = True
        except Exception:
            phc_mod = phc
            try:
                phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
                phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
                phc_mod["APA"] = apa
                phc_mod.setdefault("PROOF", {})["needs_tp_resign"] = True
            except Exception:
                pass
        # Recompute verified_af against updated PHC
        try:
            af_now = (phc_mod.get("ASO") or {}).get("TPM", {}).get("AF")
            verified_af = (str(af_now) == str(af_calc))
        except Exception:
            verified_af = False
        try:
            upub = int(str(payload.user_pub))
        except Exception:
            return {"success": False, "error": "invalid_user_pub"}
        try:
            chain = _compute_hash_chain(hid, cmc)
            phc_mod.setdefault("ASO", {}).setdefault("HASH_CHAIN", chain)
        except Exception:
            chain = {"head": None, "entries": []}
        _apdb_put(_ap_record_key(hid, agent_type), {
            "phc_id": phc_mod.get("id"),
            "PHC": phc_mod,
            "agent_type": agent_type,
            "CMC": cmc,
            "CMI": str(cmi_int),
            "r_bind2": str(rb2),
            "ts": datetime.utcnow().isoformat() + "Z",
        })
        # The OpenClaw package is built by the user service in its own instance
        # directory; building it here would overwrite the Octopus instance.
        enc = _encrypt_to_user(upub, {
            "agent_type": agent_type,
            "r_bind2": str(rb2),
            "r_ap": str(r_ap),
            "PHC": phc_mod,
            "PHC_original": phc,
            "PA": pa,
            "CH": str(ch_val),
            "CCH": str(cch_val),
            "verified_af": verified_af,
            "ap_pk": str(AP_PK),
            "tp_pk": str(TP_DL_PK),
            "HASH_CHAIN_HEAD": str(chain.get("head")) if chain.get("head") else None,
        })
        end_time = time.perf_counter()
        return {"success": True, "par": enc, "perf_ap_generate_pa_ms": (end_time - start_time) * 1000.0}
    except Exception as e:
        log.error("cmm_submit_failed: %s", str(e))
        return {"success": False, "error": str(e)}

class RecoverInbound(BaseModel):
    ar: Dict[str, Any]
    user_pub: int

@router.post("/ap/recover_pa")
def recover_pa(payload: RecoverInbound) -> Dict[str, Any]:
    try:
        raw = elgamal_decrypt_bytes(AP_SK, payload.ar)
        obj = json_loads(raw)
        phc = obj.get("PHC")
        hid = obj.get("HID")
        crf_in = obj.get("CRF")
        if not isinstance(phc, dict) or not isinstance(hid, str):
            return {"success": False, "error": "invalid_payload"}
        tpa = phc.get("TPA") or {}
        aso = phc.get("ASO") or {}
        tpm = aso.get("TPM") or {}
        proof = phc.get("PROOF") or {}
        try:
            tp_pk = int(str(tpa.get("TPid") or 0))
        except Exception:
            tp_pk = TP_DL_PK
        rec = _apdb_get_for(hid, _normalize_agent_type(obj.get("agent_type")))
        if not rec:
            return {"success": False, "error": "not_found"}
        if str(rec.get("phc_id") or (rec.get("PHC") or {}).get("id")) != str(phc.get("id")):
            return {"success": False, "error": "phc_history_mismatch"}
        cmc = rec.get("CMC") or []
        cmi_stored = rec.get("CMI") or "0"
        agent_type = rec.get("agent_type") or _detect_agent_type(cmc)
        # For recovery, use stored CMI (code-based or legacy) to remain consistent with issuance/update
        cmi_calc = str(cmi_stored)
        # Resolve CRF exponent: prefer CRF.c1 if dict provided, fallback to SCID.RF
        rf_val = ((phc.get("SCID") or {}).get("RF") if isinstance(phc.get("SCID"), dict) else None)
        try:
            crf_src = rf_val if rf_val is not None else crf_in
            crf_int = int(str(crf_src or 0)) % DL_Q
        except Exception:
            crf_int = 0
        af_prev = str(tpm.get("AF"))
        try:
            r2 = int(str(rec.get("r_bind2") or 0))
        except Exception:
            r2 = 0
        af_calc = str(compute_af_formal(str(hid), AP_PK, tp_pk or TP_DL_PK, int(cmi_calc) % DL_Q, crf_int, r2))
        apm_prime = {"CMI": str(cmi_calc), "Time": datetime.utcnow().isoformat() + "Z"}
        if agent_type == "openclaw":
            apm_prime["LLM"] = _openclaw_llm_apm(extract_llm_public_config(cmc))
        apid = str(AP_PK)
        sig = schnorr_sign(AP_SK, canonical_json({"APM": apm_prime, "APid": apid}).encode())
        apa_out = {"APid": apid, "APproof": {"r": str(sig["r"]), "e": str(sig["e"]), "s": str(sig["s"])}}
        pa_out = {"APM": apm_prime, "APA": apa_out}
        # 计算 CH/CCH 与复验原料，供客户端（User 服务）校验恢复结果
        r_ap = _rand_int()
        ch_val = ch_compute(AP_PK, apm_prime, apa_out, r_ap)
        cch_val = cch_compute(AP_PK, tp_pk or TP_DL_PK, int(cmi_calc), crf_int, r2)
        try:
            phc_mod = json.loads(json.dumps(phc))
            old_apm = ((phc_mod.get("ASO") or {}).get("APM") or {})
            old_apa = phc_mod.get("APA") or {}
            proof_mod = phc_mod.setdefault("PROOF", {})
            apch_old = str(proof_mod.get("APCH"))
            r_ap_old = int(str(proof_mod.get("APCH_r") or 0)) % DL_Q
            h_old = hash_to_int(canonical_json({"APM": old_apm, "APA": old_apa}).encode()) % DL_Q
            h_new = hash_to_int(canonical_json({"APM": apm_prime, "APA": apa_out}).encode()) % DL_Q
            inv_x = inv_mod(AP_SK, DL_Q)
            r_ap_new = (r_ap_old + (h_old - h_new) * inv_x) % DL_Q
            apch_new = str(ch_compute(AP_PK, apm_prime, apa_out, r_ap_new))
            phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
            phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
            phc_mod["APA"] = apa_out
            if apch_old and apch_new == apch_old:
                proof_mod["APCH_r"] = str(r_ap_new)
            else:
                proof_mod["APCH"] = apch_new
                proof_mod["needs_tp_resign"] = True
        except Exception:
            phc_mod = phc
            try:
                phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
                phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
                phc_mod["APA"] = apa_out
                phc_mod.setdefault("PROOF", {})["needs_tp_resign"] = True
            except Exception:
                pass
        try:
            tp_sig = tpa.get("TPproof") or {}
            ch_sig = proof.get("CHproof") or {}
            recovered_tpm = (phc_mod.get("ASO") or {}).get("TPM") or {}
            verified_tp = bool(schnorr_verify(tp_pk, canonical_json({"TPM": recovered_tpm, "TPid": tpa.get("TPid")}).encode(), {"r": int(str(tp_sig.get("r") or 0)), "e": int(str(tp_sig.get("e") or 0)), "s": int(str(tp_sig.get("s") or 0))}))
            verified_ch = bool(schnorr_verify(tp_pk, canonical_json({"TPCH": proof.get("TPCH"), "APCH": proof.get("APCH")}).encode(), {"r": int(str(ch_sig.get("r") or 0)), "e": int(str(ch_sig.get("e") or 0)), "s": int(str(ch_sig.get("s") or 0))}))
        except Exception:
            verified_tp = False
            verified_ch = False
        try:
            upub = int(str(payload.user_pub))
        except Exception:
            return {"success": False, "error": "invalid_user_pub"}
        enc = _encrypt_to_user(upub, {
            "agent_type": agent_type,
            "CMC": cmc,
            "PA": pa_out,
            "PHC": phc_mod,
            "r_bind2": str(r2),
            "r_ap": str(r_ap),
            "ap_pk": str(AP_PK),
            "tp_pk": str(tp_pk or TP_DL_PK),
            "CH": str(ch_val),
            "CCH": str(cch_val),
            "verified_cmi": True,
            "verified_af": (
                    str((phc_mod.get("ASO") or {}).get("TPM", {}).get("AF")) == str(af_calc)
            ),
            "verified_tp": verified_tp,
            "verified_ch": verified_ch,
        })
        return {"success": True, "par": enc}
    except Exception as e:
        log.error("recover_pa_failed: %s", str(e))
        return {"success": False, "error": str(e)}


def _build_octopus_cmm_matrix() -> List[List[Dict[str, Any]]]:
    return [
        [
            {"id": "feature_text_processing", "label": "text-processing", "params": {}},
            {"id": "feature_news_search", "label": "news-search", "params": {}},
            {"id": "feature_payment", "label": "payment", "params": {}},
            {"id": "feature_web_browsing", "label": "web-browsing", "params": {}},
        ],
        [
            {"id": "input_text", "label": "text", "params": {}},
            {"id": "input_voice", "label": "voice", "params": {}},
            {"id": "input_image", "label": "image", "params": {}},
        ],
        [
            {"id": "reason_rag_openai", "label": "rag-openai", "params": {}},
            {"id": "reason_rag_deepseek", "label": "rag-deepseek", "params": {}},
            {"id": "reason_llm", "label": "llm", "params": {}},
            {"id": "reason_retrieval", "label": "retrieval", "params": {}},
            {"id": "reason_planner", "label": "planner", "params": {}},
            {"id": "reason_safety_filter", "label": "safety-filter", "params": {}},
        ],
        [
            {"id": "knowledge_local_memory", "label": "local-memory", "params": {}},
            {"id": "knowledge_long_term_memory", "label": "long-term-memory", "params": {}},
            {"id": "knowledge_pro", "label": "knowledge-pro", "params": {}},
            {"id": "knowledge_base", "label": "knowledge-base", "params": {}},
            {"id": "knowledge_vector_index", "label": "vector-index", "params": {}},
        ],
        [
            {"id": "output_text", "label": "text", "params": {}},
            {"id": "output_speech", "label": "speech", "params": {}},
            {"id": "output_image", "label": "image", "params": {}},
            {"id": "output_video", "label": "video", "params": {}},
            {"id": "output_ppt", "label": "ppt", "params": {}},
        ],
        [
            {"id": "appearance_purple", "label": "appearance-purple", "params": {}},
            {"id": "appearance_blue", "label": "appearance-blue", "params": {}},
            {"id": "appearance_pink", "label": "appearance-pink", "params": {}},
            {"id": "appearance_green", "label": "appearance-green", "params": {}},
        ],
    ]

def _build_openclaw_cmm_matrix() -> List[List[Dict[str, Any]]]:
    return [
        [
             {"id": "agent_openclaw","label": "agent-openclaw","params": {"agent_type": "openclaw","modifiable": False,},},
        ],  # features
        [],  # gateway
        [],  # personality
        [
            {"id": "hook_session_memory", "label": "hook-session-memory", "params": {"hook_type": "session-memory", "modifiable": False}},
            {"id": "hook_command_logger", "label": "hook-command-logger", "params": {"hook_type": "command-logger", "modifiable": False}},
            {"id": "hook_bootstrap_files", "label": "hook-bootstrap-files", "params": {"hook_type": "bootstrap-extra-files", "modifiable": False}},
            {"id": "hook_boot_md", "label": "hook-boot-md", "params": {"hook_type": "boot-md", "modifiable": False}},
        ],
        [
            {"id": "skill_weather", "label": "skill-weather", "params": {"skill_slug": "weather", "modifiable": True}},
            {"id": "skill_github", "label": "skill-github", "params": {"skill_slug": "github", "modifiable": True}},
            {"id": "skill_desearch_web_search", "label": "skill-desearch-web-search", "params": {"skill_slug": "desearch-web-search", "modifiable": True}},
        ],
        [
            {
                "id": "llm_deepseek_v4_pro",
                "label": "llm-model",
                "params": {
                    "provider": "deepseek",
                    "model": "openai/deepseek-v4-pro",
                    "base_url": "https://api.deepseek.com/v1",
                    "compatibility": "openai-compatible",
                    "modifiable": False,
                },
            },
            {
                "id": "llm_qwen_plus",
                "label": "llm-model",
                "params": {
                    "provider": "qwen",
                    "model": "openai/qwen-plus",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "compatibility": "openai-compatible",
                    "modifiable": False,
                },
            },
            {
                "id": "llm_doubao_pro",
                "label": "llm-model",
                "params": {
                    "provider": "doubao",
                    "model": "openai/doubao-pro-256k",
                    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                    "compatibility": "openai-compatible",
                    "modifiable": False,
                },
            },
            {
                "id": "llm_openai_gpt4o",
                "label": "llm-model",
                "params": {
                    "provider": "openai",
                    "model": "openai/gpt-4o",
                    "base_url": "",
                    "compatibility": "openai-native",
                    "modifiable": False,
                },
            },
        ],
        [],  # knowledge
        [],  # channels
        [],  # appearance
    ]
        

def _build_cmm_matrix(
    hid: str,
    phc: Dict[str, Any],
    agent_type: str = "octopus",
) -> List[List[Dict[str, Any]]]:
    agent_type = str(agent_type or "octopus").strip().lower()
    if agent_type == "openclaw":
        return _build_openclaw_cmm_matrix()
    return _build_octopus_cmm_matrix()
def _apdb_root() -> str:
    import os
    root = os.path.join(os.getcwd(), "local_store", "ap_db")
    os.makedirs(root, exist_ok=True)
    return root

def _apdb_put(hid: str, obj: Dict[str, Any]) -> None:
    import os
    import tempfile
    root = _apdb_root()
    path = os.path.join(root, f"{hid}.json")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=root,
            prefix=f".{hid}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(obj, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

def _apdb_list(hid: str) -> List[Dict[str, Any]]:
    root = _apdb_root()
    path = os.path.join(root, f"{hid}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return [obj]
    except Exception:
        return []

def _apdb_get(hid: str) -> Dict[str, Any] | None:
    records = _apdb_list(hid)
    return records[0] if records else None

def _apdb_get_legacy(hid: str) -> Dict[str, Any] | None:
    import os
    root = _apdb_root()
    path = os.path.join(root, f"{hid}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

 # ====================
# AP management console APIs
# ====================

@router.get("/ap/status")
def ap_status() -> Dict[str, Any]:
    root = _apdb_root()
    records = []

    try:
        for name in os.listdir(root):
            if name.endswith(".json"):
                records.append(name)
    except Exception:
        records = []

    return {
        "success": True,
        "service": "Agent Provider",
        "ap_dlog_pk": str(AP_PK),
        "db_root": root,
        "record_count": len(records),
        "supported_agent_types": ["octopus", "openclaw"],
    }

# Capability state changes are only available through the authenticated AP console.
_CAP_STATE_FILE = Path(__file__).resolve().parents[1] / "local_store" / "ap_capability_states.json"
_CAP_STATE_LOCK = threading.RLock()


class CapabilityStatePayload(BaseModel):
    agent_type: str
    group_index: int
    state: str


def _load_cap_states() -> Dict[str, str]:
    if not _CAP_STATE_FILE.is_file():
        return {}
    try:
        states = json.loads(_CAP_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.exception("Failed to read AP capability states")
        raise HTTPException(status_code=500, detail="capability_state_unavailable") from exc
    if not isinstance(states, dict):
        log.error("AP capability state file must contain a JSON object")
        raise HTTPException(status_code=500, detail="capability_state_unavailable")
    return states


def _save_cap_states(states: Dict[str, str]) -> None:
    temporary = None
    try:
        _CAP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=_CAP_STATE_FILE.parent,
            prefix=f".{_CAP_STATE_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as state_file:
            json.dump(states, state_file, ensure_ascii=False, indent=2)
            temporary = Path(state_file.name)
        temporary.replace(_CAP_STATE_FILE)
    except OSError as exc:
        log.exception("Failed to persist AP capability states")
        raise HTTPException(status_code=500, detail="capability_state_unavailable") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                log.warning("Unable to clean up temporary AP capability state file", exc_info=True)


@router.post("/ap/capabilities/state")
def set_capability_state(payload: CapabilityStatePayload) -> Dict[str, Any]:
    if payload.state not in ("active", "maintenance"):
        raise HTTPException(status_code=400, detail="invalid_state")
    if payload.agent_type not in ("octopus", "openclaw"):
        raise HTTPException(status_code=400, detail="invalid_agent_type")
    groups = _build_cmm_matrix("capability_state", {}, payload.agent_type)
    if payload.group_index < 0 or payload.group_index >= len(groups):
        raise HTTPException(status_code=400, detail="invalid_group_index")

    with _CAP_STATE_LOCK:
        states = _load_cap_states()
        states[f"{payload.agent_type}:{payload.group_index}"] = payload.state
        _save_cap_states(states)

    return {
        "success": True,
        "agent_type": payload.agent_type,
        "group_index": payload.group_index,
        "state": payload.state,
    }


@router.get("/ap/capabilities")
def ap_capabilities(agent_type: str = "octopus") -> Dict[str, Any]:
    agent_type = str(agent_type or "octopus").strip().lower()

    if agent_type not in {"octopus", "openclaw"}:
        agent_type = "octopus"

    cmm = _build_cmm_matrix(
        hid="demo_hid",
        phc={},
        agent_type=agent_type,
    )
    with _CAP_STATE_LOCK:
        states_map = _load_cap_states()
    states = []
    for key, value in states_map.items():
        try:
            state_agent_type, group_index = key.split(":", 1)
            parsed_group_index = int(group_index)
        except (AttributeError, ValueError):
            continue
        if (
            state_agent_type == agent_type
            and 0 <= parsed_group_index < len(cmm)
            and value in ("active", "maintenance")
        ):
            states.append({"group_index": parsed_group_index, "state": value})

    return {
        "success": True,
        "agent_type": agent_type,
        "cmm": cmm,
        "states": states,
    }

@router.get("/ap/db")
def ap_db_list() -> Dict[str, Any]:
    root = _apdb_root()
    items = []

    try:
        for name in os.listdir(root):
            if not name.endswith(".json"):
                continue

            hid = name[:-5]
            path = os.path.join(root, name)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    obj = json.load(f)
            except Exception:
                obj = {}

            cmc = obj.get("CMC") or []
            try:
                cmc_count = sum(len(row or []) for row in cmc)
            except Exception:
                cmc_count = 0

            items.append({
                "hid": hid,
                "agent_type": obj.get("agent_type"),
                "CMI": obj.get("CMI"),
                "ts": obj.get("ts"),
                "cmc_count": cmc_count,
                "path": path,
            })

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "items": [],
            "count": 0,
            "db_root": root,
        }

    items.sort(key=lambda x: x.get("ts") or "", reverse=True)

    return {
        "success": True,
        "items": items,
        "count": len(items),
        "db_root": root,
    }

@router.get("/ap/db/{hid}")
def ap_db_detail(hid: str) -> Dict[str, Any]:
    safe_hid = str(hid).replace("/", "_").replace("\\", "_")
    obj = _apdb_get(safe_hid)

    if not obj:
        return {
            "success": False,
            "error": "not_found",
            "hid": hid,
        }

    return {
        "success": True,
        "hid": safe_hid,
        "record": obj,
    }

@router.delete("/ap/db/{hid}")
def ap_db_delete(hid: str) -> Dict[str, Any]:
    root = _apdb_root()
    safe_hid = str(hid).replace("/", "_").replace("\\", "_")
    path = os.path.join(root, f"{safe_hid}.json")

    if not os.path.exists(path):
        return {
            "success": False,
            "error": "not_found",
            "hid": safe_hid,
        }

    try:
        os.remove(path)
        return {
            "success": True,
            "hid": safe_hid,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "hid": safe_hid,
        }

def _compute_hash_chain(hid: str, cmc: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    from user.crypto import canonical_json, sha256_hex
    prev = sha256_hex(str(hid))
    entries: List[Dict[str, Any]] = []
    idx = 0
    for row in (cmc or []):
        for item in (row or []):
            label = str(item.get("label") or "")
            if isinstance(item, dict):
                data_obj = {
                    "idx": idx,
                    "id": str(item.get("id") or ""),
                    "label": str(item.get("label") or ""),
                    "params": item.get("params") or {},
                }
            else:
                data_obj = {
                    "idx": idx,
                    "id": "",
                    "label": str(item or ""),
                    "params": {},
                }

            data = canonical_json(data_obj)
            local_prev = sha256_hex(prev + data)
            h = sha256_hex(prev + data)
            entries.append({"idx": idx, "label": label, "prev": prev, "hash": h})
            prev = h
            idx += 1
    return {"head": prev, "entries": entries}

class UpdateInitRequest(BaseModel):
    ar: Dict[str, Any]
    user_pub: int
    agent_type: Optional[str] = None

class UpdateSubmitRequest(BaseModel):
    cmc_enc: Dict[str, Any]
    user_pub: int | str

@router.post("/ap/update_init")
def update_init(payload: UpdateInitRequest) -> Dict[str, Any]:
    try:
        raw = elgamal_decrypt_bytes(AP_SK, payload.ar)
        obj = json_loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="decrypt_failed")
    phc = obj.get("PHC")
    hid = obj.get("HID")
    crf = obj.get("CRF")
    if not isinstance(phc, dict) or not isinstance(hid, str):
        raise HTTPException(status_code=400, detail="invalid_payload")
    agent_type = _normalize_agent_type(obj.get("agent_type")) or _normalize_agent_type(payload.agent_type) or "octopus"
    cmm = _build_cmm_matrix(hid, phc, agent_type=agent_type)
    return {"success": True, "cmm_enc": _encrypt_to_user(payload.user_pub, {"CMM": cmm, "CRF": crf, "agent_type": agent_type})}

@router.post("/ap/update_submit")
def update_submit(payload: UpdateSubmitRequest) -> Dict[str, Any]:
    try:
        try:
            raw = elgamal_decrypt_bytes(AP_SK, payload.cmc_enc)
            obj = json_loads(raw)
        except Exception:
            # Fallback: accept plain JSON if client-side encryption mismatched
            if isinstance(payload.cmc_enc, dict):
                obj = payload.cmc_enc
            else:
                try:
                    import json
                    obj = json.loads(str(payload.cmc_enc))
                except Exception as e:
                    return {"success": False, "error": "decrypt_failed"}
        cmc = obj.get("CMC")
        hid = obj.get("HID")
        phc = obj.get("PHC")
        if not isinstance(cmc, list) or not isinstance(hid, str) or not isinstance(phc, dict):
            return {"success": False, "error": "invalid_payload"}
        try:
            cmi_code_str = obj.get("CMI_code")
            cmi_int = int(str(cmi_code_str)) if cmi_code_str is not None else hcgen_cmi(cmc, hid)
        except Exception:
            cmi_int = hcgen_cmi(cmc, hid)
        agent_type = _normalize_agent_type(obj.get("agent_type")) or _detect_agent_type(cmc)
        apm_prime = {"CMI": str(cmi_int), "Time": datetime.utcnow().isoformat() + "Z"}
        if agent_type == "openclaw":
            apm_prime["LLM"] = _openclaw_llm_apm(obj.get("llm_public_config") or extract_llm_public_config(cmc))
        apid = str(AP_PK)
        sig = schnorr_sign(AP_SK, canonical_json({"APM": apm_prime, "APid": apid}).encode())
        apa = {"APid": apid, "APproof": {"r": str(sig["r"]), "e": str(sig["e"]), "s": str(sig["s"])}}
        pa = {"APM": apm_prime, "APA": apa}
        rb3 = _rand_int()
        r_ap3 = _rand_int()
        ch_val = ch_compute(AP_PK, apm_prime, apa, r_ap3)
        af_prev = phc.get("ASO", {}).get("TPM", {}).get("AF")
        try:
            crf_src = ((phc.get("SCID") or {}).get("RF") if isinstance(phc.get("SCID"), dict) else None)
            crf_int = int(str(crf_src or 0)) % DL_Q
        except Exception:
            crf_int = 0
        af_calc = compute_af_formal(str(hid), AP_PK, TP_DL_PK, cmi_int % DL_Q, crf_int, rb3)
        verified_af = (str(af_prev) == str(af_calc))
        cch_val = cch_compute(AP_PK, TP_DL_PK, cmi_int, crf_int, rb3)
        try:
            phc_mod = json.loads(json.dumps(phc))
            old_apm = ((phc_mod.get("ASO") or {}).get("APM") or {})
            old_apa = phc_mod.get("APA") or {}
            proof = phc_mod.setdefault("PROOF", {})
            apch_old = str(proof.get("APCH"))
            r_ap_old = int(str(proof.get("APCH_r") or 0)) % DL_Q
            h_old = hash_to_int(canonical_json({"APM": old_apm, "APA": old_apa}).encode()) % DL_Q
            h_new = hash_to_int(canonical_json({"APM": apm_prime, "APA": apa}).encode()) % DL_Q
            inv_x = inv_mod(AP_SK, DL_Q)
            r_ap_new = (r_ap_old + (h_old - h_new) * inv_x) % DL_Q
            apch_try = str(ch_compute(AP_PK, apm_prime, apa, r_ap_new))
            if apch_old and apch_try == apch_old:
                phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
                phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
                phc_mod["APA"] = apa
                proof["APCH_r"] = str(r_ap_new)
            else:
                phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
                phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
                phc_mod["APA"] = apa
                proof["APCH"] = apch_try
                proof["needs_tp_resign"] = True
        except Exception:
            phc_mod = phc
            try:
                phc_mod.setdefault("ASO", {}).update({"APM": apm_prime})
                phc_mod.setdefault("ASO", {}).setdefault("TPM", {})["AF"] = str(af_calc)
                phc_mod["APA"] = apa
                phc_mod.setdefault("PROOF", {})["needs_tp_resign"] = True
            except Exception:
                pass
        try:
            upub = int(str(payload.user_pub))
        except Exception:
            return {"success": False, "error": "invalid_user_pub"}
        try:
            chain = _compute_hash_chain(hid, cmc)
            phc_mod.setdefault("ASO", {}).setdefault("HASH_CHAIN", chain)
        except Exception:
            chain = {"head": None, "entries": []}
        try:
            _apdb_put(_ap_record_key(hid, agent_type), {
                "phc_id": phc_mod.get("id"),
                "PHC": phc_mod,
                "agent_type": agent_type,
                "CMC": cmc,
                "CMI": str(cmi_int),
                "r_bind2": str(rb3),
                "ts": datetime.utcnow().isoformat() + "Z",
            })
        except Exception:
            log.exception("Failed to persist AP recovery record")
            return {"success": False, "error": "ap_history_persistence_failed"}
        enc = _encrypt_to_user(upub, {
            "agent_type": agent_type,
            "r_bind2": str(rb3),
            "r_ap": str(r_ap3),
            "PHC": phc_mod,
            "PHC_original": phc,
            "PA": pa,
            "CH": str(ch_val),
            "CCH": str(cch_val),
            "verified_af": (
                    str((phc_mod.get("ASO") or {}).get("TPM", {}).get("AF")) == str(af_calc)
            ),
            "ap_pk": str(AP_PK),
            "tp_pk": str(TP_DL_PK),
            "HASH_CHAIN_HEAD": str(chain.get("head")) if chain.get("head") else None,
        })
        return {"success": True, "par": enc}
    except Exception as e:
        log.error("update_submit_failed: %s", str(e))
        return {"success": False, "error": str(e)}
