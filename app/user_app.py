from fastapi import FastAPI, Response, Body, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict,List
from app.windows_dependency_helper import (
    detect_windows_dependencies,
    launch_dependency_installer,
)
from app.skills_router import router as skills_router
from app.hooks_router import router as hooks_router
from user.models import UserInfo, PIIModel, BIModel
from user.apply_agent import request_phc_remote, request_pa_remote, request_cmm_init, request_cmm_submit
from user.apply_agent import request_phc_secure
from user.apply_agent import request_pa_recover, normalize_service_base_url
from crypto_lib import elgamal_decrypt_bytes
from user.crypto import canonical_json, sha256_hex
from crypto_lib import compute_af_formal, hcgen_cmi, ch_compute, cch_compute
from trust_provider.issue_phc import TP_DL_PK
from trust_provider.issue_phc import reveal_identity, RevealByDidRequest
from agent_provider.ap import AP_PK
from pic.pic_upload import router as pic_router
import httpx
import os
from user.apply_agent import request_phc_application_status
import time as _time
from user.crypto import compute_r_bind, canonical_json, sha256_hex, compute_cmi, dl_generate_user_keypair
from user.crypto import elgamal_encrypt_bytes
from trust_provider.issue_phc import issue_phc, ASOCompleteModel
from agent_provider.openclaw.openclaw_package import (
    detect_agent_type,
    build_openclaw_package,
    build_openclaw_agent_files,
)
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import os
from pathlib import Path  # <-- 添加这一行
import uuid  # <-- 也添加这一行，因为后面用到了 uuid
import json

app = FastAPI(title="User Service")
app.include_router(pic_router, prefix="/v1")
app.include_router(skills_router)
app.include_router(hooks_router)
app.mount("/user/static", StaticFiles(directory=os.path.join(os.getcwd(), "app", "web_user")), name="user_static")

# ==================== 鉴权：登录页与认证接口 ====================
# User App 是跑在用户本机的控制台服务，加登录有两层意义：
#   1) 产品形态完整 —— 一个讲「身份可信」的系统，自己的入口不该是裸的
#   2) 访问控制 —— 防止同机他人直接操作本机钱包与凭证
#
# 注意这里不能用「身份证号 + 密码」这类设计：用户此刻还没有身份
# （正在申请 PHC），要求用凭证登录会形成逻辑闭环矛盾。
# 所以 User 端走独立的本地账号体系，与 TP/AP 的管理员账号互不相通。
from app import auth_common as auth
from app import web_assets

USER_WEB_DIR = os.path.join(os.getcwd(), "app", "web_user")

@app.get("/user/login", include_in_schema=False)
def user_login_page() -> Response:
    return Response(status_code=303, headers={"Location": "/user/static/experience/login.html", "Cache-Control": "no-store"})

auth.register_auth_routes(
    app,
    role="user",
    cookie_name=auth.COOKIE_USER,
    api_prefix="/user/api",
)


class RequestPHCStatus(BaseModel):
    base_url: str
    request_id: str

def _normalize_hid(hid: str) -> str:
    """
    统一 HID 格式�?
    - 如果传入本身就是 64 �?sha256 hex，则直接使用
    - 否则对原始字符串�?sha256
    """
    try:
        hid_str = str(hid or "")
        is_hex = (
            len(hid_str) == 64
            and all(c in "0123456789abcdefABCDEF" for c in hid_str)
        )
        return hid_str if is_hex else sha256_hex(hid_str)
    except Exception:
        return sha256_hex(str(hid))

def _build_octopus_snapshot(
    root: str,
    cmc: list,
    hid_use: str,
) -> tuple[str, int | None, list[str]]:
    """
    �?Octopus 构建逻辑�?
    1. 复制 agent_provider/octopus �?local_store/agents/<phc_id>/octopus_build
    2. 根据用户选择的功能裁�?agent 文件
    3. �?octopus_build 目录计算 CMI
    """
    import shutil
    from crypto_lib import dir_code_cmi_hid

    features = [m.get("label") for m in (cmc[0] if len(cmc) > 0 else [])]

    mapping = {
        "text-processing": "text_processor",
        "news-search": "news",
        "web-browsing": "web_browsing",
    }

    allowed_agents = [mapping.get(x, "") for x in features]
    allowed_agents = [x for x in allowed_agents if x]

    personal_dir = os.path.join(root, "octopus_build")
    src_dir = os.path.join(os.getcwd(), "agent_provider", "octopus")

    shutil.copytree(
        src_dir,
        personal_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".venv",
            ".web-venv",
            "venv",
            "__pycache__",
            ".git",
            ".idea",
            ".vscode",
            ".env",
            "*.log",
            "*.egg-info",
        ),
    )

    prune_map = {
        "text_processor": os.path.join(
            personal_dir,
            "octopus",
            "agents",
            "text_processor_agent.py",
        ),
        "news": os.path.join(
            personal_dir,
            "octopus",
            "agents",
            "news_agent.py",
        ),
        "web_browsing": os.path.join(
            personal_dir,
            "octopus",
            "agents",
            "web_browsing_agent.py",
        ),
    }

    keep = set(allowed_agents)

    for name, fpath in prune_map.items():
        if name not in keep and os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass

    cmi_code_int = dir_code_cmi_hid(personal_dir, hid_use)

    return personal_dir, cmi_code_int, allowed_agents

def _build_openclaw_snapshot(
    root: str,
    phc: Dict[str, Any],
    cmc: list,
    hid_use: str,
    hooks_config: dict | None = None,
    skills_config: list | None = None,
    llm_config: dict | None = None,
) -> tuple[str, int | None]:
    """
    OpenClaw 构建逻辑:
    1. 生成 openclaw_package
    2. 计算代码目录 CMI
    3. 再把 CMC + 模型公开配置绑定进最终 CMI
    """
    from crypto_lib import dir_code_cmi_hid
    from agent_provider.openclaw.openclaw_package import (
        extract_llm_public_config,
        compute_openclaw_bound_cmi,
    )

    llm_public_config = extract_llm_public_config(cmc or [])

    # 优先使用前端提交的配置，如果前端没有提交则使用 cmc 中的配置
    merged_llm_config = dict(llm_config or {})
    if not merged_llm_config.get("provider"):
        merged_llm_config["provider"] = llm_public_config.get("provider")
    if not merged_llm_config.get("model"):
        merged_llm_config["model"] = llm_public_config.get("model")
    if not merged_llm_config.get("base_url"):
        merged_llm_config["base_url"] = llm_public_config.get("base_url")

    package_info = build_openclaw_package(
        root=root,
        phc=phc,
        cmc=cmc,
        hid=hid_use,
        pa=None,
        package_cmi=None,
        hooks_config=hooks_config,
        skills_config=skills_config,
        llm_config=merged_llm_config,
    )

    package_dir = package_info.get("package_dir")

    code_cmi_int = dir_code_cmi_hid(package_dir, hid_use)

    final_cmi_int = compute_openclaw_bound_cmi(
        hid=hid_use,
        code_cmi=code_cmi_int,
        cmc=cmc or [],
        llm_public_config=llm_public_config,
    )

    return package_dir, final_cmi_int
def _agent_package_dir(phc: Dict[str, Any], cmc: list) -> str:
    """
    根据 agent_type 返回需要计�?CMI 的目录�?
    """
    phc_id = (phc.get("id") or "phc").replace(":", "_")
    root = os.path.join(os.getcwd(), "local_store", "agents", phc_id)

    agent_type = detect_agent_type(cmc)

    if agent_type == "openclaw":
        return os.path.join(root, "openclaw_package")

    return os.path.join(root, "octopus_build")

class RequestPHC(BaseModel):
    base_url: str
    user: UserInfo

class RequestPA(BaseModel):
    base_url: str
    phc: Dict[str, Any]
    user: UserInfo

class RequestCMMInit(BaseModel):
    base_url: str
    phc: Dict[str, Any]
    user: UserInfo
    agent_type: str = "octopus"

class RequestCMMSubmit(BaseModel):
    base_url: str
    cmc: list
    hid: str
    phc: Dict[str, Any]
    user_sk: str
    user_pk: str
    agent_type: str = "octopus"
    hooks_config: dict | None = None
    skills_config: list | None = None
    llm_config: dict | None = None

class RequestCreateAgent(BaseModel):
    phc: Dict[str, Any]
    pa: Dict[str, Any]
    cmc: list
    agent_type: str | None = None
    hooks_config: dict | None = None
    skills_config: list | None = None
    llm_config: dict | None = None

class RequestPARecover(BaseModel):
    base_url: str
    tp_base_url: str = "http://127.0.0.1:8111"
    phc: Dict[str, Any]
    user: UserInfo
    agent_type: str = "octopus"

class RequestUpdateInit(BaseModel):
    base_url: str
    phc: Dict[str, Any]
    user: UserInfo
    agent_type: str = "octopus"

class RequestUpdateSubmit(BaseModel):
    base_url: str
    tp_base_url: str = "http://127.0.0.1:8111"
    cmc: list
    hid: str
    phc: Dict[str, Any]
    user_sk: str
    user_pk: str
    agent_type: str = "octopus"

class DependencyInstallRequest(BaseModel):
    target: str = "all"



class RecoverBothRequest(BaseModel):
    tp_base: str
    ap_base: str
    user: UserInfo
    agent_type: str = "octopus"
    did: str | None = None
class BenchRequest(BaseModel):
    loops: int = 100
    size: int = 1024
    exp_bits: int = 16
    exp_fixed: int | None = None
    agent_type: str = "octopus"

@app.post('/user/request_phc')
def user_request_phc(req: RequestPHC) -> Dict[str, Any]:
    from crypto_lib import schnorr_verify
    try:
        res = request_phc_secure(req.base_url, req.user)
        out = res.model_dump()
        if not out.get("phc"):
            out["perf_user_verify_phc_ms"] = 0.0
            return out

        t0 = _time.perf_counter()
        try:
             phc = res.phc
             tpa = phc.get('TPA') or {}
             tpm = (phc.get('ASO') or {}).get('TPM') or {}
             sig = tpa.get('TPproof') or {}
             tpid = tpa.get('TPid')
             _ = bool(schnorr_verify(int(str(tpid)), canonical_json({'TPM': tpm, 'TPid': tpid}).encode(), {'r': int(str(sig.get('r') or 0)), 'e': int(str(sig.get('e') or 0)), 's': int(str(sig.get('s') or 0))}))
        except Exception:
             pass
        t1 = _time.perf_counter()
        out["perf_user_verify_phc_ms"] = (t1 - t0) * 1000.0
        return out
    except httpx.HTTPError as e:
        from fastapi import HTTPException
        status = getattr(getattr(e, "response", None), "status_code", 502)
        detail = None
        if getattr(e, "response", None) is not None:
            try:
                detail = e.response.json().get("detail")
            except Exception:
                pass
        if status == 403 and str(detail) in {"face_verification_failed", "face_record_not_found"}:
            raise HTTPException(status_code=403, detail=str(detail) or "face_verification_failed")
        if (os.getenv("ALLOW_LEGACY_ISSUE") or "0") == "1":
            r_bind = compute_r_bind()
            af = sha256_hex(canonical_json({"pii": req.user.pii.model_dump(), "bi": req.user.bi.model_dump(), "r_bind": r_bind, "pk_ap": "ap.pk.placeholder"}))
            cmi = compute_cmi(req.user.pii.model_dump())
            payload = ASOCompleteModel(af=af, cmi=cmi, cdid=req.user.cdid, ecid=req.user.ecid)
            data = issue_phc(payload)
            return data
        raise HTTPException(status_code=status, detail=detail or "phc_secure_failed")

@app.post('/bench/crypto')
def bench_crypto(req: BenchRequest) -> Dict[str, Any]:
    import time, os, secrets
    from crypto_lib import (
        elgamal_encrypt_bytes as elg_enc,
        elgamal_decrypt_bytes as elg_dec,
        schnorr_sign,
        schnorr_verify,
        sym_encrypt,
        sym_decrypt,
        sha256_hex,
        canonical_json,
        inv_mod,
        generate_paillier_keypair,
        paillier_encrypt,
        paillier_decrypt,
        ch_compute,
        cch_compute,
        DL_P,
        dl_generate_keypair,
    )
    from crypto_lib.keys import TP_DL_SK, TP_DL_PK, AP_PK, TP_DL_PK as TP_PK_INT
    loops = int(req.loops)
    msg = os.urandom(int(req.size))
    def avg(fn):
        s = _time.perf_counter()
        for _ in range(loops):
            fn()
        e = _time.perf_counter()
        return (e - s) * 1000.0 / loops
    te_enc = avg(lambda: elg_enc(int(TP_DL_PK), msg))
    ct_once = elg_enc(int(TP_DL_PK), msg)
    te_dec = avg(lambda: elg_dec(int(TP_DL_SK), ct_once))
    key_sym = os.urandom(32)
    tae = avg(lambda: sym_encrypt(key_sym, msg))
    ct_sym = sym_encrypt(key_sym, msg)
    tad = avg(lambda: sym_decrypt(key_sym, ct_sym))
    th = avg(lambda: sha256_hex(msg.hex()))
    prev0 = sha256_hex("seed")
    data0 = canonical_json({"label": "x", "idx": 0})
    chain_input0 = prev0 + data0
    th_step = avg(lambda: sha256_hex(chain_input0))
    def hash_chain_run():
        prev = sha256_hex("seed")
        for i in range(loops):
            data = canonical_json({"label": "x", "idx": i})
            prev = sha256_hex(prev + data)
        return prev
    s1 = _time.perf_counter()
    _ = hash_chain_run()
    thc = (_time.perf_counter() - s1) * 1000.0
    thc_avg = thc / max(loops, 1)
    sk_u, pk_u = dl_generate_keypair()
    tsig = avg(lambda: schnorr_sign(int(sk_u), msg))
    sig_once = schnorr_sign(int(sk_u), msg)
    tver = avg(lambda: schnorr_verify(int(pk_u), msg, sig_once))
    apm_obj = {"CMI": "1", "Time": "1"}
    apa_obj = {"APid": str(AP_PK), "APproof": {"r": "0", "e": "0", "s": "0"}}
    r_ap = secrets.randbelow(DL_P - 1) + 1
    tch = avg(lambda: ch_compute(int(AP_PK), apm_obj, apa_obj, int(r_ap)))
    cmi_int = 1
    crf_int = 1
    r_int = secrets.randbelow(DL_P - 1) + 1
    tcch = avg(lambda: cch_compute(int(AP_PK), int(TP_PK_INT), int(cmi_int), int(crf_int), int(r_int)))
    kp = generate_paillier_keypair(256)
    m_int = int.from_bytes(os.urandom(32), "big")
    tpe = avg(lambda: paillier_encrypt(kp.public, m_int))
    c_paillier = paillier_encrypt(kp.public, m_int)
    tpd = avg(lambda: paillier_decrypt(kp.private, c_paillier))
    base = secrets.randbelow(DL_P - 2) + 2
    exp_bits = max(1, int(getattr(req, "exp_bits", 16)))
    exp_rand = secrets.randbelow(1 << exp_bits) + 1
    e_fixed = int(getattr(req, "exp_fixed", 0) or 0) or ((1 << exp_bits) - 1)
    tmu = avg(lambda: pow(base, exp_rand, DL_P))
    tmu_fixed = avg(lambda: pow(base, e_fixed, DL_P))
    texp = avg(lambda: pow(base, exp_rand))
    texp_fixed = avg(lambda: pow(base, e_fixed))
    tinv = avg(lambda: inv_mod(secrets.randbelow(DL_P - 1) + 1, DL_P))
    return {
        "loops": loops,
        "size": int(req.size),
        "results": {
            "Te_enc_ms": te_enc,
            "Te_dec_ms": te_dec,
            "Tae_ms": tae,
            "Tad_ms": tad,
            "Th_ms": th,
            "Th_step_ms": th_step,
            "Thc_ms": thc,
            "Thc_avg_ms": thc_avg,
            "Tsig_ms": tsig,
            "Tver_ms": tver,
            "Tch_ms": tch,
            "Tcch_ms": tcch,
            "Tpe_ms": tpe,
            "Tpd_ms": tpd,
            "Tmu_fixed_ms": tmu_fixed,
            "Texp_fixed_ms": texp_fixed,
            "Tinv_ms": tinv,
            "Tsg_ms": None,
            "TBLS_ms": None,
            "Tsig1_ms": None,
            "Tver1_ms": None,
        },
        "unsupported": ["shamir", "bls", "ecdsa"],
    }

@app.post('/user/recover_phc')
def user_recover_phc(req: RequestPHC) -> Dict[str, Any]:
    from user.apply_agent import request_phc_recover
    from crypto_lib import schnorr_verify, canonical_json
    try:
        out = request_phc_recover(req.base_url, req.user)
    except httpx.HTTPStatusError as exc:
        response = exc.response
        detail = "tp_identity_mismatch" if response.status_code == 403 else "tp_identity_record_not_found" if response.status_code == 404 else "tp_recovery_rejected"
        raise HTTPException(status_code=response.status_code if response.status_code < 500 else 502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="tp_unavailable") from exc
    phc = out.get('PHC') or out.get('phc') or {}
    if not phc:
        raise HTTPException(status_code=502, detail="tp_recovery_response_invalid")
    tpa = phc.get('TPA') or {}
    tpm = (phc.get('ASO') or {}).get('TPM') or {}
    sig = tpa.get('TPproof') or {}
    tpid = tpa.get('TPid')
    try:
        ok = bool(schnorr_verify(int(str(tpid)), canonical_json({'TPM': tpm, 'TPid': tpid}).encode(), {'r': int(str(sig.get('r') or 0)), 'e': int(str(sig.get('e') or 0)), 's': int(str(sig.get('s') or 0))}))
    except Exception:
        ok = False
    hid = sha256_hex(req.user.pii.id_number)
    return {'success': True, 'phc': phc, 'verified_identity': True, 'verified_tp': ok, 'identity': {'hid': hid, 'pii': req.user.pii.model_dump(exclude_none=True), 'bi': req.user.bi.model_dump(exclude_none=True)}}

@app.post('/user/recover_both')
def user_recover_both(req: RecoverBothRequest) -> Dict[str, Any]:
    from user.apply_agent import request_phc_recover
    try:
        hid = sha256_hex(req.user.pii.id_number)
        phc_obj = request_phc_recover(req.tp_base, req.user, req.did)
        phc = phc_obj.get('PHC') or phc_obj.get('phc') or {}
        if not phc:
            return {"success": False, "error": "phc_recover_failed", "detail": phc_obj, "identity": {"hid": hid, "pii": req.user.pii.model_dump(exclude_none=True), "bi": req.user.bi.model_dump(exclude_none=True)}}
        pa_obj = request_pa_recover(req.ap_base, phc, req.user)
        pa_obj = _verify_and_restore_pa(pa_obj, req.user, req.agent_type, req.tp_base)
        did = phc.get("DID") or ((phc.get("ASO") or {}).get("TPM") or {}).get("CDID")
        try:
            sec = reveal_identity(RevealByDidRequest(did=str(did)))
            pii_out = (sec.get("pii") or {})
            bi_out = (sec.get("bi") or {})
        except Exception:
            pii_out = req.user.pii.model_dump(exclude_none=True)
            bi_out = req.user.bi.model_dump(exclude_none=True)
        return {"success": True, "phc": pa_obj.get("PHC") or phc, "pa": pa_obj, "identity": {"hid": hid, "pii": pii_out, "bi": bi_out}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post('/user/request_pa')
def user_request_pa(req: RequestPA) -> Dict[str, Any]:
    try:
        return request_pa_remote(req.base_url, req.phc, req.user)
    except httpx.HTTPError:
        from agent_provider.ap import request_pa, APInbound, AP_PK
        from user.crypto import dl_generate_user_keypair, elgamal_encrypt_bytes
        hid = sha256_hex(req.user.pii.id_number)
        tpac = req.phc.get("TPA") if isinstance(req.phc, dict) else {}
        sk_a, pk_a = dl_generate_user_keypair()
        ar_plain = {"PHC": req.phc, "HID": hid, "TPAC": tpac}
        ar = elgamal_encrypt_bytes(AP_PK, ar_plain)
        out = request_pa(APInbound(ar=ar, user_pub=pk_a))
        from trust_provider.crypto import elgamal_decrypt_bytes
        import json
        raw = elgamal_decrypt_bytes(sk_a, out["par"]).decode()
    return json.loads(raw)

@app.post('/user/cmm_init')
def user_cmm_init(req: RequestCMMInit) -> Dict[str, Any]:
    agent_type = (req.agent_type or "octopus").strip().lower()

    out = request_cmm_init(
        req.base_url,
        req.phc,
        req.user,
        agent_type=agent_type,
    )

    out["agent_type"] = agent_type
    return out

@app.post('/user/cmm_submit')
def user_cmm_submit(req: RequestCMMSubmit) -> Dict[str, Any]:
    cmi_code_int = None
    package_dir = None
    agent_type = (req.agent_type or "octopus").strip().lower()

    if agent_type not in {"octopus", "openclaw"}:
        agent_type = detect_agent_type(req.cmc or [])

    # Use provided user pk/sk; if missing, fall back to a fresh ephemeral pair
    try:
        user_pk_int = int(str(req.user_pk or ""))
        user_sk_int = int(str(req.user_sk or ""))
        if user_pk_int == 0 or user_sk_int == 0:
            raise ValueError("empty keys")
    except Exception:
        user_sk_int, user_pk_int = dl_generate_user_keypair()

    # Build personalized package snapshot to compute CMI.
    try:
        phc = req.phc or {}
        phc_id = (phc.get("id") or "phc").replace(":", "_")
        root = os.path.join(os.getcwd(), "local_store", "agents", phc_id)
        os.makedirs(root, exist_ok=True)

        hid_use0 = _normalize_hid(req.hid)

        if agent_type == "openclaw":
            package_dir, cmi_code_int = _build_openclaw_snapshot(
            root=root,
            phc=phc,
            cmc=req.cmc or [],
            hid_use=hid_use0,
            hooks_config=req.hooks_config,
            skills_config=getattr(req, "skills_config", None),
            llm_config=getattr(req, "llm_config", None),
        )
        else:
            package_dir, cmi_code_int, _allowed_agents = _build_octopus_snapshot(
                root=root,
                cmc=req.cmc or [],
                hid_use=hid_use0,
            )

    except Exception as e:
        print(f"build package snapshot failed: {e}")
        cmi_code_int = None

    # Submit CMC to AP
    out = request_cmm_submit(
        req.base_url,
        req.cmc,
        req.hid,
        req.phc,
        user_pk_int,
        cmi_code=cmi_code_int,
        agent_type=agent_type,
    )

    par = out.get("par")
    if not par:
        return out

    raw = elgamal_decrypt_bytes(int(user_sk_int), par).decode()

    import json
    obj = json.loads(raw)

    obj["perf_ap_generate_pa_ms"] = out.get("perf_ap_generate_pa_ms")

    t_verify_start = _time.perf_counter()

    # Verify CMI' = code snapshot CMI against PA.APM.CMI
    try:
        hid_str = str(req.hid or "")
        is_hex = (
            len(hid_str) == 64
            and all(c in "0123456789abcdefABCDEF" for c in hid_str)
        )
        hid_use = hid_str if is_hex else sha256_hex(hid_str)
    except Exception:
        hid_use = sha256_hex(str(req.hid))

    try:
        from crypto_lib import dir_code_cmi_hid
        if agent_type == "openclaw":
            from agent_provider.openclaw.openclaw_package import (
                extract_llm_public_config,
                compute_openclaw_bound_cmi,
            )

            calc_dir = _agent_package_dir(req.phc or {}, req.cmc or [])
            code_cmi_int = dir_code_cmi_hid(calc_dir, hid_use)
            llm_public_config = extract_llm_public_config(req.cmc or [])

            calc_cmi_int = compute_openclaw_bound_cmi(
                hid=hid_use,
                code_cmi=code_cmi_int,
                cmc=req.cmc or [],
                llm_public_config=llm_public_config,
            )
        else:
            calc_dir = _agent_package_dir(req.phc or {}, req.cmc or [])
            calc_cmi_int = dir_code_cmi_hid(calc_dir, hid_use)
    except Exception:
        calc_cmi_int = hcgen_cmi(req.cmc, hid_use)

    pa_cmi = ((obj.get("PA") or {}).get("APM") or {}).get("CMI")
    verified_cmi = (str(calc_cmi_int) == str(pa_cmi))

    # Verify AF formal
    try:
        cmi_int = int(str(pa_cmi))
    except Exception:
        cmi_int = int(str(calc_cmi_int))

    try:
        rf_val = ((obj.get("PHC") or {}).get("SCID") or {}).get("RF")
        crf_int = int(str(rf_val or 0))
    except Exception:
        crf_int = 0

    try:
        rbind2_int = int(str(obj.get("r_bind2") or 0))
    except Exception:
        rbind2_int = 0

    try:
        ap_pk_int = int(str(obj.get("ap_pk")))
    except Exception:
        ap_pk_int = 0

    try:
        tp_pk_int = int(str(obj.get("tp_pk")))
    except Exception:
        tp_pk_int = 0

    af_calc_user = compute_af_formal(
        str(hid_use),
        ap_pk_int,
        tp_pk_int,
        cmi_int,
        crf_int,
        rbind2_int,
    )

    af_prev = ((obj.get("PHC") or {}).get("ASO") or {}).get("TPM", {}).get("AF")
    verified_af = (str(af_prev) == str(af_calc_user))

    # Verify CH/CCH
    try:
        r_ap_val = int(str(obj.get("r_ap") or 0))
    except Exception:
        r_ap_val = 0

    ch_calc = ch_compute(
        ap_pk_int,
        (obj.get("PA") or {}).get("APM") or {},
        (obj.get("PA") or {}).get("APA") or {},
        r_ap_val,
    )

    cch_calc = cch_compute(
        ap_pk_int,
        tp_pk_int,
        cmi_int,
        crf_int,
        rbind2_int,
    )

    try:
        verified_ch = (int(str(ch_calc)) == int(str(obj.get("CH") or 0)))
    except Exception:
        verified_ch = False

    try:
        verified_cch = (int(str(cch_calc)) == int(str(obj.get("CCH") or 0)))
    except Exception:
        verified_cch = False

    # Build PA.MEMORY and encrypt with user's public key
    from user.crypto import elgamal_encrypt_bytes as user_elg_enc

    memory_payload = {
        "PHC_backup": obj.get("PHC"),
        "CRF": (obj.get("PHC") or {}).get("SCID", {}).get("RF"),
        "CMI": str(calc_cmi_int),
        "r_bind2": obj.get("r_bind2"),
        "agent_type": agent_type,
    }

    memory_enc = user_elg_enc(int(str(req.user_pk or "0")), memory_payload)

    obj["agent_type"] = obj.get("agent_type") or agent_type
    obj["package_dir"] = package_dir
    obj["verified_cmi"] = verified_cmi
    obj["verified_af_user"] = verified_af
    obj["verified_ch_user"] = verified_ch
    obj["verified_cch_user"] = verified_cch
    obj["memory_enc"] = memory_enc

    try:
        import json as _json

        store_dir = os.path.join(os.getcwd(), "local_store", "pa_memory")
        os.makedirs(store_dir, exist_ok=True)

        phc_id = ((obj.get("PHC") or {}).get("id") or "phc").replace(":", "_")
        fname = f"{phc_id}_{int(_time.time())}.json"
        full_path = os.path.join(store_dir, fname)

        _json.dump(
            {
                "memory_enc": memory_enc,
                "meta": {
                    "phc_id": phc_id,
                    "hid": req.hid,
                    "agent_type": agent_type,
                    "timestamp": int(_time.time()),
                },
            },
            open(full_path, "w", encoding="utf-8"),
            ensure_ascii=False,
        )

        obj["memory_path"] = full_path
    except Exception:
        obj["memory_path"] = None

    try:
        chain = ((obj.get("PHC") or {}).get("ASO") or {}).get("HASH_CHAIN") or {}
        chain_head = chain.get("head")

        local_prev = sha256_hex(str(hid_use))
        idx = 0

        for row in (req.cmc or []):
            for it in (row or []):
                if isinstance(it, dict):
                    data_obj = {
                        "idx": idx,
                        "id": str(it.get("id") or ""),
                        "label": str(it.get("label") or ""),
                        "params": it.get("params") or {},
                    }
                else:
                    data_obj = {
                        "idx": idx,
                        "id": "",
                        "label": str(it or ""),
                        "params": {},
                    }

                data = canonical_json(data_obj)
                local_prev = sha256_hex(local_prev + data)
                idx += 1

        obj["verified_hash_chain_user"] = (str(local_prev) == str(chain_head or ""))
    except Exception:
        obj["verified_hash_chain_user"] = False

    t_verify_end = _time.perf_counter()
    obj["perf_user_verify_pa_ms"] = (t_verify_end - t_verify_start) * 1000.0

    return obj

@app.post('/user/create_agent')
def user_create_agent(req: RequestCreateAgent) -> Dict[str, Any]:
    try:
        import os, json, time

        phc = req.phc or {}
        pa = req.pa or {}
        cmc = req.cmc or []

        agent_type = (req.agent_type or "").strip().lower()
        if agent_type not in {"octopus", "openclaw"}:
            agent_type = detect_agent_type(cmc)

        phc_id = (phc.get("id") or "phc").replace(":", "_")
        did = (
            phc.get("DID")
            or ((phc.get("ASO") or {}).get("TPM") or {}).get("CDID")
        )

        root = os.path.join(os.getcwd(), "local_store", "agents", phc_id)
        os.makedirs(root, exist_ok=True)

        # ==========================
        # OpenClaw create_agent 分支
        # ==========================
        if agent_type == "openclaw":
            try:
                dependency_status = detect_windows_dependencies()
                if not dependency_status.get("ready_for_openclaw"):
                    return {
                        "success": False,
                        "agent_type": "openclaw",
                        "error": "missing_openclaw_dependencies",
                        "message": "当前电脑缺少 OpenClaw 所需依赖，请先安装 Node.js 和 Git。",
                        "dependencies": dependency_status,
                    }

                cmi_val = ((pa.get("APM") or {}).get("CMI"))

                # RequestCreateAgent 当前没有 HID 字段�?
                # 这里不写 PII/BI，只�?DID/PHC ID 做本地非敏感索引�?
                hid_val = did or phc.get("DID") or phc_id

                openclaw_info = build_openclaw_agent_files(
                    root=root,
                    phc=phc,
                    pa=pa,
                    cmc=cmc,
                    hid=str(hid_val),
                    package_cmi=str(cmi_val) if cmi_val is not None else None,
                    hooks_config=req.hooks_config,
                    skills_config=req.skills_config,
                    llm_config=req.llm_config,
                )

                manifest = {
                    "id": phc_id,
                    "agent_type": "openclaw",
                    "did": did,
                    "modules": {
                        "features": [m.get("label") for m in (cmc[0] if len(cmc) > 0 else []) if isinstance(m, dict)],
                        "gateway": [m.get("label") for m in (cmc[1] if len(cmc) > 1 else []) if isinstance(m, dict)],
                        "personality": [m.get("label") for m in (cmc[2] if len(cmc) > 2 else []) if isinstance(m, dict)],
                        "hooks": [m.get("label") for m in (cmc[3] if len(cmc) > 3 else []) if isinstance(m, dict)],
                        "skills": [m.get("label") for m in (cmc[4] if len(cmc) > 4 else []) if isinstance(m, dict)],
                        "knowledge": [m.get("label") for m in (cmc[5] if len(cmc) > 5 else []) if isinstance(m, dict)],
                        "channels": [m.get("label") for m in (cmc[6] if len(cmc) > 6 else []) if isinstance(m, dict)],
                        "appearance": [m.get("label") for m in (cmc[7] if len(cmc) > 7 else []) if isinstance(m, dict)],
                    },
                    "binding": {
                        "PHC_id": phc.get("id"),
                        "SCID": phc.get("SCID"),
                        "APid": ((pa.get("APA") or {}).get("APid")),
                    },
                    "proof": {
                        "APA": (pa.get("APA") or {}).get("APproof"),
                        "APCH": ((phc.get("PROOF") or {}).get("APCH")),
                        "APCH_r": ((phc.get("PROOF") or {}).get("APCH_r")),
                    },
                    "openclaw": {
                        "package_dir": openclaw_info.get("package_dir"),
                        "state_dir": openclaw_info.get("state_dir"),
                        "config_path": openclaw_info.get("config_path"),
                        "binding_path": openclaw_info.get("binding_path"),
                        "runtime_info_path": openclaw_info.get("runtime_info_path"),
                        "manifest_path": openclaw_info.get("manifest_path"),
                        "workspace_state_path": openclaw_info.get("workspace_state_path"),
                        "deploy_script": openclaw_info.get("deploy_script"),
                        "launcher": openclaw_info.get("launcher"),
                    },
                }

                manifest_path = os.path.join(root, "agent_manifest.json")

                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)

                return {
                    "success": True,
                    "agent_type": "openclaw",
                    "agent_path": manifest_path,
                    "manifest": manifest,
                    "openclaw_package": openclaw_info.get("package_dir"),
                    "openclaw_state_dir": openclaw_info.get("state_dir"),
                    "openclaw_config": openclaw_info.get("config_path"),
                    "openclaw_binding": openclaw_info.get("binding_path"),
                    "openclaw_runtime_info": openclaw_info.get("runtime_info_path"),
                    "openclaw_manifest": openclaw_info.get("manifest_path"),
                    "openclaw_workspace_state": openclaw_info.get("workspace_state_path"),
                    "deploy_script": openclaw_info.get("deploy_script"),
                    "personal_launcher": openclaw_info.get("launcher"),
                    "binding": openclaw_info.get("binding"),
                    "policy": openclaw_info.get("policy"),
                }

            except Exception as e:
                return {
                    "success": False,
                    "agent_type": "openclaw",
                    "error": str(e),
                }
        manifest = {
            "id": phc_id,
            "did": did,
            "modules": {
                "features": [m.get("label") for m in (cmc[0] if len(cmc)>0 else [])],
                "inputs": [m.get("label") for m in (cmc[1] if len(cmc)>1 else [])],
                "reasoning": [m.get("label") for m in (cmc[2] if len(cmc)>2 else [])],
                "knowledge": [m.get("label") for m in (cmc[3] if len(cmc)>3 else [])],
                "outputs": [m.get("label") for m in (cmc[4] if len(cmc)>4 else [])],
            },
            "binding": {
                "PHC_id": phc.get("id"),
                "SCID": phc.get("SCID"),
                "APid": ((pa.get("APA") or {}).get("APid")),
            },
            "proof": {
                "APA": (pa.get("APA") or {}).get("APproof"),
                "APCH": ((phc.get("PROOF") or {}).get("APCH")),
                "APCH_r": ((phc.get("PROOF") or {}).get("APCH_r")),
            },
        }

        # keep a single manifest file; remove old timestamped manifests
        try:
            import glob
            for old in glob.glob(os.path.join(root, "agent_manifest_*.json")):
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass
        path = os.path.join(root, "agent_manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        features = manifest.get("modules", {}).get("features", [])
        mapping = {"text-processing": "text_processor", "news-search": "news", "web-browsing": "web_browsing"}
        allowed_agents = [mapping.get(x, "") for x in features]
        allowed_agents = [x for x in allowed_agents if x]
        theme = "purple"
        try:
            appearance = [str((m.get("label") if isinstance(m, dict) else m) or "") for m in (cmc[5] if len(cmc)>5 else [])]
            sel = (appearance[0] if appearance else "").lower().strip().replace(" ", "").replace("_", "-")
            if "blue" in sel:
                theme = "blue"
            elif "pink" in sel:
                theme = "pink"
            elif "green" in sel:
                theme = "green"
            elif "purple" in sel:
                theme = "purple"
        except Exception:
            theme = "purple"
        active_path = os.path.join(root, "active_agents.json")
        with open(active_path, "w", encoding="utf-8") as f2:
            json.dump({"allowed_agents": allowed_agents, "theme": theme}, f2, ensure_ascii=False, indent=2)
        bat_path = None
        reason = manifest.get("modules", {}).get("reasoning", [])
        labels = [str(m or "") for m in reason]
        prov = "openai"
        try:
            lab_set = set(labels)
            if ("rag-openai" in lab_set):
                prov = "openai"
            else:
                prov = "openai"
        except Exception:
            prov = "openai"
        inputs = manifest.get("modules", {}).get("inputs", [])
        try:
            allow_img = ("image" in [str(x or "") for x in inputs])
        except Exception:
            allow_img = False
        outputs = manifest.get("modules", {}).get("outputs", [])
        try:
            allow_speech = ("speech" in [str(x or "") for x in outputs])
        except Exception:
            allow_speech = False
        personal_bat = None
        try:
            import shutil
            personal_dir = os.path.join(root, "octopus_build")
            src_dir = os.path.join(os.getcwd(), "agent_provider", "octopus")
            # A running venv can lock files on Windows. Deleting then copying used
            # to leave only the locked venv behind and silently lose the package.
            if os.path.exists(personal_dir):
                from app.experience_runtime import repair_octopus_package
                repair_octopus_package(Path(personal_dir))
            else:
                shutil.copytree(src_dir, personal_dir, dirs_exist_ok=False,
                    ignore=shutil.ignore_patterns('.venv','.web-venv','__pycache__','.git'))
            prune_map = {
                "text_processor": os.path.join(personal_dir, "octopus", "agents", "text_processor_agent.py"),
                "news": os.path.join(personal_dir, "octopus", "agents", "news_agent.py"),
                "web_browsing": os.path.join(personal_dir, "octopus", "agents", "web_browsing_agent.py"),
            }
            keep = set(allowed_agents)
            for name, fpath in prune_map.items():
                if name not in keep and os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
            personal_bat = os.path.join(root, "launch_octopus_personal.bat")
            with open(personal_bat, "w", encoding="utf-8") as pbf:
                pbf.write("@echo off\n")
                pbf.write("setlocal enabledelayedexpansion\n")
                pbf.write("set SCRIPT_DIR=%~dp0\n")
                pbf.write("set REPO_DIR=%SCRIPT_DIR%..\\..\\..\n")
                pbf.write(f"set PERSONAL_DIR=%REPO_DIR%\\local_store\\agents\\{phc_id}\\octopus_build\n")
                pbf.write(f"set ALLOWED_PATH=%REPO_DIR%\\local_store\\agents\\{phc_id}\\active_agents.json\n")
                pbf.write("pushd \"%REPO_DIR%\"\n")
                pbf.write("set PYEXE=python\n")
                pbf.write("set VENV_PY=%REPO_DIR%\\.venv\\Scripts\\python.exe\n")
                pbf.write("if exist \"%VENV_PY%\" set PYEXE=\"%VENV_PY%\"\n")
                pbf.write("set OCTOPUS_ALLOWED_AGENTS_PATH=%ALLOWED_PATH%\n")
                pbf.write("set MODEL_PROVIDER=openai\n")
                pbf.write("set ANP_SDK_ENABLED=true\n")
                pbf.write("set DOTENV_PATH=%REPO_DIR%\\agent_provider\\octopus\\.env\n")
                pbf.write(f"set INPUTS_INCLUDE_IMAGE={'true' if allow_img else 'false'}\n")
                pbf.write(f"set OUTPUTS_INCLUDE_SPEECH={'true' if allow_speech else 'false'}\n")
                pbf.write(f"set OCTOPUS_THEME={theme}\n")
                pbf.write("echo Checking Octopus dependencies...\n")
                pbf.write("%PYEXE% -m pip install -q openai python-dotenv httpx pydantic pydantic-settings fastapi uvicorn\n")
                pbf.write("set PYTHONPATH=%PERSONAL_DIR%\n")
                pbf.write("cd /d \"%PERSONAL_DIR%\"\n")
                pbf.write("%PYEXE% -m octopus.octopus --port 9527 --anp-gateway ws://127.0.0.1:8765/ws\n")
                pbf.write("if errorlevel 1 (echo Octopus failed to start. Press any key to view logs & pause)\n")
                pbf.write("timeout /t 1 >nul\n")
                pbf.write("start \"\" http://localhost:9527/\n")
                pbf.write("popd\n")
        except Exception:
            personal_bat = None
        return {"success": True, "agent_path": path, "manifest": manifest, "launcher": None, "personal_launcher": personal_bat, "allowed": allowed_agents}
    except Exception:
        return {"success": False}

@app.get('/user/openclaw/dependencies')
def user_openclaw_dependencies() -> Dict[str, Any]:
    try:
        return detect_windows_dependencies()
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get('/user/llm_providers')
def user_llm_providers() -> Dict[str, Any]:
    """返回支持的大模型提供商列表，前端用于下拉选择"""
    try:
        from agent_provider.openclaw.openclaw_package import LLM_PROVIDERS
        providers = []
        for key, cfg in LLM_PROVIDERS.items():
            providers.append({
                "key": key,
                "name": cfg["name"],
                "default_base_url": cfg["default_base_url"],
                "models": cfg["models"],
                "default_model": cfg["default_model"],
            })
        return {"success": True, "providers": providers}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post('/user/openclaw/install_dependencies')
def user_openclaw_install_dependencies(req: DependencyInstallRequest) -> Dict[str, Any]:
    try:
        return launch_dependency_installer(req.target)
    except Exception as e:
        return {"success": False, "error": str(e)}

def _verify_and_restore_pa(
    obj: Dict[str, Any],
    user: UserInfo,
    agent_type: str,
    tp_base_url: str,
) -> Dict[str, Any]:
    """恢复后校验结果（AF/CH/CCH，CMI 视本地快照而定）并封存 PA.MEMORY。

    obj 为 request_pa_recover 解密后的结果，需包含 ap_pk/tp_pk/r_bind2/r_ap/CH/CCH
    （由 AP 的 recover_pa 返回）。校验逻辑与 user_cmm_submit 保持一致。
    """
    import json as _json
    from user.crypto import elgamal_encrypt_bytes as user_elg_enc

    hid = sha256_hex(user.pii.id_number)
    phc = obj.get("PHC") or {}
    pa = obj.get("PA") or {}
    apm = pa.get("APM") or {}
    apa = pa.get("APA") or {}

    pa_cmi = str(apm.get("CMI") or "")
    try:
        cmi_int = int(pa_cmi)
    except Exception:
        cmi_int = 0

    try:
        rf_val = ((phc.get("SCID") or {}).get("RF") if isinstance(phc.get("SCID"), dict) else None)
        crf_int = int(str(rf_val or 0))
    except Exception:
        crf_int = 0

    try:
        rbind2_int = int(str(obj.get("r_bind2") or 0))
    except Exception:
        rbind2_int = 0
    try:
        ap_pk_int = int(str(obj.get("ap_pk") or 0))
    except Exception:
        ap_pk_int = 0
    try:
        tp_pk_int = int(str(obj.get("tp_pk") or 0))
    except Exception:
        tp_pk_int = 0

    af_calc_user = compute_af_formal(str(hid), ap_pk_int, tp_pk_int, cmi_int, crf_int, rbind2_int)
    af_prev = ((phc.get("ASO") or {}).get("TPM") or {}).get("AF")
    verified_af = (str(af_prev) == str(af_calc_user))

    try:
        r_ap_val = int(str(obj.get("r_ap") or 0))
    except Exception:
        r_ap_val = 0
    ch_calc = ch_compute(ap_pk_int, apm, apa, r_ap_val)
    cch_calc = cch_compute(ap_pk_int, tp_pk_int, cmi_int, crf_int, rbind2_int)
    try:
        verified_ch = (int(str(ch_calc)) == int(str(obj.get("CH") or 0)))
    except Exception:
        verified_ch = False
    try:
        verified_cch = (int(str(cch_calc)) == int(str(obj.get("CCH") or 0)))
    except Exception:
        verified_cch = False

    # CMI 校验：本地代码快照存在时比对，否则跳过（保持 AP 侧返回的 verified_cmi）
    verified_cmi = None
    try:
        from crypto_lib import dir_code_cmi_hid
        phc_id = (phc.get("id") or "phc").replace(":", "_")
        base_dir = os.path.join(os.getcwd(), "local_store", "agents", phc_id)
        calc_dir = os.path.join(base_dir, "openclaw_package") if str(agent_type or "").strip().lower() == "openclaw" else os.path.join(base_dir, "octopus_build")
        if os.path.isdir(calc_dir):
            calc_cmi = dir_code_cmi_hid(calc_dir, hid)
            verified_cmi = (str(calc_cmi) == pa_cmi)
    except Exception:
        verified_cmi = None

    if verified_cmi is False:
        raise ValueError("本机智能体代码的 CMI 与 AP 恢复的历史能力配置不一致，未请求 TP 更新凭证。")
    if not verified_af or not verified_ch or not verified_cch:
        raise ValueError("恢复结果的 AF、CH 或 CCH 校验未通过，未请求 TP 更新凭证。")

    if obj.get("verified_tp") is not True:
        if not tp_base_url:
            raise ValueError("本地 PHC 的 TP 签名无效，未配置 TP 地址，无法安全重新签发。")
        if obj.get("verified_ch") is not True or obj.get("verified_af") is not True:
            raise ValueError("AP 返回的恢复凭证未通过 CH 或 AF 校验，已停止 TP 重新签发。")
        try:
            reissue = httpx.post(
                normalize_service_base_url(tp_base_url) + "/v1/tp/reissue_updated_phc",
                json={
                    "hid": hid,
                    "candidate_phc": phc,
                    "pa": pa,
                    "r_bind2": obj.get("r_bind2"),
                },
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"TP 重新签发服务不可用：{exc}") from exc
        if reissue.status_code == 404:
            raise ValueError("TP 未找到有效的历史身份记录，无法重新签发 PHC。")
        try:
            reissue.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = reissue.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"TP 重新签发失败：{detail or exc}") from exc

        signed_phc = reissue.json().get("phc")
        from trust_provider.phc import verify_phc
        if (
            not isinstance(signed_phc, dict)
            or not verify_phc(signed_phc)
            or signed_phc.get("PROOF", {}).get("needs_tp_resign")
            or signed_phc.get("id") != phc.get("id")
            or ((signed_phc.get("ASO") or {}).get("APM") or {}) != apm
            or (signed_phc.get("APA") or {}) != apa
        ):
            raise ValueError("TP 返回的 PHC 未通过签名或 PA 关联校验，已停止恢复。")
        phc = signed_phc
        obj["PHC"] = phc
        obj["verified_tp"] = True
        obj["verified_phc_user"] = True

    # 封存记忆：用临时密钥对加密，密钥随响应返回供用户解密
    sk_m, pk_m = dl_generate_user_keypair()
    memory_payload = {
        "PHC_backup": phc,
        "CRF": (phc.get("SCID") or {}).get("RF"),
        "CMI": pa_cmi,
        "r_bind2": obj.get("r_bind2"),
        "agent_type": agent_type,
    }
    memory_enc = user_elg_enc(pk_m, memory_payload)

    obj["agent_type"] = obj.get("agent_type") or agent_type
    if verified_cmi is not None:
        obj["verified_cmi"] = verified_cmi
    obj["verified_af_user"] = verified_af
    obj["verified_ch_user"] = verified_ch
    obj["verified_cch_user"] = verified_cch
    obj["memory_enc"] = memory_enc
    obj["memory_sk"] = str(sk_m)
    obj["memory_pk"] = str(pk_m)

    try:
        store_dir = os.path.join(os.getcwd(), "local_store", "pa_memory")
        os.makedirs(store_dir, exist_ok=True)
        phc_id = (phc.get("id") or "phc").replace(":", "_")
        fname = f"{phc_id}_{int(_time.time())}.json"
        full_path = os.path.join(store_dir, fname)
        with open(full_path, "w", encoding="utf-8") as memory_file:
            _json.dump(
                {
                    "memory_enc": memory_enc,
                    "meta": {
                        "phc_id": phc_id,
                        "hid": hid,
                        "agent_type": agent_type,
                        "timestamp": int(_time.time()),
                    },
                },
                memory_file,
                ensure_ascii=False,
            )
        obj["memory_path"] = full_path
    except Exception:
        obj["memory_path"] = None

    return obj


@app.post('/user/recover_pa')
def user_recover_pa(req: RequestPARecover) -> Dict[str, Any]:
    # 场景 2「仅恢复 PA」：已持有 PHC，直接提交 PHC + HID 恢复，不做 PII/BI 身份校验
    try:
        pa_obj = request_pa_recover(req.base_url, req.phc, req.user)
        pa_obj = _verify_and_restore_pa(pa_obj, req.user, req.agent_type, req.tp_base_url)
        return {"success": True, "phc": pa_obj.get("PHC") or req.phc, "pa": pa_obj}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _last_agent_path(request: Request = None) -> str:
    if request is not None:
        session = auth.current_session(request, auth.COOKIE_USER, 'user')
        if session:
            session = auth.public_session(session)
        if session and session['username'] != 'user':
            import hashlib
            account = hashlib.sha256(session['username'].encode('utf-8')).hexdigest()
            return os.path.join(os.getcwd(), 'local_store', 'user_state', account, 'last_agent.json')
    return os.path.join(os.getcwd(), "local_store", "user_state", "last_agent.json")


@app.get('/user/last_agent')
def user_get_last_agent(request: Request) -> Dict[str, Any]:
    """读取最近一次创建的智能体快照，供更新/故障恢复在重启后直接复用。"""
    try:
        path = _last_agent_path(request)
        if not os.path.exists(path):
            return {"success": False, "error": "no_last_agent"}
        with open(path, "r", encoding="utf-8") as f:
            return {"success": True, "agent": json.load(f)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post('/user/last_agent')
def user_save_last_agent(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """保存最近一次创建的智能体快照（含 PHC/PA/CMC/agent_type/身份/技能）。"""
    try:
        path = _last_agent_path(request)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post('/user/update_init')
def user_update_init(req: RequestUpdateInit) -> Dict[str, Any]:
    try:
        import httpx
        ap_base_url = normalize_service_base_url(req.base_url)
        pub_resp = httpx.get(ap_base_url + '/ap/public_keys', timeout=10.0)
        pub_resp.raise_for_status()
        ap_dlog_pk = int(str(pub_resp.json()["ap_dlog_pk"]))
    except Exception:
        from agent_provider.ap import AP_PK as ap_dlog_pk
    sk_a, pk_a = dl_generate_user_keypair()
    hid = sha256_hex(req.user.pii.id_number)
    crf = (req.phc.get("CRF") if isinstance(req.phc, dict) else None) or ((req.phc.get("SCID") or {}).get("RF") if isinstance(req.phc, dict) else 0)
    ar_plain = {"PHC": req.phc, "HID": hid, "CRF": crf}
    ar = elgamal_encrypt_bytes(ap_dlog_pk, ar_plain)
    try:
        import httpx
        r = httpx.post(
            ap_base_url + '/v1/ap/update_init',
            json={
                "ar": ar,
                "user_pub": pk_a,
                "agent_type": req.agent_type,
            },
            timeout=15.0
        )
        r.raise_for_status()
        data = r.json()
        cmm_enc = data.get("cmm_enc")
        raw = elgamal_decrypt_bytes(int(sk_a), cmm_enc)
        import json
        return {"cmm": json.loads(raw.decode()).get("CMM"), "sk": str(sk_a), "pk": str(pk_a)}
    except Exception:
        from agent_provider.ap import _build_cmm_matrix
        cmm = _build_cmm_matrix(hid, req.phc, agent_type=req.agent_type)
        return {"cmm": cmm, "sk": str(sk_a), "pk": str(pk_a), "fallback": True}

@app.post('/user/update_submit')
def user_update_submit(req: RequestUpdateSubmit) -> Dict[str, Any]:
    try:
        import httpx, json
        ap_base_url = normalize_service_base_url(req.base_url)
        pub_resp = httpx.get(ap_base_url + '/v1/ap/public_keys', timeout=10.0)
        pub_resp.raise_for_status()
        ap_dlog_pk = int(str(pub_resp.json()["ap_dlog_pk"]))
    except Exception:
        from agent_provider.ap import AP_PK as ap_dlog_pk
    try:
        user_pk_int = int(str(req.user_pk or ""))
        user_sk_int = int(str(req.user_sk or ""))
        if user_pk_int == 0 or user_sk_int == 0:
            raise ValueError("empty keys")
    except Exception:
        user_sk_int, user_pk_int = dl_generate_user_keypair()
    try:
        hid_str = str(req.hid or "")
        is_hex = (len(hid_str) == 64 and all(c in "0123456789abcdefABCDEF" for c in hid_str))
        hid_use = hid_str if is_hex else sha256_hex(hid_str)
    except Exception:
        hid_use = sha256_hex(str(req.hid))
    # Compute code-based CMI for updated configuration
    try:
        import os, shutil
        phc = req.phc or {}
        phc_id = (phc.get("id") or "phc").replace(":", "_")
        root = os.path.join(os.getcwd(), "local_store", "agents", phc_id)
        os.makedirs(root, exist_ok=True)
        features = [m.get("label") for m in (req.cmc[0] if len(req.cmc)>0 else [])]
        mapping = {"text-processing": "text_processor", "news-search": "news", "web-browsing": "web_browsing"}
        allowed_agents = [mapping.get(x, "") for x in features]
        allowed_agents = [x for x in allowed_agents if x]
        personal_dir = os.path.join(root, "octopus_build")
        src_dir = os.path.join(os.getcwd(), "agent_provider", "octopus")
        # Refresh code without deleting the instance's Python environment,
        # model configuration or runtime logs. Deleting this directory used
        # to remove .web-venv and made every subsequent launch reinstall it.
        shutil.copytree(src_dir, personal_dir, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns('.venv', '.web-venv', 'venv',
                '__pycache__', '.git', '.idea', '.vscode', '.env', '*.log', '*.egg-info'))
        prune_map = {
            "text_processor": os.path.join(personal_dir, "octopus", "agents", "text_processor_agent.py"),
            "news": os.path.join(personal_dir, "octopus", "agents", "news_agent.py"),
            "web_browsing": os.path.join(personal_dir, "octopus", "agents", "web_browsing_agent.py"),
        }
        keep = set(allowed_agents)
        for name, fpath in prune_map.items():
            if name not in keep and os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
        from crypto_lib import dir_code_cmi_hid
        cmi_code_int = dir_code_cmi_hid(personal_dir, hid_use)
    except Exception:
        cmi_code_int = None
    obj = {"CMC": req.cmc, "HID": hid_use, "PHC": req.phc}
    if cmi_code_int is not None:
        obj["CMI_code"] = str(int(cmi_code_int))
    # Send plaintext payload for update_submit; server supports both encrypted and plaintext
    cmc_enc = obj
    url = ap_base_url + '/v1/ap/update_submit'
    try:
        import httpx
        resp = httpx.post(url, json={"cmc_enc": cmc_enc, "user_pub": user_pk_int}, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        par = data.get("par")
        if not par:
            return data
        raw = elgamal_decrypt_bytes(int(user_sk_int), par).decode()
        obj2 = json.loads(raw)
        try:
            hid_str = str(req.hid or "")
            is_hex = (len(hid_str) == 64 and all(c in "0123456789abcdefABCDEF" for c in hid_str))
            hid_use = hid_str if is_hex else sha256_hex(hid_str)
        except Exception:
            hid_use = sha256_hex(str(req.hid))
        calc_cmi_int = cmi_code_int if cmi_code_int is not None else hcgen_cmi(req.cmc, hid_use)
        pa_cmi = ((obj2.get("PA") or {}).get("APM") or {}).get("CMI")
        verified_cmi = (str(calc_cmi_int) == str(pa_cmi))
        try:
            ap_pk_int = int(str(obj2.get("ap_pk")))
        except Exception:
            ap_pk_int = 0
        try:
            tp_pk_int = int(str(obj2.get("tp_pk")))
        except Exception:
            tp_pk_int = 0
        try:
            rbind3_int = int(str(obj2.get("r_bind2") or 0))
        except Exception:
            rbind3_int = 0
        try:
            crf_src = ((obj2.get("PHC") or {}).get("SCID") or {}).get("RF")
            crf_int = int(str(crf_src or 0))
        except Exception:
            crf_int = 0
        try:
            cmi_int = int(str(pa_cmi))
        except Exception:
            cmi_int = int(str(calc_cmi_int))
        af_calc_user = compute_af_formal(str(hid_use), ap_pk_int, tp_pk_int, cmi_int, crf_int, rbind3_int)
        af_prev = ((obj2.get("PHC") or {}).get("ASO") or {}).get("TPM", {}).get("AF")
        verified_af = (str(af_prev) == str(af_calc_user))
        obj2["verified_cmi"] = verified_cmi
        obj2["verified_af_user"] = verified_af

        if not verified_cmi or not verified_af:
            return {"success": False, "error": "ap_update_verification_failed", "verified_cmi": verified_cmi, "verified_af_user": verified_af}
        try:
            from trust_provider.phc import verify_phc
            reissue = httpx.post(
                normalize_service_base_url(req.tp_base_url) + '/v1/tp/reissue_updated_phc',
                json={"hid": hid_use, "candidate_phc": obj2["PHC"], "pa": obj2["PA"], "r_bind2": obj2.get("r_bind2")},
                timeout=15.0,
            )
            if reissue.status_code == 404:
                return {"success": False, "error": "TP 重签接口不可用，请重启 TP 服务后重试。"}
            reissue.raise_for_status()
            signed_phc = reissue.json().get("phc")
            if not signed_phc or not verify_phc(signed_phc) or signed_phc.get("PROOF", {}).get("needs_tp_resign"):
                return {"success": False, "error": "TP 未返回可验证的重签凭证。"}
            obj2["PHC"] = signed_phc
            obj2["verified_phc_user"] = True
        except Exception as exc:
            detail = ""
            try:
                detail = str(reissue.json().get("detail") or "")
            except Exception:
                pass
            return {"success": False, "error": "TP 重签失败：" + (detail or str(exc))}

        # Update local agent configuration files (manifest, active_agents, launcher)
        try:
            import os, json
            phc_id = (req.phc.get("id") or "phc").replace(":", "_")
            root = os.path.join(os.getcwd(), "local_store", "agents", phc_id)
            os.makedirs(root, exist_ok=True)

            cmc = req.cmc or []
            phc_new = obj2.get("PHC") or req.phc or {}
            pa_new = obj2.get("PA") or {}

            # 1. Update active_agents.json
            features = [m.get("label") for m in (cmc[0] if len(cmc) > 0 else [])]
            mapping = {"text-processing": "text_processor", "news-search": "news", "web-browsing": "web_browsing"}
            allowed_agents = [mapping.get(x, "") for x in features]
            allowed_agents = [x for x in allowed_agents if x]

            theme = "purple"
            try:
                appearance = [str((m.get("label") if isinstance(m, dict) else m) or "") for m in (cmc[5] if len(cmc) > 5 else [])]
                sel = (appearance[0] if appearance else "").lower().strip().replace(" ", "").replace("_", "-")
                if "blue" in sel:
                    theme = "blue"
                elif "pink" in sel:
                    theme = "pink"
                elif "green" in sel:
                    theme = "green"
                elif "purple" in sel:
                    theme = "purple"
            except Exception:
                theme = "purple"

            active_path = os.path.join(root, "active_agents.json")
            with open(active_path, "w", encoding="utf-8") as f2:
                json.dump({"allowed_agents": allowed_agents, "theme": theme}, f2, ensure_ascii=False, indent=2)

            # 2. Update agent_manifest.json
            did = ((phc_new.get("ASO") or {}).get("TPM") or {}).get("CDID")
            manifest = {
                "id": phc_id,
                "did": did,
                "modules": {
                    "features": [m.get("label") for m in (cmc[0] if len(cmc) > 0 else [])],
                    "inputs": [m.get("label") for m in (cmc[1] if len(cmc) > 1 else [])],
                    "reasoning": [m.get("label") for m in (cmc[2] if len(cmc) > 2 else [])],
                    "knowledge": [m.get("label") for m in (cmc[3] if len(cmc) > 3 else [])],
                    "outputs": [m.get("label") for m in (cmc[4] if len(cmc) > 4 else [])],
                },
                "binding": {
                    "PHC_id": phc_new.get("id"),
                    "SCID": phc_new.get("SCID"),
                    "APid": ((pa_new.get("APA") or {}).get("APid")),
                },
                "proof": {
                    "APA": (pa_new.get("APA") or {}).get("APproof"),
                    "APCH": ((phc_new.get("PROOF") or {}).get("APCH")),
                    "APCH_r": ((phc_new.get("PROOF") or {}).get("APCH_r")),
                },
            }
            manifest_path = os.path.join(root, "agent_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            # 3. Update launcher (launch_octopus_personal.bat)
            inputs = manifest.get("modules", {}).get("inputs", [])
            allow_img = ("image" in [str(x or "") for x in inputs])
            outputs = manifest.get("modules", {}).get("outputs", [])
            allow_speech = ("speech" in [str(x or "") for x in outputs])

            personal_bat = os.path.join(root, "launch_octopus_personal.bat")
            with open(personal_bat, "w", encoding="utf-8") as pbf:
                pbf.write("@echo off\n")
                pbf.write("setlocal enabledelayedexpansion\n")
                pbf.write("set SCRIPT_DIR=%~dp0\n")
                pbf.write("set REPO_DIR=%SCRIPT_DIR%..\\..\\..\n")
                pbf.write(f"set PERSONAL_DIR=%REPO_DIR%\\local_store\\agents\\{phc_id}\\octopus_build\n")
                pbf.write(f"set ALLOWED_PATH=%REPO_DIR%\\local_store\\agents\\{phc_id}\\active_agents.json\n")
                pbf.write("pushd \"%REPO_DIR%\"\n")
                pbf.write("set PYEXE=python\n")
                pbf.write("set VENV_PY=%REPO_DIR%\\.venv\\Scripts\\python.exe\n")
                pbf.write("if exist \"%VENV_PY%\" set PYEXE=\"%VENV_PY%\"\n")
                pbf.write("set OCTOPUS_ALLOWED_AGENTS_PATH=%ALLOWED_PATH%\n")
                pbf.write("set MODEL_PROVIDER=openai\n")
                pbf.write("set ANP_SDK_ENABLED=true\n")
                pbf.write("set DOTENV_PATH=%REPO_DIR%\\agent_provider\\octopus\\.env\n")
                pbf.write(f"set INPUTS_INCLUDE_IMAGE={'true' if allow_img else 'false'}\n")
                pbf.write(f"set OUTPUTS_INCLUDE_SPEECH={'true' if allow_speech else 'false'}\n")
                pbf.write(f"set OCTOPUS_THEME={theme}\n")
                pbf.write("echo Checking Octopus dependencies...\n")
                pbf.write("%PYEXE% -m pip install -q openai python-dotenv httpx pydantic pydantic-settings fastapi uvicorn\n")
                pbf.write("set PYTHONPATH=%PERSONAL_DIR%\n")
                pbf.write("cd /d \"%PERSONAL_DIR%\"\n")
                pbf.write("%PYEXE% -m octopus.octopus --port 9527 --anp-gateway ws://127.0.0.1:8765/ws\n")
                pbf.write("if errorlevel 1 (echo Octopus failed to start. Press any key to view logs & pause)\n")
                pbf.write("timeout /t 1 >nul\n")
                pbf.write("start \"\" http://localhost:9527/\n")
                pbf.write("popd\n")

            # Update response with local config
            obj2["manifest"] = manifest
            obj2["allowed_agents"] = allowed_agents
            obj2["theme"] = theme
        except Exception as e:
            print(f"Error updating local agent configuration: {e}")

        return obj2
    except Exception as e:
        return {"success": False, "error": str(e)}



@app.get('/user')
def ui() -> Response:
    return Response(status_code=303, headers={"Location": "/user/static/experience/index.html", "Cache-Control": "no-store"})


# ==================== 子 Agent 数据模型 ====================

class SubAgentConfig(BaseModel):
    """子 Agent 配置"""
    name: str
    description: str = ""
    capabilities: List[str] = []  # 能力列表
    parent_phc_id: str  # 所属主 Agent 的 PHC ID
    agent_type: str = "openclaw"
    hooks_config: Optional[Dict[str, bool]] = None
    skills_config: Optional[List[str]] = None
    llm_config: Optional[Dict[str, Any]] = None
    communication_config: Optional[Dict[str, Any]] = None


class SubAgentInfo(BaseModel):
    """子 Agent 信息"""
    id: str
    name: str
    phc_id: str
    status: str  # created, deployed, running, stopped
    created_at: str
    deploy_path: Optional[str] = None
    gateway_port: Optional[int] = None
    token: Optional[str] = None


class MultiAgentGroup(BaseModel):
    """多 Agent 组"""
    group_id: str
    group_name: str
    parent_agent_id: str  # 主 Agent 的 PHC ID
    sub_agents: List[SubAgentInfo]
    communication_config: Dict[str, Any]
    created_at: str


class AgentMessage(BaseModel):
    """Agent 间消息"""
    from_agent: str
    to_agent: str
    message_type: str  # chat, command, broadcast
    content: Any
    timestamp: str


# ==================== 存储管理 ====================

AGENT_GROUPS_DIR = Path("local_store/agent_groups")
AGENT_GROUPS_DIR.mkdir(parents=True, exist_ok=True)


def agent_group_path(group_id: str) -> Path:
    # PHC identifiers contain ':'; on Windows this denotes an NTFS data stream.
    import re
    if not re.fullmatch(r'[\w:.-]+', group_id) or group_id in {'.', '..'}:
        raise ValueError('Invalid agent group identifier')
    return AGENT_GROUPS_DIR / f"{group_id.replace(':', '_')}.json"


def save_agent_group(group: MultiAgentGroup) -> None:
    """保存 Agent 组配置"""
    path = agent_group_path(group.group_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(group.model_dump(), f, ensure_ascii=False, indent=2)


def load_agent_group(group_id: str) -> Optional[MultiAgentGroup]:
    """加载 Agent 组配置"""
    path = agent_group_path(group_id)
    if not path.exists():
        # Read historical colon filenames (including NTFS streams) without deleting them.
        path = AGENT_GROUPS_DIR / f"{group_id}.json"
        if not path.exists():
            return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # Windows may report the base NTFS file as existing even when the
        # requested historical alternate data stream does not exist.
        return None
    return MultiAgentGroup(**data)


def list_agent_groups(parent_agent_id: str = None) -> List[MultiAgentGroup]:
    """列出所有 Agent 组"""
    groups = []
    if parent_agent_id:
        group_id = f'group_{parent_agent_id}'
        if not agent_group_path(group_id).exists():
            historical = load_agent_group(group_id)
            if historical and historical.parent_agent_id == parent_agent_id:
                save_agent_group(historical)
    for path in AGENT_GROUPS_DIR.glob("*.json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        canonical = agent_group_path(data['group_id'])
        if path != canonical and canonical.exists():
            continue
        if parent_agent_id is None or data.get("parent_agent_id") == parent_agent_id:
            groups.append(MultiAgentGroup(**data))
    return groups


# ==================== 子 Agent 创建接口 ====================

@app.post("/agent/sub/create")
async def create_sub_agent(config: SubAgentConfig) -> Dict[str, Any]:
    """
    创建子 Agent（基于已有的 PHC/PA 体系）
    """
    return {"success": False, "error": "OpenClaw 为独立身份认证实例，不支持创建子智能体。请在 Octopus 工作台创建分身。"}
    try:
        import uuid
        import secrets
        from pathlib import Path
        from datetime import datetime
        from agent_provider.openclaw.openclaw_package import build_openclaw_agent_files
        from crypto_lib import sha256_hex

        print(f"[DEBUG] Creating sub agent with parent_phc_id: {config.parent_phc_id}")

        # 1. 生成子 Agent 的唯一 ID
        sub_agent_id = f"sub_{config.name}_{uuid.uuid4().hex[:8]}"

        # 2. 查找父 Agent 的目录（将冒号替换为下划线）
        parent_phc_id_safe = config.parent_phc_id.replace(":", "_")
        parent_root = Path(f"local_store/agents/{parent_phc_id_safe}")

        print(f"[DEBUG] Looking for parent at: {parent_root}")

        if not parent_root.exists():
            agents_dir = Path("local_store/agents")
            if agents_dir.exists():
                print(f"[DEBUG] Available agents: {list(agents_dir.iterdir())}")
            return {
                "success": False,
                "error": f"父 Agent 不存在: {config.parent_phc_id} (查找路径: {parent_root})"
            }

        # 3. 加载父 Agent 的 manifest
        parent_manifest_path = parent_root / "agent_manifest.json"
        if not parent_manifest_path.exists():
            return {
                "success": False,
                "error": f"父 Agent manifest 不存在: {parent_manifest_path}"
            }

        with open(parent_manifest_path, "r") as f:
            parent_manifest = json.load(f)

        # 4. 获取父 Agent 的网关配置
        parent_config_path = parent_root / "openclaw_package" / "state" / "openclaw.json"
        parent_gateway_port = 18789  # 默认端口
        parent_token = ""
        if parent_config_path.exists():
            with open(parent_config_path, "r") as f:
                parent_config = json.load(f)
                gateway = parent_config.get("gateway", {})
                parent_gateway_port = gateway.get("port", 18789)
                parent_token = gateway.get("auth", {}).get("token", "")

        # 5. 为子 Agent 生成新的 ID
        sub_phc_id = f"{parent_phc_id_safe}_sub_{uuid.uuid4().hex[:12]}"

        # 6. 构建子 Agent 的 PHC 结构
        sub_phc = {
            "id": sub_phc_id,
            "DID": f"did:agent:{sub_phc_id}",
            "SCID": parent_manifest.get("binding", {}).get("SCID"),
            "ASO": {
                "TPM": {
                    "AF": parent_manifest.get("binding", {}).get("af"),
                    "CDID": f"did:agent:{sub_phc_id}"
                }
            },
            "TPA": parent_manifest.get("binding", {}).get("TPA"),
            "PROOF": parent_manifest.get("proof", {})
        }

        # 7. 构建子 Agent 的 PA
        sub_pa = {
            "APM": {
                "CMI": f"sub_agent_cmi_{config.name}",
                "Time": datetime.utcnow().isoformat() + "Z"
            },
            "APA": parent_manifest.get("binding", {}).get("APA")
        }

        # 8. 构建子 Agent 的 CMC
        sub_cmc = build_sub_agent_cmc(config.capabilities, config.llm_config)

        # 9. 创建子 Agent 的部署目录
        sub_root = Path(f"local_store/agents/{sub_phc_id}")
        sub_root.mkdir(parents=True, exist_ok=True)

        # 10. 生成子 Agent 的部署包
        hid = sha256_hex(sub_phc_id)

        hooks_config = config.hooks_config or {
            "session_memory": False,
            "bootstrap_extra_files": False,
            "command_logger": False,
            "boot_md": False
        }

        sub_package_info = build_openclaw_agent_files(
            root=str(sub_root),
            phc=sub_phc,
            pa=sub_pa,
            cmc=sub_cmc,
            hid=hid,
            package_cmi=sub_pa["APM"]["CMI"],
            hooks_config=hooks_config,
            skills_config=config.skills_config or [],
            llm_config=config.llm_config or {"provider": "deepseek", "model": "deepseek-v4-pro"}
        )

        # 11. 生成子 Agent 的网关配置
        gateway_port = 19000 + (hash(sub_agent_id) % 1000)
        token = secrets.token_urlsafe(32)

        # 12. 修改子 Agent 的 openclaw.json
        config_path = Path(sub_package_info["config_path"])
        if config_path.exists():
            with open(config_path, "r") as f:
                sub_config_json = json.load(f)

            sub_config_json["gateway"] = {
                "mode": "local",
                "port": gateway_port,
                "auth": {
                    "mode": "token",
                    "token": token
                }
            }

            with open(config_path, "w") as f:
                json.dump(sub_config_json, f, indent=2)

        # 13. 保存子 Agent 信息
        sub_agent_info = {
            "id": sub_agent_id,
            "name": config.name,
            "phc_id": sub_phc_id,
            "status": "created",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "deploy_path": str(sub_root),
            "gateway_port": gateway_port,
            "token": token
        }

        # 14. 父 Agent 信息
        parent_agent_info = {
            "id": config.parent_phc_id,
            "name": "parent",
            "phc_id": config.parent_phc_id,
            "gateway_port": parent_gateway_port,
            "token": parent_token
        }

        # 15. 更新或创建 Agent 组
        groups = list_agent_groups(config.parent_phc_id)
        all_agents = [parent_agent_info, sub_agent_info]

        if groups:
            group = groups[0]
            group.sub_agents.append(SubAgentInfo(**sub_agent_info))
            save_agent_group(group)
        else:
            group = MultiAgentGroup(
                group_id=f"group_{config.parent_phc_id}",
                group_name=f"Agent Group for {config.parent_phc_id}",
                parent_agent_id=config.parent_phc_id,
                sub_agents=[SubAgentInfo(**sub_agent_info)],
                communication_config={
                    "protocol": "http",
                    "discovery": "config_file",
                    "message_format": "json"
                },
                created_at=datetime.utcnow().isoformat() + "Z"
            )
            save_agent_group(group)

        # 16. 生成测试脚本 test.py（不生成 agent_bridge.py）
        test_script = generate_test_script(
            parent_agent=parent_agent_info,
            sub_agents=[sub_agent_info]
        )

        test_script_path = sub_root / "test.py"
        with open(test_script_path, "w", encoding="utf-8") as f:
            f.write(test_script)

        # 同时保存到父 Agent 目录
        parent_test_path = parent_root / "test.py"
        with open(parent_test_path, "w", encoding="utf-8") as f:
            f.write(test_script)

        print(f"[DEBUG] 测试脚本已生成: {test_script_path}")

        return {
            "success": True,
            "sub_agent": sub_agent_info,
            "group_id": group.group_id,
            "test_script_path": str(test_script_path),
            "deploy_script": sub_package_info.get("deploy_script"),
            "launcher": sub_package_info.get("launcher"),
            "message": f"子 Agent '{config.name}' 创建成功！\n"
                       f"子 Agent 目录: {sub_root}\n"
                       f"父 Agent 端口: {parent_gateway_port}\n"
                       f"子 Agent 端口: {gateway_port}\n"
                       f"请先确保两个 Agent 都已启动，然后运行 test.py 测试连接"
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }


def generate_test_script(parent_agent: Dict[str, Any], sub_agents: List[Dict[str, Any]]) -> str:
    """
    生成测试脚本 test.py，用于测试 Agent 的 HTTP API 是否可用
    """
    all_agents = [parent_agent] + sub_agents

    agents_info = []
    for agent in all_agents:
        agents_info.append({
            "name": agent["name"],
            "port": agent["gateway_port"],
            "token": agent["token"]
        })

    import json
    agents_json = json.dumps(agents_info, indent=2)

    script_content = f'''#!/usr/bin/env python3
"""
Agent HTTP API 测试脚本
测试两个 Agent 的 HTTP API 是否正常工作
"""

import requests
import json
import time

# Agent 配置
AGENTS = {agents_json}

def test_agent(agent):
    """测试单个 Agent 的 HTTP API"""
    url = f"http://127.0.0.1:{{agent['port']}}/v1/chat/completions"
    headers = {{
        "Authorization": f"Bearer {{agent['token']}}",
        "Content-Type": "application/json"
    }}

    test_messages = [
        {{"role": "user", "content": "你好"}},
    ]

    for test_msg in test_messages:
        data = {{
            "model": "openclaw",
            "messages": [test_msg],
            "max_tokens": 50
        }}

        try:
            print(f"  发送: {{test_msg['content']}}")
            response = requests.post(url, headers=headers, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                reply = result['choices'][0]['message']['content']
                print(f"  ✅ 回复: {{reply[:100]}}")
                return True
            else:
                print(f"  ❌ HTTP {{response.status_code}}: {{response.text[:100]}}")
        except Exception as e:
            print(f"  ❌ 错误: {{e}}")

    return False

def test_health(agent):
    """测试健康检查端点"""
    url = f"http://127.0.0.1:{{agent['port']}}/health"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            print(f"  ✅ 健康检查通过")
            return True
        else:
            print(f"  ❌ 健康检查失败: {{response.status_code}}")
            return False
    except Exception as e:
        print(f"  ❌ 健康检查错误: {{e}}")
        return False

def main():
    print("=" * 60)
    print("OpenClaw Agent HTTP API 测试")
    print("=" * 60)

    results = {{}}

    for agent in AGENTS:
        print(f"\\n📡 测试 {{agent['name']}} (端口 {{agent['port']}})")
        print("-" * 40)

        results[agent['name']] = {{
            "health": test_health(agent),
            "chat": test_agent(agent)
        }}

    print("\\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)

    for name, result in results.items():
        status = "✅ 正常" if all(result.values()) else "⚠️ 部分失败"
        print(f"\\n{{name}}: {{status}}")
        print(f"  健康检查: {{'✅' if result['health'] else '❌'}}")
        print(f"  聊天API:  {{'✅' if result['chat'] else '❌'}}")

    print("\\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
'''

    return script_content

def build_sub_agent_cmc(capabilities: List[str], llm_config: Dict[str, Any] = None) -> List[List[Dict[str, Any]]]:
    """
    根据能力列表构建子 Agent 的 CMC（8行矩阵）
    """
    # 基础 CMC 模板（8行）
    cmc = [[] for _ in range(8)]

    # 第0行：运行时 - 始终包含 openclaw
    cmc[0] = [{"id": "agent_openclaw", "label": "openclaw", "params": {}}]

    # 第3行：工具权限
    tool_mapping = {
        "browser": {"id": "tool_browser", "label": "browser-control", "params": {}},
        "file_access": {"id": "tool_file", "label": "file-access", "params": {}},
        "shell": {"id": "tool_shell", "label": "shell-run", "params": {}},
        "canvas": {"id": "tool_canvas", "label": "canvas", "params": {}},
        "memory": {"id": "tool_memory", "label": "local-memory", "params": {}},
        "camera": {"id": "tool_camera", "label": "camera", "params": {}}
    }

    tools = []
    for cap in capabilities:
        if cap in tool_mapping:
            tools.append(tool_mapping[cap])

    if tools:
        cmc[3] = tools

    # 第4行：通信渠道
    channel_mapping = {
        "webchat": {"id": "channel_webchat", "label": "webchat", "params": {}},
        "telegram": {"id": "channel_telegram", "label": "telegram", "params": {}},
        "discord": {"id": "channel_discord", "label": "discord", "params": {}}
    }

    channels = []
    for cap in capabilities:
        if cap in channel_mapping:
            channels.append(channel_mapping[cap])

    if channels:
        cmc[4] = channels

    # 第5行：LLM 配置
    if llm_config:
        cmc[5] = [{
            "id": "llm_config",
            "label": "llm-model",
            "params": {
                "provider": llm_config.get("provider", "deepseek"),
                "model": llm_config.get("model", "deepseek-v4-pro"),
                "base_url": llm_config.get("base_url", ""),
                "compatibility": "openai-compatible"
            }
        }]

    return cmc


def generate_bridge_script(group_id: str, agents: List[Dict[str, Any]], parent_agent_id: str) -> str:
    """
    生成 Agent 通信桥接脚本（Python）
    """
    agents_info = []
    for agent in agents:
        # agent 是字典，不是对象，所以用 [] 访问而不是 .
        agents_info.append({
            "id": agent["id"],
            "name": agent["name"],
            "phc_id": agent["phc_id"],
            "gateway_port": agent["gateway_port"],
            "token": agent["token"]
        })

    # 注意：这里的 group_id 是参数传入的
    script_content = f'''#!/usr/bin/env python3

import asyncio
import json
import websockets
import os
from pathlib import Path
from typing import Dict, Any, Optional
import signal
import sys

# ==================== Configuration ====================

AGENTS = {json.dumps(agents_info, indent=2)}

PARENT_AGENT_ID = "{parent_agent_id}"

# ==================== Message Router ====================

class AgentRouter:
    def __init__(self):
        self.agents: Dict[str, websockets.WebSocketClientProtocol] = {{}}
        self.message_handlers = []

    async def connect_to_agent(self, agent_id: str, port: int, token: str):
        """连接到 Agent 的 Gateway"""
        uri = f"ws://127.0.0.1:{{port}}/ws?token={{token}}"
        try:
            ws = await websockets.connect(uri)
            self.agents[agent_id] = ws
            print(f"[OK] Connected to {{agent_id}} at {{uri}}")
            return ws
        except Exception as e:
            print(f"[ERROR] Failed to connect to {{agent_id}}: {{e}}")
            return None

    async def send_message(self, from_agent: str, to_agent: str, content: str):
        """发送消息到指定 Agent"""
        if to_agent not in self.agents:
            print(f"[ERROR] Agent {{to_agent}} not connected")
            return False

        message = {{
            "type": "chat",
            "from": from_agent,
            "content": content,
            "timestamp": __import__('datetime').datetime.utcnow().isoformat() + "Z"
        }}

        try:
            await self.agents[to_agent].send(json.dumps(message))
            print(f"[SENT] {{from_agent}} -> {{to_agent}}: {{content[:50]}}...")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send: {{e}}")
            return False

    async def broadcast(self, from_agent: str, content: str, exclude: str = None):
        """广播消息到所有连接的 Agent"""
        tasks = []
        for agent_id, ws in self.agents.items():
            if agent_id != exclude:
                tasks.append(self.send_message(from_agent, agent_id, content))
        await asyncio.gather(*tasks)

    async def listen_to_agent(self, agent_id: str, ws: websockets.WebSocketClientProtocol):
        """监听来自 Agent 的消息"""
        try:
            async for message in ws:
                data = json.loads(message)
                await self.handle_incoming_message(agent_id, data)
        except websockets.exceptions.ConnectionClosed:
            print(f"[WARN] Connection to {{agent_id}} closed")
        except Exception as e:
            print(f"[ERROR] Error listening to {{agent_id}}: {{e}}")

    async def handle_incoming_message(self, from_agent: str, message: Dict[str, Any]):
        """处理收到的消息"""
        msg_type = message.get("type", "chat")

        if msg_type == "chat":
            content = message.get("content", "")
            target = message.get("to", None)

            if target and target in self.agents:
                await self.send_message(from_agent, target, content)
            else:
                # 转发给父 Agent 处理
                await self.send_message(from_agent, PARENT_AGENT_ID, content)

        # 调用自定义处理器
        for handler in self.message_handlers:
            await handler(from_agent, message)

    def add_handler(self, handler):
        self.message_handlers.append(handler)

    async def run(self):
        """运行路由器"""
        print("=" * 50)
        print(f"Agent Communication Bridge for {group_id}")
        print("=" * 50)
        print()

        # 连接所有 Agent
        connect_tasks = []
        for agent in AGENTS:
            connect_tasks.append(
                self.connect_to_agent(agent["id"], agent["gateway_port"], agent["token"])
            )

        ws_list = await asyncio.gather(*connect_tasks)

        # 启动监听任务
        listen_tasks = []
        for agent, ws in zip(AGENTS, ws_list):
            if ws:
                listen_tasks.append(self.listen_to_agent(agent["id"], ws))

        print(f"\\n[READY] Router is running with {{len(listen_tasks)}} active agents")
        print("Press Ctrl+C to stop\\n")

        await asyncio.gather(*listen_tasks)

async def main():
    router = AgentRouter()

    # 添加自定义消息处理器示例
    async def log_handler(from_agent: str, message: Dict[str, Any]):
        print(f"[RECV] From {{from_agent}}: {{json.dumps(message, ensure_ascii=False)[:100]}}")

    router.add_handler(log_handler)

    await router.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\\n[STOP] Bridge stopped")
        sys.exit(0)
'''

    return script_content


# ==================== 获取 Agent 组信息 ====================

@app.get("/agent/groups/{parent_agent_id}")
async def get_agent_groups(parent_agent_id: str) -> Dict[str, Any]:
    """获取指定父 Agent 的所有 Agent 组"""
    groups = list_agent_groups(parent_agent_id)
    return {
        "success": True,
        "groups": [g.model_dump() for g in groups],
        "count": len(groups)
    }


@app.get("/agent/group/{group_id}")
async def get_agent_group(group_id: str) -> Dict[str, Any]:
    """获取 Agent 组详情"""
    group = load_agent_group(group_id)
    if not group:
        return {"success": False, "error": "Group not found"}
    return {"success": True, "group": group.model_dump()}


# ==================== 子 Agent 管理 ====================

@app.post("/agent/sub/{sub_agent_id}/deploy")
async def deploy_sub_agent(sub_agent_id: str) -> Dict[str, Any]:
    """部署子 Agent（调用部署脚本）"""
    # 查找子 Agent 信息
    for group in list_agent_groups():
        for sub in group.sub_agents:
            if sub.id == sub_agent_id:
                # 更新状态
                sub.status = "deployed"
                save_agent_group(group)
                return {
                    "success": True,
                    "sub_agent": sub.model_dump(),
                    "deploy_command": f"cd {sub.deploy_path} && ./deploy_openclaw_personal.bat"
                }

    return {"success": False, "error": f"Sub agent {sub_agent_id} not found"}


@app.post("/agent/sub/{sub_agent_id}/start")
async def start_sub_agent(sub_agent_id: str) -> Dict[str, Any]:
    """启动子 Agent"""
    for group in list_agent_groups():
        for sub in group.sub_agents:
            if sub.id == sub_agent_id:
                sub.status = "running"
                save_agent_group(group)
                return {
                    "success": True,
                    "sub_agent": sub.model_dump(),
                    "launch_command": f"cd {sub.deploy_path} && ./launch_openclaw_personal.bat"
                }

    return {"success": False, "error": f"Sub agent {sub_agent_id} not found"}


@app.delete("/agent/sub/{sub_agent_id}")
async def delete_sub_agent(sub_agent_id: str) -> Dict[str, Any]:
    """删除子 Agent"""
    from fastapi import HTTPException
    raise HTTPException(status_code=409, detail="请在新工作台申请删除，经 TP 审批后执行。旧接口不再直接删除文件。")
    for group in list_agent_groups():
        for i, sub in enumerate(group.sub_agents):
            if sub.id == sub_agent_id:
                # 删除文件
                import shutil
                if sub.deploy_path and Path(sub.deploy_path).exists():
                    shutil.rmtree(sub.deploy_path, ignore_errors=True)

                group.sub_agents.pop(i)
                save_agent_group(group)
                return {"success": True, "message": f"Sub agent {sub_agent_id} deleted"}

    return {"success": False, "error": f"Sub agent {sub_agent_id} not found"}


# ==================== 消息发送接口 ====================

@app.post("/agent/message/send")
async def send_agent_message(message: AgentMessage) -> Dict[str, Any]:
    """发送 Agent 间消息（通过 API）"""
    # 这里可以通过 WebSocket 转发，或者写入消息队列
    return {
        "success": True,
        "message": "Message queued for delivery",
        "message_id": uuid.uuid4().hex
    }

@app.post("/user/check_phc_application")
def user_check_phc_application(req: RequestPHCStatus) -> Dict[str, Any]:
    try:
        return request_phc_application_status(req.base_url, req.request_id)
    except httpx.HTTPError as e:
        from fastapi import HTTPException
        status = getattr(getattr(e, "response", None), "status_code", 502)
        detail = None
        if getattr(e, "response", None) is not None:
            try:
                detail = e.response.json().get("detail")
            except Exception:
                pass
        raise HTTPException(status_code=status, detail=detail or "phc_application_status_failed")


# ==================== 鉴权守卫（放在最后，确保覆盖全部路由）====================
# 保护范围：/user 控制台页面及其全部业务接口
# 放行范围：
#   /user/login         登录页本身
#   /user/static/*      智契化身页面及静态资源
#   /user/api/*         登录 / 登出 / 身份查询
#
# 之所以敢把业务接口一并保护：页面与接口同源，浏览器会自动携带 Cookie，
# 不会出现「登录了却调不通接口」的情况。若演示现场需要临时放开，
# 设置环境变量 ENABLE_AUTH=0 重启即可，无需改代码。
USER_PUBLIC_PATHS = [
    "/user/login",
    "/user/static/*",
    "/user/api/*",
]

auth.install_auth(
    app,
    role="user",
    cookie_name=auth.COOKIE_USER,
    login_path="/user/login",
    public_paths=USER_PUBLIC_PATHS,
)

# 静态资源缓存策略。必须放在 install_auth 之后（后添加的中间件在外层）。
# 更新页面脚本后必须重新获取资源，避免浏览器继续执行旧版启动流程。
web_assets.install_static_cache(app, ["/user/static/"])
