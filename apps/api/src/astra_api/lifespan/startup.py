"""lifespan 启动/关闭逻辑。

启动：加载配置 → 初始化日志 → 装配 Providers → 构建 ``AppServices`` →
**触发默认身份引导**（Tenant-ready，幂等）→ 挂到 ``app.state``。
关闭：释放数据库引擎等资源。

🔴 本模块**不判断 mode**（唯一分流点在 ``astra_config.providers``）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from astra_config import build_providers, get_settings
from astra_logging import configure_logging, get_logger
from fastapi import FastAPI

from astra_api.dependencies.services import build_app_services

__all__ = ["lifespan"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期上下文管理器。"""
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)

    # Provider 自动装配（决策 D4）：唯一的环境分流点位于 build_providers 内部。
    providers = build_providers(settings)
    app.state.settings = settings
    app.state.providers = providers

    # 应用服务装配（组合根产物）。
    services = build_app_services(providers)
    app.state.services = services

    # §3-#5 Tenant-ready：默认 `default` Tenant / 组织 / admin 自动建立（幂等，用户无感）。
    services.identity.bootstrap.ensure_default_identity()

    # §2.9 / W6 · T1-31：重启兜底扫描——心跳超期的 ``RUNNING`` Run 置 ``FAILED``
    # + 同步 ``task`` + 强制回收 ``sandbox_session``（幂等；失败不阻断启动）。
    try:
        recovered = services.run.recover_stale_runs(settings.run_timeout_ms)
    except Exception:  # noqa: BLE001 - 兜底扫描失败不得阻断应用启动
        logger.warning(
            "astra.api.recovery.failed",
            extra={"event": "startup_recovery_failed"},
            exc_info=True,
        )
    else:
        if recovered:
            logger.info(
                "astra.api.recovery",
                extra={"event": "startup_recovery", "count": len(recovered)},
            )

    logger.info("astra.api.startup", extra={"event": "startup", "mode": settings.mode})
    try:
        yield
    finally:
        database = providers.database
        engine = getattr(database, "engine", None) if database is not None else None
        if engine is not None:
            engine.dispose()
        logger.info("astra.api.shutdown", extra={"event": "shutdown"})
