"""三端共用的轻量会话鉴权模块。

设计约束（面向比赛演示环境）：

1. **零外部依赖** —— 只用 Python 标准库（hmac / hashlib / secrets / base64）。
   比赛环境不该再装 PyJWT、passlib、bcrypt 之类的包，多一个依赖多一个坑。

2. **可一键降级** —— 环境变量 ``ENABLE_AUTH=0`` 时中间件完全放行。
   演示现场万一出问题，不用改代码就能恢复原状。

3. **精确白名单** —— User App 会以「服务」身份回调 TP/AP 的接口
   （issue_phc_secure、request_pa、public_keys ...）。这些必须放行，
   否则整条业务链会断。这是本模块最关键的设计约束。

4. **不侵入业务逻辑** —— 只通过 HTTP 中间件在路由之外拦截，
   现有端点函数一行都不改。

会话令牌格式：``base64url(payload) . base64url(HMAC-SHA256(payload))``
无状态、可自校验，服务重启后已签发的令牌依然有效（只要 AUTH_SECRET 不变）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Callable, Dict, Optional, Sequence

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

log = logging.getLogger("auth")


class LoginPayload(BaseModel):
    """登录请求体。

    **必须定义在模块级。** 若定义在函数内部（闭包作用域），FastAPI 的
    ``get_type_hints()`` 会在模块全局命名空间里解析签名注解、找不到该类，
    从而把参数退化成 query 参数，导致请求体永远校验失败并返回 422。
    这是本项目实际踩过的坑。
    """

    username: str = ""
    password: str = ""

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

COOKIE_USER = "pa_session_user"
COOKIE_TP = "pa_session_tp"
COOKIE_AP = "pa_session_ap"

# 默认 8 小时。演示足够长，又不会永久有效。
DEFAULT_TTL = int(os.getenv("AUTH_TTL_SECONDS") or 8 * 3600)


def auth_enabled() -> bool:
    """鉴权总开关。默认开启；设为 0 / false / no / off 即完全放行。"""
    raw = (os.getenv("ENABLE_AUTH") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


def _secret() -> bytes:
    """签名密钥。演示环境用固定默认值，保证服务重启后 Cookie 不失效。"""
    return (os.getenv("AUTH_SECRET") or "pa-identity-demo-secret-2026").encode("utf-8")


# --------------------------------------------------------------------------
# 预置演示账号
# --------------------------------------------------------------------------
# 密码统一为 pa@2026，以 PBKDF2-HMAC-SHA256 哈希形式存储（不落明文）。
# 可用环境变量覆盖：AUTH_PASSWORD_USER / AUTH_PASSWORD_TP / AUTH_PASSWORD_AP
#
# 之所以预置而非对接数据库：演示环境里 MySQL 可能没起来，
# 而登录是进入系统的第一步 —— 这一步绝不能依赖外部服务。

ACCOUNTS: Dict[str, Dict[str, Dict[str, str]]] = {
    "user": {
        "user": {
            "hash": "pbkdf2_sha256$120000$1c8d19f6e1d682f447e9c9ef15bb0452$"
                    "d2a4ddac09280742577c95e3c9ca144d5d2160f5a28b56060770635b74a737b2",
            "display": "个人用户",
        },
    },
    "tp": {
        "tpadmin": {
            "hash": "pbkdf2_sha256$120000$ef480b31545e972953edceefeed3f032$"
                    "9c598a0d1ca164b86d00737e5fa34d65ddaa2c6a68d5b1540feb0b05521193b7",
            "display": "信任提供方管理员",
        },
    },
    "ap": {
        "apadmin": {
            "hash": "pbkdf2_sha256$120000$b1a213e4e72d5ffb00b86419e9be20b3$"
                    "cbc2177519dffe64b1d5c7d01f079a5fa0cb5feee70203e3e140ca441838497d",
            "display": "智能体提供方管理员",
        },
    },
}

ACCOUNTS['user']['avatar_demo'] = {
    'hash': 'pbkdf2_sha256$120000$bdcf3891ca01d20ab94bfe556789dec3$83f6dd0474dbe3eb9a0e1fbe1850f357a2209ca883182e9605d8827c581a6625',
    'display': '化身体验用户',
}

# 各端登录页上展示的演示账号（用户名，明文密码仅用于提示）
DEMO_HINT: Dict[str, Dict[str, str]] = {
    "user": {"username": "user", "password": "pa@2026"},
    "tp": {"username": "tpadmin", "password": "pa@2026"},
    "ap": {"username": "apadmin", "password": "pa@2026"},
}

# 环境变量覆盖用的键名
_ENV_PWD_KEY = {"user": "AUTH_PASSWORD_USER", "tp": "AUTH_PASSWORD_TP", "ap": "AUTH_PASSWORD_AP"}


# --------------------------------------------------------------------------
# 密码哈希
# --------------------------------------------------------------------------

def hash_password(password: str, salt: Optional[str] = None, iterations: int = 120_000) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """常量时间比对，避免时序侧信道。"""
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def authenticate(role: str, username: str, password: str) -> Optional[Dict[str, Any]]:
    """校验凭据。成功返回会话信息，失败返回 None。"""
    key = (username or "").strip().lower()
    table = ACCOUNTS.get(role) or {}
    acct = table.get(key)
    if not acct:
        # 仍然做一次哈希运算，避免「用户不存在」响应明显更快而泄露账号是否存在
        verify_password(password or "", ACCOUNTS["user"]["user"]["hash"])
        return None

    env_key = _ENV_PWD_KEY.get(role)
    env_pwd = os.getenv(env_key) if env_key else None
    if env_pwd:
        ok = hmac.compare_digest(password or "", env_pwd)
    else:
        ok = verify_password(password or "", acct["hash"])

    if not ok:
        return None

    return {
        "username": key,
        "role": role,
        "display": acct.get("display") or key,
        "login_at": int(time.time()),
    }


# --------------------------------------------------------------------------
# 会话令牌
# --------------------------------------------------------------------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(session: Dict[str, Any], ttl: int = DEFAULT_TTL) -> str:
    payload = {
        "u": session.get("username"),
        "r": session.get("role"),
        "d": session.get("display"),
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
        "n": secrets.token_hex(8),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """只做签名与有效期校验（不看角色、不查吊销）。

    拆出来是为了让 :func:`revoke_token` 能在解出 nonce 的同时不产生递归。
    """
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expect = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception:
        return None

    if int(payload.get("exp") or 0) < int(time.time()):
        return None
    return payload


def verify_token(token: Optional[str], role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """校验令牌：签名、有效期、角色归属、吊销状态。"""
    payload = decode_token(token)
    if payload is None:
        return None
    if role and payload.get("r") != role:
        # 跨端令牌不通用：User 的会话不能拿进 TP 控制台
        return None
    if is_revoked(payload.get("n")):
        # 已登出的令牌即便签名有效也拒绝
        return None
    return payload


# --------------------------------------------------------------------------
# 令牌吊销
# --------------------------------------------------------------------------
# Cookie 由浏览器负责删除，但令牌本身是无状态的 —— 如果它此前被复制走，
# 在 8 小时有效期内依然可用。用内存黑名单按 nonce 吊销，登出即时生效。
#
# 已知局限：黑名单存在进程内存里，重启即清空；多 worker 之间也不共享。
# 本系统的演示形态是单进程 uvicorn，够用。若将来上多进程，需要换成
# Redis 之类的共享存储 —— 这是无状态令牌做吊销的固有代价。

_REVOKED: Dict[str, float] = {}
_REVOKED_LOCK = threading.Lock()


def _prune_revoked(now: float) -> None:
    """清掉已自然过期的条目，避免黑名单无限增长。调用方需持锁。"""
    for nonce, exp in list(_REVOKED.items()):
        if exp < now:
            _REVOKED.pop(nonce, None)


def revoke_token(token: Optional[str]) -> bool:
    """把令牌加入吊销集合。返回是否成功识别出令牌。"""
    payload = decode_token(token)
    if not payload:
        return False
    nonce = str(payload.get("n") or "")
    if not nonce:
        return False
    now = time.time()
    with _REVOKED_LOCK:
        _prune_revoked(now)
        _REVOKED[nonce] = float(payload.get("exp") or now)
    return True


def is_revoked(nonce: Any) -> bool:
    """判断 nonce 是否已被吊销。已过期的条目顺手清理。"""
    if not nonce:
        return False
    key = str(nonce)
    now = time.time()
    with _REVOKED_LOCK:
        exp = _REVOKED.get(key)
        if exp is None:
            return False
        if exp < now:
            _REVOKED.pop(key, None)
            return False
        return True


def public_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """把内部会话/令牌载荷映射成前端可直接用的规范字段。

    令牌为了紧凑用 ``u`` / ``r`` / ``d`` 存放用户名、角色、显示名，但前端
    读的是 ``username`` / ``role`` / ``display``。这里统一补齐规范名，
    同时保留原字段以兼容既有读取方 —— 前端拿不到名字只会显示 ``—``，
    排查起来很费时间，不如在出口处一次性对齐。
    """
    out: Dict[str, Any] = dict(session or {})
    out["username"] = out.get("username") or out.get("u") or ""
    out["role"] = out.get("role") or out.get("r") or ""
    out["display"] = out.get("display") or out.get("d") or out["username"]
    return out


def set_session_cookie(response: Response, cookie_name: str, session: Dict[str, Any]) -> None:
    token = create_token(session)
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=DEFAULT_TTL,
        httponly=True,     # JS 读不到，防 XSS 窃取
        samesite="lax",    # 防 CSRF
        path="/",
    )


def clear_session_cookie(response: Response, cookie_name: str) -> None:
    response.delete_cookie(key=cookie_name, path="/")


def current_session(request: Request, cookie_name: str, role: str) -> Optional[Dict[str, Any]]:
    """从请求里取出已登录会话，未登录返回 None。"""
    return verify_token(request.cookies.get(cookie_name), role)


# --------------------------------------------------------------------------
# 路径白名单
# --------------------------------------------------------------------------

def match_path(path: str, patterns: Sequence[str]) -> bool:
    """支持精确匹配与 ``/prefix/*`` 通配。"""
    for p in patterns:
        if p.endswith("/*"):
            base = p[:-2]
            if path == base or path.startswith(base + "/"):
                return True
        elif path == p:
            return True
    return False


# --------------------------------------------------------------------------
# 中间件
# --------------------------------------------------------------------------

def install_auth(
    app,
    *,
    role: str,
    cookie_name: str,
    login_path: str,
    public_paths: Sequence[str],
    extra_allow: Optional[Callable[[str], bool]] = None,
) -> None:
    """给 FastAPI 应用装上鉴权守卫。

    参数
    ----
    role
        本端角色（user / tp / ap），用于校验令牌归属。
    cookie_name
        本端专用 Cookie 名。**必须三端互不相同** —— Cookie 按 host 隔离、
        不按端口隔离，8000 与 8001 同域会互相覆盖。
    login_path
        未登录访问页面时重定向的目标，如 ``/tp/login``。
    public_paths
        白名单，支持 ``/x/*`` 通配。
    extra_allow
        额外放行判定，用于无法用通配表达的规则
        （如「放行 applications/{id}/status，但保护 applications 列表」）。
    """

    @app.middleware("http")
    async def _auth_guard(request: Request, call_next):
        path = request.url.path

        if not auth_enabled():
            return await call_next(request)
        if match_path(path, public_paths):
            return await call_next(request)
        if extra_allow and extra_allow(path):
            return await call_next(request)

        sess = verify_token(request.cookies.get(cookie_name), role)
        if sess:
            request.state.session = sess
            return await call_next(request)

        # 未通过 —— 页面请求跳登录页，接口请求返回 401 JSON
        if path.startswith("/v1/") or path.startswith("/api/"):
            return JSONResponse(
                {"success": False, "detail": "unauthorized", "message": "登录状态已失效，请重新登录"},
                status_code=401,
            )
        return RedirectResponse(url=f"{login_path}?next={path}", status_code=302)


def render_login_page(app, *, page_path: str, html_file: str, static_dir: str = "") -> None:
    """把登录页注册成路由（不走静态目录，URL 更干净）。

    ``static_dir`` 传入同目录的静态资源目录，用于替换页面里的资源版本
    占位符；留空则页面里的 ``?v=`` 会保持原样（不推荐）。
    """
    from app import web_assets  # 局部导入，避免模块级循环依赖

    @app.get(page_path, include_in_schema=False)
    def _login_page() -> Response:
        return web_assets.render_html(html_file, static_dir)


def register_auth_routes(app, *, role: str, cookie_name: str, api_prefix: str) -> None:
    """注册登录 / 登出 / 身份查询三个接口。

    api_prefix 形如 ``/v1/tp``，最终端点为 ``{api_prefix}/login`` 等。
    """

    @app.post(f"{api_prefix}/login", include_in_schema=False)
    def _login(payload: LoginPayload, response: Response) -> Dict[str, Any]:
        sess = authenticate(role, payload.username, payload.password)
        if not sess:
            log.warning("login failed role=%s user=%r", role, payload.username)
            raise HTTPException(status_code=401, detail="invalid_credentials")
        set_session_cookie(response, cookie_name, sess)
        log.info("login ok role=%s user=%s", role, sess["username"])
        return {"success": True, "user": public_session(sess)}

    @app.post(f"{api_prefix}/logout", include_in_schema=False)
    def _logout(request: Request, response: Response) -> Dict[str, Any]:
        # 先吊销令牌再清 Cookie：只清 Cookie 的话，被复制走的令牌仍能用满有效期
        token = request.cookies.get(cookie_name)
        revoked = revoke_token(token)
        clear_session_cookie(response, cookie_name)
        log.info("logout role=%s revoked=%s", role, revoked)
        return {"success": True, "revoked": revoked}

    @app.get(f"{api_prefix}/me", include_in_schema=False)
    def _me(request: Request) -> Dict[str, Any]:
        sess = current_session(request, cookie_name, role)
        if not sess:
            raise HTTPException(status_code=401, detail="unauthorized")
        return {"success": True, "user": public_session(sess)}
