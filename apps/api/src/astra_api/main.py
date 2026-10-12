"""FastAPI 应用入口：装配 lifespan / 路由 / 异常处理 / CORS。

🔴 不判断环境：本模块及所有业务代码**不**出现 ``if mode == ...``；
   Providers 由 lifespan 通过 :func:`astra_config.build_providers` 装配，
   业务经由 ``dependencies/container.py`` 取用。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from astra_api import __version__
from astra_api.errors import register_exception_handlers
from astra_api.lifespan import lifespan
from astra_api.middleware import RequestContextMiddleware, ResponseShellMiddleware
from astra_api.routers import api_router, health_router
from astra_api.web_static import install_web_static, resolve_web_dist

__all__ = ["create_app", "app"]


def create_app() -> FastAPI:
    """构造并配置 FastAPI 应用。"""
    from astra_config import get_settings
    from astra_logging import build_metrics

    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Astra AI API（Phase 0 可运行骨架）",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 请求上下文（T1-04）：生成 request_id/trace_id，下发响应头，写日志上下文。
    # 先加 → 更内层；其响应头供外层「响应壳中间件」复用（体 == 头）。
    application.add_middleware(RequestContextMiddleware)

    # 统一响应壳（T1-04 / 总纲 §11.1）：成功 JSON 响应套 {code,message,data,request_id}。
    # 加在请求上下文之外 → 能读到其写入的 X-Request-Id；失败 / SSE / 非 JSON 原样透传。
    application.add_middleware(ResponseShellMiddleware)

    # CORS：显式配置来源时启用凭据；无配置时放开（开发默认，凭据关闭以符合 CORS 规范）。
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(application)

    # 指标（T1-04）：社区默认关闭 → No-Op，且不暴露 /metrics。
    application.state.metrics = build_metrics(enabled=settings.observability.metrics_enabled)

    application.include_router(health_router)
    application.include_router(api_router)

    if settings.observability.metrics_enabled:
        from astra_api.routers.metrics import router as metrics_router

        application.include_router(metrics_router)

    # 前端静态托管（发行形态 A / M2 · WS2）：API 同源托管 apps/web/dist → 单容器
    # 打开即完整 UI。**仅当**解析到产物目录（含 index.html）存在时启用；缺省 /
    # 开发 / 测试无 dist 时零影响。仅在路由未命中的兜底处接管，不改既有 404/405。
    web_dist = resolve_web_dist(settings)
    if web_dist is not None:
        install_web_static(application, web_dist)

    return application


app = create_app()
