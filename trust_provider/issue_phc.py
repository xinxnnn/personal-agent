"""FastAPI router exposing TP endpoints.

Existing endpoints:
- POST /tp/issue_phc  -> issue PHC with given ASO payload (returns PHC JSON-LD)
- POST /tp/verify_phc -> verify a PHC structure
- POST /tp/trace      -> trace identity using RF ciphertext (stub decrypt)

New secure flow additions:
- GET  /tp/public_keys -> returns TP RSA public key for encrypted requests
    Secure branch of /tp/issue_phc accepts encrypted payload: {cr, user_pub, sig}
    where:
        cr       = base64(RSA-OAEP(JSON)) with TP public key
        user_pub = base64(raw Ed25519 public key 32 bytes)
        sig      = base64(Ed25519 signature over raw r_bind bytes)

Plain legacy path (af,cmi,cdid,ecid) still works for backward compatibility.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

from .phc import build_phc, verify_phc, phc_to_json
from crypto_lib import (
    paillier_decrypt,
    paillier_encrypt,
    sign_with_secret,
    canonical_json,
    elgamal_decrypt_bytes,
    schnorr_sign,
    schnorr_verify,
    compute_af,
    compute_af_formal,
    kdf_s1,
    sym_encrypt,
    sym_decrypt,
    cch_hash,
    DL_P,
    ipfs_put,
    ipfs_get,
    crf_encrypt,
)
from crypto_lib.keys import TP_PAILLIER, TP_DL_SK, TP_DL_PK, AP_SK, AP_PK
import base64
import json
import logging
from pydantic import BaseModel
import hashlib
import secrets
import os
import time
import sys
try:
    import pymysql
except Exception:
    pymysql = None

log = logging.getLogger("tp")
from datetime import datetime

router = APIRouter()

def _mysql_get_pic_string_by_user_id(user_id: str) -> Optional[str]:
    if pymysql is None:
        raise HTTPException(status_code=500, detail={
            "error": "db_driver_missing",
            "python": sys.version,
            "executable": sys.executable,
            "cwd": os.getcwd(),
        })
    host = os.getenv("MYSQL_HOST") or "127.0.0.1"
    port = int(os.getenv("MYSQL_PORT") or "3306")
    user = os.getenv("MYSQL_USER") or "root"
    password = os.getenv("MYSQL_PASSWORD") or "1234"
    db = os.getenv("MYSQL_DB") or "avatar"
    table = os.getenv("MYSQL_TABLE") or "bi"
    try:
        conn = pymysql.connect(host=host, port=port, user=user, password=password, database=db, charset="utf8mb4", connect_timeout=3)
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT `pic_string` FROM `{table}` WHERE `user_id`=%s LIMIT 1", (user_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return row[0] if isinstance(row, (tuple, list)) else None
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "error": "db_check_failed",
            "host": host,
            "port": port,
            "user": user,
            "db": db,
            "table": table,
            "reason": str(e),
        })


class TPMModel(BaseModel):
    Time: Optional[str] = None
    CDID: Optional[str] = None
    AF: str
    ECID: Optional[str] = None


class APMModel(BaseModel):
    Time: Optional[str] = None
    CMI: str


class ASOCompleteModel(BaseModel):
    TPM: Optional[TPMModel] = None
    APM: Optional[APMModel] = None

    # Fallback simplified inputs to auto-build TPM/APM if not provided
    af: Optional[str] = None
    cdid: Optional[str] = None
    ecid: Optional[str] = None
    cmi: Optional[str] = None


class PHCModel(BaseModel):
    phc: Dict[str, Any]


class UpdatedPHCRequest(BaseModel):
    hid: str
    candidate_phc: Dict[str, Any]
    pa: Dict[str, Any]
    r_bind2: int | str


class TraceRequest(BaseModel):
    rf_ciphertext: str

class RevealByDidRequest(BaseModel):
    did: str


class SecureInbound(BaseModel):
    cr: Dict[str, Any]
    user_pub: int
    sig: Dict[str, int]


# Keys are provided by shared module


@router.post("/tp/issue_phc")
def issue_phc(aso: ASOCompleteModel) -> Dict[str, Any]:
    """Issue a PHC for the provided ASO (Agent Self-Owned) payload.

    This endpoint will:
    - Construct ASO.TPM/APM (if missing) with required fields
    - Create TPA {TPid, TPproof} and APA {APid, APproof} placeholders
    - Compute PROOF {TPCH, APCH, CHproof, VM}
    - Return constructed PHC JSON-LD
    """
    from datetime import datetime


    # SECURE BRANCH: detect encrypted content by raw dict keys (FastAPI parsed model won't include them)
    # We access the request body via dependency injection less easily here; instead allow an alternate function below.
    # To keep backwards compatibility, we implement a sibling secure endpoint using raw dict payload.
    # This function remains the legacy/plain issuance path.
    # 1) Build ASO (TPM/APM)
    if aso.TPM and aso.APM:
        tpm = aso.TPM.model_dump()
        apm = aso.APM.model_dump()
        tpm.setdefault("Time", datetime.utcnow().isoformat() + "Z")
        apm.setdefault("Time", datetime.utcnow().isoformat() + "Z")
    else:
        if not aso.af or not aso.cmi:
            raise HTTPException(status_code=400, detail="Missing 'af' or 'cmi' for ASO when TPM/APM not provided")
        # Construct SCID and DID per spec (SCID = {AF, RF}); RF unavailable in legacy path -> use 0
        scid_af = aso.af
        scid_rf = 0
        did = f"did:wba:{scid_af}.{scid_rf}:{(aso.cdid or 'example').split(':')[-1]}"
        tpm = {
            "Time": datetime.utcnow().isoformat() + "Z",
            "CDID": did,
            "AF": scid_af,
            "ECID": aso.ecid or "g",
        }
        apm = {
            "Time": datetime.utcnow().isoformat() + "Z",
            "CMI": aso.cmi,
        }

    aso_built = {"TPM": tpm, "APM": apm}

    # 2) TPA: use TP public key as TPid
    tpid = str(TP_DL_PK)
    from crypto_lib import schnorr_sign
    tpproof_sig = schnorr_sign(TP_DL_SK, canonical_json({"TPM": tpm, "TPid": tpid}).encode())
    tpa = {"TPid": tpid, "TPproof": {"r": str(tpproof_sig["r"]), "e": str(tpproof_sig["e"]), "s": str(tpproof_sig["s"])}}

    # 3) APA: use AP public key as APid
    apid = str(AP_PK)
    approof_sig = schnorr_sign(AP_SK, canonical_json({"APM": apm, "APid": apid}).encode())
    apa = {"APid": apid, "APproof": {"r": str(approof_sig["r"]), "e": str(approof_sig["e"]), "s": str(approof_sig["s"])}}

    # 4) Build PHC with PROOF fields (use formal CH for TPCH/APCH)
    # Attach SCID when available (legacy path uses RF=0)
    phc = build_phc(aso=aso_built, tpa=tpa, apa=apa, tp_sk=TP_DL_SK, tp_pk=TP_DL_PK, ap_pk=AP_PK)
    phc.setdefault("SCID", {"AF": tpm.get("AF"), "RF": scid_rf})

    return {"success": True, "phc": phc}


@router.get("/tp/public_keys")
def get_public_keys() -> Dict[str, Any]:
    return {
        "tp_dlog_pk": str(TP_DL_PK),
        "ap_dlog_pk": str(AP_PK),
        "dl_params": {"p": str(DL_P), "g": str(5)},
        "paillier_pub": {"n": str(TP_PAILLIER.public.get("n")), "g": str(TP_PAILLIER.public.get("g"))},
    }


@router.post("/tp/reissue_updated_phc")
def reissue_updated_phc(payload: UpdatedPHCRequest) -> Dict[str, Any]:
    """Re-sign an AP configuration change against an already approved identity."""
    hid = str(payload.hid).lower()
    if len(hid) != 64 or any(char not in "0123456789abcdef" for char in hid):
        raise HTTPException(status_code=400, detail="invalid_hid")
    record = _tpdb_get(hid)
    if not record or not record.get("request_id"):
        raise HTTPException(status_code=404, detail="approved_identity_not_found")
    application = _tpapp_get(record["request_id"])
    if not application or application.get("status") != "issued":
        raise HTTPException(status_code=403, detail="identity_not_approved")
    previous = record.get("phc") or {}
    candidate = payload.candidate_phc
    pa = payload.pa
    if not verify_phc(previous) or previous.get("PROOF", {}).get("needs_tp_resign"):
        raise HTTPException(status_code=409, detail="stored_credential_invalid")
    if not previous.get("id") or previous.get("id") != candidate.get("id"):
        raise HTTPException(status_code=400, detail="identity_id_mismatch")
    if str((previous.get("TPA") or {}).get("TPid")) != str(TP_DL_PK) or str((previous.get("APA") or {}).get("APid")) != str(AP_PK):
        raise HTTPException(status_code=409, detail="issuer_key_changed")
    if candidate.get("SCID") != previous.get("SCID"):
        raise HTTPException(status_code=400, detail="identity_scid_mismatch")
    if candidate.get("DID") != previous.get("DID"):
        raise HTTPException(status_code=400, detail="identity_did_mismatch")
    apm = pa.get("APM") or {}
    apa = pa.get("APA") or {}
    if apm != ((candidate.get("ASO") or {}).get("APM") or {}) or apa != (candidate.get("APA") or {}):
        raise HTTPException(status_code=400, detail="pa_mismatch")
    if str(apa.get("APid")) != str(AP_PK):
        raise HTTPException(status_code=400, detail="ap_key_mismatch")
    try:
        signature = {key: int(str((apa.get("APproof") or {})[key])) for key in ("r", "e", "s")}
        proof_valid = schnorr_verify(AP_PK, canonical_json({"APM": apm, "APid": str(AP_PK)}).encode(), signature)
        cmi = int(str(apm["CMI"]))
        rf = int(str((previous.get("SCID") or {})["RF"]))
        r_bind = int(str(payload.r_bind2))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="invalid_ap_update")
    if not proof_valid:
        raise HTTPException(status_code=400, detail="invalid_ap_signature")
    af = str(compute_af_formal(hid, AP_PK, TP_DL_PK, cmi, rf, r_bind))
    if str(((candidate.get("ASO") or {}).get("TPM") or {}).get("AF")) != af:
        raise HTTPException(status_code=400, detail="af_mismatch")
    tpm = dict((previous.get("ASO") or {}).get("TPM") or {})
    tpm.update({"AF": af, "Time": datetime.utcnow().isoformat() + "Z"})
    tpid = str(TP_DL_PK)
    tp_signature = schnorr_sign(TP_DL_SK, canonical_json({"TPM": tpm, "TPid": tpid}).encode())
    tpa = {"TPid": tpid, "TPproof": {key: str(tp_signature[key]) for key in ("r", "e", "s")}}
    phc = build_phc({"TPM": tpm, "APM": apm}, tpa, apa, TP_DL_SK, TP_DL_PK, AP_PK)
    for key in ("id", "issued", "SCID", "DID", "CID", "CID_enc", "CRF"):
        if key in previous:
            phc[key] = previous[key]
    phc["updated"] = datetime.utcnow().isoformat() + "Z"
    if not verify_phc(phc):
        raise HTTPException(status_code=500, detail="updated_credential_verification_failed")
    record["phc"] = phc
    _tpdb_put(hid, record)
    return {"success": True, "phc": phc}


@router.post("/tp/issue_phc_secure")
def issue_phc_secure(payload: SecureInbound) -> Dict[str, Any]:
    return _create_pending_phc_application(payload)
def _issue_phc_from_application(app_obj: Dict[str, Any]) -> Dict[str, Any]:
    start_time = time.perf_counter()

    pt = app_obj.get("pt") or {}
    idv = pt.get("ID")
    pii = pt.get("PII") or {}
    bi = pt.get("BI") or {}
    rb = int(str(pt.get("r_bind") or 0))
    pk_ap = int(str(pt.get("pk_ap") or AP_PK))

    af_recv = int(str(pt.get("AF") or 0))
    af_calc = compute_af(str(idv), pk_ap, TP_DL_PK, rb)
    if af_calc != af_recv:
        af_recv = af_calc

    rf = paillier_encrypt(
        TP_PAILLIER.public,
        int(hashlib.sha256(str(idv).encode()).hexdigest(), 16)
    )
    crf = crf_encrypt(TP_DL_PK, rf, rb)

    scid = {"AF": str(af_recv), "RF": str(rf)}
    did = f"did:wba:{hashlib.sha256(json.dumps(scid, separators=(',', ':')).encode()).hexdigest()}:example"

    tpm = {
        "Time": datetime.utcnow().isoformat() + "Z",
        "CDID": did,
        "AF": str(af_recv),
        "ECID": "g",
    }
    apm = {
        "Time": datetime.utcnow().isoformat() + "Z",
        "CMI": "0",
    }

    tpid = str(TP_DL_PK)
    apid = str(AP_PK)

    tpproof_sig = schnorr_sign(
        TP_DL_SK,
        canonical_json({"TPM": tpm, "TPid": tpid}).encode()
    )
    approof_sig = schnorr_sign(
        AP_SK,
        canonical_json({"APM": apm, "APid": apid}).encode()
    )

    tpa = {
        "TPid": tpid,
        "TPproof": {
            "r": str(tpproof_sig["r"]),
            "e": str(tpproof_sig["e"]),
            "s": str(tpproof_sig["s"]),
        },
    }
    apa = {
        "APid": apid,
        "APproof": {
            "r": str(approof_sig["r"]),
            "e": str(approof_sig["e"]),
            "s": str(approof_sig["s"]),
        },
    }

    phc = build_phc(
        aso={"TPM": tpm, "APM": apm},
        tpa=tpa,
        apa=apa,
        tp_sk=TP_DL_SK,
        tp_pk=TP_DL_PK,
        ap_pk=AP_PK,
    )

    phc["SCID"] = scid
    phc["DID"] = did

    s1 = kdf_s1(TP_PAILLIER.private["lambda"], TP_DL_SK, rf)
    secinfo_obj = {
        "BI": bi,
        "PII": pii,
        "DID": did,
        "r_bind": rb,
    }

    secinfo = sym_encrypt(s1, json.dumps(secinfo_obj, separators=(",", ":")).encode())
    cid = ipfs_put(secinfo)
    phc["CID"] = cid

    try:
        phc["CID_enc"] = sym_encrypt(s1, cid.encode())
    except Exception:
        phc["CID_enc"] = None

    try:
        phc["CRF"] = {"c1": str(crf.get("c1")), "c2": str(crf.get("c2"))}
    except Exception:
        phc["CRF"] = crf

    hid = hashlib.sha256(str(idv).encode()).hexdigest()
    _tpdb_put(hid, {
        "cid": cid,
        "cid_enc": phc.get("CID_enc"),
        "rf": str(rf),
        "r_bind": str(rb),
        "phc": phc,
        "request_id": app_obj.get("request_id"),
    })

    return {
        "success": True,
        "phc": phc,
        "mode": "secure_phc_jsonld_manual_approved",
        "face_verified": (app_obj.get("checks") or {}).get("face_verified"),
        "face_check_ms": (app_obj.get("checks") or {}).get("face_check_ms"),
        "perf_tp_verify_user_ms": (app_obj.get("checks") or {}).get("perf_tp_verify_user_ms"),
        "perf_tp_issue_ms": (time.perf_counter() - start_time) * 1000.0,
    }
def _create_pending_phc_application(payload: SecureInbound) -> Dict[str, Any]:
    start_time = time.perf_counter()
    try:
        decrypted = elgamal_decrypt_bytes(TP_DL_SK, payload.cr)
        pt = json.loads(decrypted.decode())
    except Exception:
        raise HTTPException(status_code=400, detail="decrypt_failed")

    try:
        rb = int(pt.get("r_bind"))
        sig_ok = bool(schnorr_verify(payload.user_pub, str(rb).encode(), payload.sig))
    except Exception:
        rb = 0
        sig_ok = False

    idv = pt.get("ID")
    bi = pt.get("BI") or {}
    pii = pt.get("PII") or {}

    try:
        pk_ap = int(pt.get("pk_ap"))
        af_recv = int(pt.get("AF"))
        af_calc = compute_af(str(idv), pk_ap, TP_DL_PK, rb)
        af_valid = (af_calc == af_recv)
    except Exception:
        pk_ap = 0
        af_recv = 0
        af_calc = 0
        af_valid = False

    user_id = str(((pii or {}).get("id_number") or idv or "")).strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="missing_user_id")

    db_available = True
    face_record_found = False
    face_verified_flag = False
    pic_db = None

    try:
        pic_db = _mysql_get_pic_string_by_user_id(user_id)
    except HTTPException as exc:
        det = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        if det.get("error") in {"db_driver_missing", "db_check_failed"}:
            db_available = False
        else:
            raise

    t_face0 = time.perf_counter()
    pic_str_in = str((bi or {}).get("pic_string") or "")

    if db_available:
        face_record_found = bool(pic_db)
        if pic_db and pic_str_in and pic_str_in == pic_db:
            face_verified_flag = True
        elif pic_db and not pic_str_in:
            face_verified_flag = False
        elif pic_db and pic_str_in != pic_db:
            face_verified_flag = False
        elif not pic_db and os.getenv("ALLOW_TEST_USERS") == "1":
            face_verified_flag = True
            pic_db = "mock_pic_string"
            bi["pic_string"] = pic_db
        else:
            face_verified_flag = False
    else:
        face_verified_flag = False
        bi["pic_string"] = pic_str_in

    face_check_ms = (time.perf_counter() - t_face0) * 1000.0
    verify_user_ms = (time.perf_counter() - start_time) * 1000.0

    request_id = "req_" + secrets.token_hex(12)
    now = datetime.utcnow().isoformat() + "Z"

    app_obj = {
        "request_id": request_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "user_pub": str(payload.user_pub),
        "sig": {
            "r": str((payload.sig or {}).get("r")),
            "e": str((payload.sig or {}).get("e")),
            "s": str((payload.sig or {}).get("s")),
        },
        "pt": {
            "AF": str(af_recv),
            "AF_calc": str(af_calc),
            "ID": str(idv),
            "PII": pii,
            "BI": bi,
            "pk_ap": str(pk_ap),
            "r_bind": str(rb),
            "timestamp": pt.get("timestamp"),
        },
        "checks": {
            "signature_valid": sig_ok,
            "af_valid": af_valid,
            "db_available": db_available,
            "face_record_found": face_record_found,
            "face_verified": face_verified_flag,
            "face_check_ms": face_check_ms,
            "perf_tp_verify_user_ms": verify_user_ms,
        },
        "review": {
            "operator": None,
            "decision": None,
            "reason": None,
            "comment": None,
            "reviewed_at": None,
        },
        "result": {
            "phc": None,
            "error": None,
        },
    }

    _tpapp_put(request_id, app_obj)

    return {
        "success": True,
        "mode": "manual_review",
        "status": "pending",
        "request_id": request_id,
        "message": "waiting_for_tp_approval",
        "checks": app_obj["checks"],
    }

@router.post("/tp/verify_phc")
def verify_phc_endpoint(payload: PHCModel) -> Dict[str, Any]:
    phc = payload.phc
    ok = verify_phc(phc, tp_secret=TP_PAILLIER.private["lambda"])  # enable deterministic checks
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid PHC structure or missing proof")
    return {"success": True, "verified": True}


@router.post("/tp/trace")
def trace_identity(req: TraceRequest) -> Dict[str, Any]:
    """Trace identity by decrypting RF (stub using paillier_decrypt).

    In production TP would use its Paillier private key to decrypt RF and
    fetch IPFS content for evidence. Here we just return the decrypted payload.
    """
    decrypted = paillier_decrypt(TP_PAILLIER.private, req.rf_ciphertext)
    return {"success": True, "decrypted": decrypted}


@router.post("/tp/reveal")
def reveal_identity(req: RevealByDidRequest) -> Dict[str, Any]:
    """Reveal user identity from PHC using DID.

    Steps:
    - Find PHC by DID in local storage
    - Derive s1 = KDF(lambda, sk_tp, RF)
    - Decrypt CID_enc with s1 (fallback to CID)
    - Fetch encrypted secinfo from IPFS and decrypt with s1
    - Paillier-decrypt RF to get id_hash (evidence)
    """
    db_rec = _find_phc_by_did(req.did)
    if not db_rec:
        raise HTTPException(status_code=404, detail="did_not_found")

    phc = db_rec.get("phc") or {}
    try:
        scid = phc.get("SCID") or {}
        rf_str = str(scid.get("RF"))
        rf_int = int(rf_str)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_scid_rf")
    # derive s1
    s1 = kdf_s1(TP_PAILLIER.private["lambda"], TP_DL_SK, rf_int)
    # resolve CID
    cid = phc.get("CID")
    cid_enc = phc.get("CID_enc")
    if cid_enc:
        try:
            cid = sym_decrypt(s1, str(cid_enc)).decode()
        except Exception:
            pass
    if not cid:
        raise HTTPException(status_code=400, detail="missing_cid")
    # fetch and decrypt secinfo
    enc = ipfs_get(str(cid))
    if not enc:
        raise HTTPException(status_code=404, detail="secinfo_not_found")
    try:
        pt = sym_decrypt(s1, enc).decode()
        sec = json.loads(pt)
    except Exception:
        raise HTTPException(status_code=400, detail="secinfo_decrypt_failed")
    # decrypt RF for evidence of ID hash
    try:
        id_hash_int = paillier_decrypt(TP_PAILLIER.private, rf_int)
    except Exception:
        id_hash_int = None
    return {
        "success": True,
        "did": sec.get("DID"),
        "id": sec.get("PII", {}).get("id_number"),
        "pii": sec.get("PII"),
        "bi": sec.get("BI"),
        "cid": cid,
        "evidence": {"id_hash": str(id_hash_int) if id_hash_int is not None else None},
    }
class RevealRequest(BaseModel):
    phc: Dict[str, Any]
class RecoverPHCInbound(BaseModel):
    rec: Dict[str, Any]
    user_pub: int
class ReviewDecision(BaseModel):
    operator: str = "tp_admin"
    reason: Optional[str] = None
    comment: Optional[str] = None

def _tpdb_root() -> str:
    import os
    root = os.path.join(os.getcwd(), "local_store", "tp_db")
    os.makedirs(root, exist_ok=True)
    return root

def _tpapp_path(request_id: str) -> str:
   safe_id = str(request_id).replace("/", "_").replace("\\", "_")
   return os.path.join(_tpapp_root(), f"{safe_id}.json")

def _tpdb_put(hid: str, obj: Dict[str, Any]) -> None:
    import os
    import tempfile
    root = _tpdb_root()
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

def _tpdb_get(hid: str) -> Dict[str, Any] | None:
    import os
    root = _tpdb_root()
    path = os.path.join(root, f"{hid}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
def _tpapp_root() -> str:
    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "tp_applications",
    )
    os.makedirs(root, exist_ok=True)
    return root

def _tpapp_path(request_id: str) -> str:
    safe_id = str(request_id).replace("/", "_").replace("\\", "_")
    return os.path.join(_tpapp_root(), f"{safe_id}.json")

def _tpapp_put(request_id: str, app_obj: dict) -> None:
    path = _tpapp_path(request_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(app_obj, f, ensure_ascii=False, indent=2)

def _tpapp_get(request_id: str):
    path = _tpapp_path(request_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _tpapp_delete(request_id: str) -> None:
    path = _tpapp_path(request_id)
    if os.path.exists(path):
        os.remove(path)

def _tpapp_list(status: Optional[str] = None) -> list[Dict[str, Any]]:
    items = []
    root = _tpapp_root()
    for fname in os.listdir(root):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(root, fname), "r", encoding="utf-8") as f:
                obj = json.load(f)
            if status and obj.get("status") != status:
                continue
            items.append(obj)
        except Exception:
            pass
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items

def _find_phc_by_did(did: str) -> Dict[str, Any] | None:
    import os
    root = _tpdb_root()
    for fname in os.listdir(root):
        if not fname.endswith('.json'):
            continue
        hid = fname.split('.')[0]
        data = _tpdb_get(hid)
        if data and data.get('phc', {}).get('DID') == did:
            return data
    return None

def _recovery_identity_matches(sec: Dict[str, Any], pii: Dict[str, Any], bi: Dict[str, Any]) -> bool:
    recorded_pii = sec.get("PII") or {}
    recorded_bi = sec.get("BI") or {}

    def normalize(value: Any) -> str:
        return str(value or "").strip()

    for field in ("name", "id_number"):
        submitted = normalize(pii.get(field))
        if not submitted or submitted != normalize(recorded_pii.get(field)):
            return False

    for field in ("id_card_number", "email"):
        submitted = normalize(pii.get(field))
        if submitted and submitted != normalize(recorded_pii.get(field)):
            return False

    for field in ("passport_number",):
        submitted = normalize(bi.get(field))
        if submitted and submitted != normalize(recorded_bi.get(field)):
            return False

    submitted_photo = normalize(bi.get("pic_string"))
    return bool(submitted_photo) and submitted_photo == normalize(recorded_bi.get("pic_string"))

@router.post("/tp/recover_phc")
def recover_phc(payload: RecoverPHCInbound) -> Dict[str, Any]:
    try:
        decrypted = elgamal_decrypt_bytes(TP_DL_SK, payload.rec)
        pt_raw = decrypted.decode()
        try:
            pt = json.loads(pt_raw)
        except Exception:
            pt = {"raw": pt_raw}
    except Exception:
        raise HTTPException(status_code=400, detail="decrypt_failed")
    try:
        if isinstance(pt, str):
            pt = json.loads(pt)
        if isinstance(pt.get("PII"), str):
            pt["PII"] = json.loads(pt.get("PII"))
        if isinstance(pt.get("BI"), str):
            pt["BI"] = json.loads(pt.get("BI"))
    except Exception:
        pass
    idv = str((pt.get("PII") or {}).get("id_number") or pt.get("ID") or "")
    bi = pt.get("BI") or {}
    pii = pt.get("PII") or {}
    did = str(pt.get("DID") or "")
    if not idv:
        raise HTTPException(status_code=400, detail="missing_id")
    hid = hashlib.sha256(idv.encode()).hexdigest()
    rec = _tpdb_get(hid)
    if not rec and did:
        rec = _find_phc_by_did(did)
    if not rec:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        rf_int = int(str(rec.get("rf")))
    except Exception:
        rf_int = 0
    s1 = kdf_s1(TP_PAILLIER.private["lambda"], TP_DL_SK, rf_int)
    cid = rec.get("cid")
    cid_enc = rec.get("cid_enc")
    if cid_enc and not cid:
        try:
            cid = sym_decrypt(s1, str(cid_enc)).decode()
        except Exception:
            cid = None
    if not cid:
        raise HTTPException(status_code=404, detail="missing_cid")
    enc = ipfs_get(str(cid))
    if not enc:
        raise HTTPException(status_code=404, detail="secinfo_not_found")
    try:
        pt2 = sym_decrypt(s1, enc).decode()
        sec = json.loads(pt2)
    except Exception:
        raise HTTPException(status_code=400, detail="secinfo_decrypt_failed")
    ok = _recovery_identity_matches(sec, pii, bi)
    if not ok:
        raise HTTPException(status_code=403, detail="verify_failed")
    from crypto_lib import elgamal_encrypt_bytes as tp_elg_enc
    raw = json.dumps({"PHC": rec.get("phc")}, separators=(",", ":")).encode()
    phc_enc = tp_elg_enc(int(payload.user_pub), raw)
    return {"success": True, "phc_enc": phc_enc}
@router.get("/tp/applications")
def list_phc_applications(status: Optional[str] = None) -> Dict[str, Any]:
    items = _tpapp_list(status=status)

    def brief(obj: Dict[str, Any]) -> Dict[str, Any]:
        pt = obj.get("pt") or {}
        pii = pt.get("PII") or {}
        checks = obj.get("checks") or {}
        id_number = str(pii.get("id_number") or pt.get("ID") or "")
        masked = id_number[:3] + "***" + id_number[-2:] if len(id_number) > 5 else id_number
        card = str(pii.get("id_card_number") or "")
        card_masked = ("****" + card[-4:]) if card else ""
        return {
            "request_id": obj.get("request_id"),
            "status": obj.get("status"),
            "created_at": obj.get("created_at"),
            "updated_at": obj.get("updated_at"),
            "name": pii.get("name"),
            "id_number_masked": masked,
            "id_card_number_masked": card_masked,
            "email": pii.get("email") or "",
            "signature_valid": checks.get("signature_valid"),
            "af_valid": checks.get("af_valid"),
            "face_verified": checks.get("face_verified"),
            "db_available": checks.get("db_available"),
        }

    return {"success": True, "items": [brief(x) for x in items], "count": len(items)}
@router.get("/tp/applications/{request_id}")
def get_phc_application(request_id: str) -> Dict[str, Any]:
    obj = _tpapp_get(request_id)
    if not obj:
        raise HTTPException(status_code=404, detail="application_not_found")
    return {"success": True, "application": obj}
@router.post("/tp/applications/{request_id}/approve")
def approve_phc_application(request_id: str, decision: ReviewDecision) -> Dict[str, Any]:
    obj = _tpapp_get(request_id)
    if not obj:
        raise HTTPException(status_code=404, detail="application_not_found")

    if obj.get("status") == "issued":
        return {
            "success": True,
            "status": "issued",
            "phc": (obj.get("result") or {}).get("phc"),
            "message": "already_issued",
        }

    if obj.get("status") == "rejected":
        raise HTTPException(status_code=400, detail="application_rejected")

    issued = _issue_phc_from_application(obj)
    now = datetime.utcnow().isoformat() + "Z"

    obj["status"] = "issued"
    obj["updated_at"] = now
    obj["review"] = {
        "operator": decision.operator,
        "decision": "approved",
        "reason": decision.reason,
        "comment": decision.comment,
        "reviewed_at": now,
    }
    obj["result"] = {
        "phc": issued.get("phc"),
        "error": None,
    }

    _tpapp_put(request_id, obj)

    return {
        "success": True,
        "status": "issued",
        "phc": issued.get("phc"),
        "issue_result": issued,
    }
@router.post("/tp/applications/{request_id}/reject")
def reject_phc_application(request_id: str, decision: ReviewDecision) -> Dict[str, Any]:
    obj = _tpapp_get(request_id)
    if not obj:
        raise HTTPException(status_code=404, detail="application_not_found")

    if obj.get("status") == "issued":
        raise HTTPException(status_code=400, detail="application_already_issued")

    now = datetime.utcnow().isoformat() + "Z"

    obj["status"] = "rejected"
    obj["updated_at"] = now
    obj["review"] = {
        "operator": decision.operator,
        "decision": "rejected",
        "reason": decision.reason or "manual_reject",
        "comment": decision.comment,
        "reviewed_at": now,
    }
    obj["result"] = {
        "phc": None,
        "error": decision.reason or "manual_reject",
    }

    _tpapp_put(request_id, obj)

    return {"success": True, "status": "rejected", "request_id": request_id}
@router.get("/tp/applications/{request_id}/status")
def get_phc_application_status(request_id: str) -> Dict[str, Any]:
    obj = _tpapp_get(request_id)
    if not obj:
        raise HTTPException(status_code=404, detail="application_not_found")

    status = obj.get("status")
    result = obj.get("result") or {}
    review = obj.get("review") or {}

    out = {
        "success": status != "rejected",
        "request_id": request_id,
        "status": status,
        "mode": "manual_review",
        "reason": review.get("reason") or result.get("error"),
        "comment": review.get("comment"),
    }

    if status == "issued":
        out["phc"] = result.get("phc")

    return out
