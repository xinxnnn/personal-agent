import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from agent_provider.ap import router as ap_router
from app import auth_common as auth
from app import web_assets

app = FastAPI(title="AP Service")
app.include_router(ap_router, prefix="/v1")

WEB_AP_DIR = os.path.join(os.getcwd(), "app", "web_ap")

app.mount(
    "/ap/static",
    StaticFiles(directory=WEB_AP_DIR),
    name="ap_static",
)


@app.get("/ap")
def ui() -> Response:
    # 交给 web_assets 渲染：替换资源版本占位符 + 禁止 HTML 自身被缓存。
    # 少了这一步，改完 JS 刷新页面会拿到旧的脚本，表现为「按钮点了没反应」。
    return web_assets.render_html(os.path.join(WEB_AP_DIR, "index.html"), WEB_AP_DIR)


# ---------------------------------------------------------------------------
# 鉴权：登录页 + 认证接口 + 访问守卫
# ---------------------------------------------------------------------------
# AP 需要保护的是「仓库运维」类接口（/v1/ap/db 的查看与删除、/v1/ap/status
# 会暴露本地路径），放行的是「服务间调用」（User App 申请 PA / 能力矩阵 /
# 更新配置）—— 拦掉后者会直接切断 User 端的智能体创建流程。

auth.render_login_page(
    app,
    page_path="/ap/login",
    html_file=os.path.join(WEB_AP_DIR, "login.html"),
    static_dir=WEB_AP_DIR,
)

auth.register_auth_routes(
    app,
    role="ap",
    cookie_name=auth.COOKIE_AP,
    api_prefix="/v1/ap",
)

AP_PUBLIC_PATHS = [
    # 登录页与静态资源
    "/ap/login",
    "/ap/static/*",
    # 认证接口自身
    "/v1/ap/login",
    "/v1/ap/logout",
    "/v1/ap/me",
    # 公钥与只读能力矩阵
    "/v1/ap/public_keys",
    "/v1/ap/capabilities",
    # 以下为「服务间调用」：User App -> AP，必须放行
    "/v1/ap/request_pa",
    "/v1/ap/recover_pa",
    "/v1/ap/cmm_init",
    "/v1/ap/cmm_submit",
    "/v1/ap/update_init",
    "/v1/ap/update_submit",
]
# 保持保护（不在白名单中）：
#   GET    /v1/ap/status        -> 暴露 db_root 本地路径与记录数
#   GET    /v1/ap/db            -> 智能体仓库清单
#   GET    /v1/ap/db/{hid}      -> 单条记录详情
#   DELETE /v1/ap/db/{hid}      -> 删除记录

auth.install_auth(
    app,
    role="ap",
    cookie_name=auth.COOKIE_AP,
    login_path="/ap/login",
    public_paths=AP_PUBLIC_PATHS,
)

# 静态资源缓存策略。必须放在 install_auth 之后（后添加的中间件在外层）。
web_assets.install_static_cache(app, ["/ap/static/"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002)
