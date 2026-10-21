import os
import sys
os.environ["ALLOW_TEST_USERS"] = "1"

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from trust_provider.issue_phc import router as tp_router
from app import auth_common as auth
from app import web_assets

app = FastAPI(title="TP Service")
app.include_router(tp_router, prefix="/v1")

TP_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_tp")

app.mount(
    "/tp/static",
    StaticFiles(directory=TP_WEB_DIR),
    name="tp_static",
)


@app.get("/tp")
def ui() -> Response:
    # 交给 web_assets 渲染：替换资源版本占位符 + 禁止 HTML 自身被缓存。
    # 少了这一步，改完 JS 刷新页面会拿到旧的脚本，表现为「按钮点了没反应」。
    return web_assets.render_html(os.path.join(TP_WEB_DIR, "index.html"), TP_WEB_DIR)


# ---------------------------------------------------------------------------
# 鉴权：登录页 + 认证接口 + 访问守卫
# ---------------------------------------------------------------------------
# 设计原则：TP 的「管理类」接口必须登录（否则任何人都能给自己签发 PHC、
# 或拉取含个人信息的申请列表），而「服务间调用」必须放行 ——
# User App 会以服务身份回调这些端点，拦掉它们整条业务链就断了。

auth.render_login_page(
    app,
    page_path="/tp/login",
    html_file=os.path.join(TP_WEB_DIR, "login.html"),
    static_dir=TP_WEB_DIR,
)

auth.register_auth_routes(
    app,
    role="tp",
    cookie_name=auth.COOKIE_TP,
    api_prefix="/v1/tp",
)

TP_PUBLIC_PATHS = [
    # 登录页与静态资源
    "/tp/login",
    "/tp/static/*",
    # 认证接口自身
    "/v1/tp/login",
    "/v1/tp/logout",
    "/v1/tp/me",
    # 公钥：本就设计为公开，User App 申请凭证前需拉取
    "/v1/tp/public_keys",
    # 以下为「服务间调用」：User App -> TP，必须放行
    "/v1/tp/issue_phc",
    "/v1/tp/issue_phc_secure",
    "/v1/tp/verify_phc",
    "/v1/tp/trace",
    "/v1/tp/recover_phc",
    "/v1/tp/reissue_updated_phc",
]


def _tp_extra_allow(path: str) -> bool:
    """申请状态轮询对 User App 开放，但列表 / 详情 / 审批保持保护。

    这几条都挂在 /v1/tp/applications 前缀下，通配符无法区分，
    所以用后缀精确判定。
    """
    return path.startswith("/v1/tp/applications/") and path.endswith("/status")


auth.install_auth(
    app,
    role="tp",
    cookie_name=auth.COOKIE_TP,
    login_path="/tp/login",
    public_paths=TP_PUBLIC_PATHS,
    extra_allow=_tp_extra_allow,
)

# 静态资源缓存策略。必须放在 install_auth 之后：Starlette 后添加的中间件
# 在外层，放外层才能改写内层（含鉴权短路）产生的响应。
web_assets.install_static_cache(app, ["/tp/static/"])


from app.deletion_review import tp_router as deletion_router
app.include_router(deletion_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
