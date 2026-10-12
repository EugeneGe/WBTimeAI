"""API 同源托管前端静态产物（发行形态 A：社区单容器打开即完整 UI）。

本模块把 Vite 构建产物（``apps/web/dist``）交由 API **同源**托管：

- 以 :class:`starlette.staticfiles.StaticFiles`（``html=True``）提供静态文件与
  ``index.html``；
- 对**未命中的前端深链**（如 ``/projects/123``）回退到 ``index.html``，使前端
  SPA 路由可直接刷新；
- 🔴 **不遮蔽**既有框架 / 业务路由：仅在「所有路由均未命中」的兜底分支
  （``app.router.default``）接管，因此 ``/api`` / ``/health`` / ``/docs`` /
  ``/openapi.json`` / ``/metrics`` 的既有命中与 **404 / 405** 语义**完全不变**；
- 🔴 **仅当 dist 存在时启用**（缺省 / 开发 / 测试无产物时零影响）；目录经配置项
  （``ASTRA_WEB_DIST``）或**包相对路径**解析，**不硬编码绝对路径**。

为什么不是直接 ``app.mount("/", StaticFiles(...))``：根挂载对**任意方法**做
``Match.FULL``，会抢在路由器的 405 判定之前接管请求，从而把「未注册路径的非 GET
请求」（既有语义 404）变成 405、并破坏尾斜杠重定向。改在 ``router.default``（仅在
无任何路由命中时触发）接管，可在**提供 SPA 回退**的同时**逐字保留**既有语义。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

if TYPE_CHECKING:
    from astra_config import Settings
    from fastapi import FastAPI

__all__ = ["SPAStaticFiles", "install_web_static", "resolve_web_dist"]

#: SPA 回退入口文件名。
_INDEX_FILE = "index.html"

#: 保留前缀：这些**路径段**的既有语义（文档 / 404 / 405）**不得**被 SPA 回退接管。
#: 命中其一即交由原有 404 兜底处理（避免把 API 未知路径渲染成前端页面）。
_RESERVED_PREFIXES: frozenset[str] = frozenset(
    {"api", "health", "docs", "redoc", "openapi.json", "metrics"}
)


def _package_relative_web_dist() -> Path:
    """按**包相对路径**解析前端产物目录。

    本模块位于 ``<root>/apps/api/src/astra_api/web_static.py``，据此以 ``parents``
    相对定位到 ``<root>/apps/web/dist``；仓库根与容器内 ``/app`` 布局一致，故**无需**
    硬编码任何绝对路径。

    Returns:
        期望的前端产物目录（**不保证存在**）。
    """
    # parents[0]=astra_api, [1]=src, [2]=api, [3]=apps
    return Path(__file__).resolve().parents[3] / "web" / "dist"


def resolve_web_dist(settings: Settings) -> Path | None:
    """解析并校验前端产物目录。

    优先级：配置项 ``settings.web_dist``（非空）→ 包相对路径 ``apps/web/dist``。
    仅当解析到的目录**含 ``index.html``** 时返回，否则返回 ``None``（未启用）。

    Args:
        settings: 平台配置（读取 ``web_dist`` / ``web_static_enabled``）。

    Returns:
        可用的前端产物目录；开关关闭或目录 / 入口缺失时返回 ``None``。
    """
    if not getattr(settings, "web_static_enabled", False):
        return None
    configured = str(getattr(settings, "web_dist", "") or "").strip()
    directory = Path(configured).expanduser() if configured else _package_relative_web_dist()
    if (directory / _INDEX_FILE).is_file():
        return directory
    return None


def _looks_like_asset(path: str) -> bool:
    """判定请求路径是否指向**具体静态资源**（末段含扩展名，如 ``app.js``）。

    Args:
        path: 静态解析后的相对路径（如 ``assets/app.js``）。

    Returns:
        末段含 ``.`` 视为资源；否则视为前端导航路由。
    """
    last_segment = path.rstrip("/").rsplit("/", 1)[-1]
    return "." in last_segment


def _is_reserved(path: str) -> bool:
    """判定路径是否落在保留前缀下（``/api`` / ``/health`` / ``/docs`` …）。

    Args:
        path: ASGI 请求路径（以 ``/`` 起始）。

    Returns:
        首段命中 :data:`_RESERVED_PREFIXES` 返回 ``True``。
    """
    first_segment = path.lstrip("/").split("/", 1)[0]
    return first_segment in _RESERVED_PREFIXES


class SPAStaticFiles(StaticFiles):
    """``StaticFiles(html=True)`` + SPA 深链回退。

    在基类基础上，把**未命中的前端导航路径**（无扩展名的深链，如
    ``/projects/123``）回退到 ``index.html``；对**带扩展名的缺失资源**
    （如 ``/assets/missing.js``）保留 404，避免把资源缺失误报为页面命中。
    """

    def __init__(self, *, directory: Path) -> None:
        """构造 SPA 静态应用（固定 ``html=True``，目录由调用方校验存在）。

        Args:
            directory: 已校验存在的产物目录。
        """
        super().__init__(directory=str(directory), html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        """返回静态响应；未命中的导航路径回退到 ``index.html``。

        Args:
            path: 静态解析后的相对路径。
            scope: ASGI 请求作用域。

        Returns:
            命中的静态响应，或导航深链回退的 ``index.html`` 响应。

        Raises:
            HTTPException: 带扩展名的缺失资源（404）或非 GET/HEAD（405）等，
                交由上层统一异常处理映射为响应壳。
        """
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and not _looks_like_asset(path):
                return await super().get_response(_INDEX_FILE, scope)
            raise


def _should_serve_spa(scope: Scope) -> bool:
    """判定是否交由 SPA 静态托管处理。

    仅接管**未命中**的 HTTP ``GET`` / ``HEAD`` 且**非保留前缀**的请求（即前端
    导航路由）；其余一律交回原有 404 兜底，保持既有语义。

    Args:
        scope: ASGI 请求作用域。

    Returns:
        应由 SPA 托管处理返回 ``True``。
    """
    if scope.get("type") != "http":
        return False
    if scope.get("method") not in ("GET", "HEAD"):
        return False
    return not _is_reserved(str(scope.get("path", "")))


def install_web_static(app: FastAPI, directory: Path) -> bool:
    """安装前端静态托管（``StaticFiles(html=True)`` + SPA 回退）。

    通过**包装** ``app.router.default``（即「所有路由均未命中」的兜底分支）实现：
    仅在无任何路由命中时，才尝试静态文件 / SPA 回退。因此**不改变**既有路由的命中
    顺序、尾斜杠重定向与 404 / 405 语义（``/api`` 未知路径 → 404、``/health`` 非
    ``GET`` → 405 等一律保持）。

    Args:
        app: 目标 FastAPI 应用。
        directory: 已校验存在的产物目录（见 :func:`resolve_web_dist`）。

    Returns:
        安装成功返回 ``True``。
    """
    static_app = SPAStaticFiles(directory=directory)
    original_default = app.router.default

    async def spa_default(scope: Scope, receive: Receive, send: Send) -> None:
        """兜底分支：命中的前端请求交 SPA 托管，其余交回原兜底。"""
        if _should_serve_spa(scope):
            await static_app(scope, receive, send)
        else:
            await original_default(scope, receive, send)

    app.router.default = spa_default
    return True
