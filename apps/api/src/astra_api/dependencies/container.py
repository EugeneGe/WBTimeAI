"""Provider 容器依赖（业务代码取用 Providers 的唯一入口）。

🔴 业务代码**只**从此处取 Providers，绝不判断 ``ASTRA_MODE``；
   环境分流只存在于 :func:`astra_config.build_providers`。
"""

from __future__ import annotations

from typing import Annotated, Any

from astra_config import Providers, build_providers, get_settings
from astra_config.providers import DatabaseProvider
from fastapi import Depends, Request

__all__ = [
    "get_container",
    "get_database_provider",
    "get_event_bus",
    "get_sandbox_provider",
    "build_container",
    "build_container_services",
    "build_identity_services_from_providers",
]


def get_container(request: Request) -> Providers:
    """从 ``app.state`` 取出已装配的 :class:`Providers`。

    Providers 由 lifespan 启动时通过 :func:`astra_config.build_providers` 装配。

    Args:
        request: 当前请求（用于访问 ``app.state``）。

    Returns:
        已装配的 Providers 容器。

    Raises:
        RuntimeError: 当 lifespan 未完成装配时。
    """
    providers = getattr(request.app.state, "providers", None)
    if providers is None:
        raise RuntimeError("Providers 尚未初始化：请确认应用 lifespan 已运行")
    return providers


def get_database_provider(
    providers: Annotated[Providers, Depends(get_container)],
) -> DatabaseProvider:
    """取出数据库 Provider。"""
    if providers.database is None:
        raise RuntimeError("Database Provider 未装配")
    return providers.database


def get_event_bus(providers: Annotated[Providers, Depends(get_container)]) -> Any:
    """取出事件总线 Provider（供 SSE 实时订阅；W6 / T1-28）。"""
    if providers.event_bus is None:
        raise RuntimeError("EventBus Provider 未装配")
    return providers.event_bus


def get_sandbox_provider(providers: Annotated[Providers, Depends(get_container)]) -> Any:
    """取出 Sandbox Provider（社区降级时可为 ``None``；W6 / T1-31）。"""
    return providers.sandbox


def build_container() -> Providers:
    """独立装配 Providers（供测试或非 Web 场景使用）。

    Returns:
        依据当前配置装配的 :class:`Providers`。
    """
    return build_providers(get_settings())


def build_container_services():
    """独立装配 Providers 并构建 :class:`AppServices`（供测试 / 非 Web 场景）。

    Returns:
        依据当前配置装配的 :class:`~astra_api.dependencies.services.AppServices`。
    """
    from .services import build_app_services

    return build_app_services(build_container())


def build_identity_services_from_providers(providers: Providers):
    """仅构建身份子域服务（供 CLI ``init`` 触发默认身份引导，无需安全原语）。

    复用同一组合根：CLI 不复制业务逻辑，仍经 ``astra_api`` 取用能力包服务。

    Args:
        providers: 已装配的 Provider 容器。

    Returns:
        :class:`~astra_identity.IdentityServices`。

    Raises:
        RuntimeError: 数据库 Provider 未装配。
    """
    from astra_identity import build_identity_services

    if providers.database is None:
        raise RuntimeError("Database Provider 未装配，无法构建身份服务")
    return build_identity_services(providers.database.session_factory)
