"""三端 Web 层的静态资源版本与缓存策略。

**要解决的问题**（本项目实际踩过的坑）
------------------------------------------------
控制台的 JS / CSS 通过固定 URL 提供，浏览器会用「启发式缓存」把它们长期
留在本地。改完代码刷新页面时会出现一种很迷惑的现象：

    HTML 更新了（页面上多出了新按钮），但 JS 还是旧版（事件没绑定），
    所以点按钮完全没反应 —— 看起来像功能坏了，实际是缓存。

**方案**（三层配合，缺一不可）
------------------------------------------------
1. HTML 引用静态资源时带 ``?v=<mtime>`` 版本号。文件一改，URL 就变，
   **从根本上绕过缓存**，不依赖浏览器是否守规矩。
2. HTML 响应本身 ``no-store``，保证浏览器总能拿到最新的版本号。
3. 带版本号的静态资源走长缓存（一年 + immutable）—— 既然 URL 变化即
   内容变化，就没有必要再回源验证，性能最好。

版本号取静态目录内最新的 mtime，因此**任何**资源改动都会自动 bump，
不需要手工维护构建号。
"""

from __future__ import annotations

import os
from typing import Sequence

from fastapi import Request
from fastapi.responses import Response

#: HTML 里引用静态资源时写的占位符，由 :func:`render_html` 替换成真实版本号
ASSET_PLACEHOLDER = "__ASSET_V__"

#: 带版本号资源的缓存时长（一年）
_LONG_CACHE = "public, max-age=31536000, immutable"
#: 无版本号时退化为「每次回源验证」，避免陈旧
_SHORT_CACHE = "no-cache"


def asset_version(static_dir: str) -> str:
    """取静态目录内最新的修改时间作为版本号。

    任何文件改动都会让版本号变化，从而让 HTML 里的 ``?v=`` 查询串变化。
    目录不可读时返回 ``0``，退化为不缓存策略。
    """
    newest = 0
    try:
        for name in os.listdir(static_dir):
            path = os.path.join(static_dir, name)
            if os.path.isfile(path):
                newest = max(newest, int(os.path.getmtime(path)))
    except OSError:
        pass
    return str(newest)


def render_html(page_file: str, static_dir: str = "") -> Response:
    """读取 HTML 页面，替换资源版本占位符，并禁止 HTML 自身被缓存。"""
    try:
        with open(page_file, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception as exc:  # pragma: no cover - 仅在文件缺失时触发
        return Response(
            content=f"<h1>Missing page</h1><pre>{exc}</pre>",
            media_type="text/html",
            status_code=500,
        )

    if static_dir and ASSET_PLACEHOLDER in html:
        html = html.replace(ASSET_PLACEHOLDER, asset_version(static_dir))

    return Response(
        content=html,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


def install_static_cache(app, prefixes: Sequence[str]) -> None:
    """给静态资源目录按 URL 是否带版本号分配缓存策略。

    注意注册顺序：本函数应在 ``install_auth`` **之后**调用。Starlette 的
    中间件是「后添加的在外层」，放外层才能改写内层（含鉴权短路）产生的响应。

    参数
    ----
    prefixes
        静态资源路径前缀，如 ``["/tp/static/", "/ap/static/"]``。
    """

    @app.middleware("http")
    async def _static_cache(request: Request, call_next):
        response = await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in prefixes):
            # URL 带 v= 说明是版本化引用，内容变了 URL 必然不同，可长缓存；
            # 否则（手工拼的地址）一律回源验证，绝不返回陈旧副本。
            if "v" in request.query_params:
                response.headers["Cache-Control"] = _LONG_CACHE
            else:
                response.headers["Cache-Control"] = _SHORT_CACHE

        return response
