"""Tool 组合工厂（纯 DI 装配 + config 装配入口，W4 架构裁定 Q1/Q4）。

- :func:`build_tool_registry`：**config 入口**（``astra_config.providers._build_optional`` 调用），
  注册首批内置工具，**零 DB**（F17）；
- :func:`build_tool_services`：**DI 装配**——把**已构造的领域 Protocol 仓储**注入
  ``PermissionService``；🔴 **不接触** ``session_factory`` / ``sandbox``（``session_factory → SQL
  仓储`` 的接线属组合根 T1-31）。
"""

from __future__ import annotations

from typing import Any

from astra_domain import (
    ResourcePermissionRepository,
    ToolPermissionRepository,
    ToolRepository,
)

from .permission_checker import PolicyDecisionPoint, PolicyEnforcementPoint
from .registry import ToolRegistry
from .services import PermissionService
from .tools import register_builtin_tools

__all__ = ["build_tool_registry", "build_tool_services"]


def build_tool_registry(settings: Any) -> ToolRegistry:
    """构建并填充首批内置工具的 :class:`ToolRegistry`（config 装配入口）。

    Args:
        settings: 生效配置（本波次未使用；保留以对齐 ``_build_optional`` 调用约定）。

    Returns:
        已注册首批 5 个内置工具的注册表。
    """
    registry = ToolRegistry()
    return register_builtin_tools(registry)


def build_tool_services(
    *,
    tool_repository: ToolRepository,
    tool_permission_repository: ToolPermissionRepository,
    resource_permission_repository: ResourcePermissionRepository | None = None,
    tool_registry: ToolRegistry | None = None,
    pep: PolicyEnforcementPoint | None = None,
    pdp: PolicyDecisionPoint | None = None,
) -> PermissionService:
    """依领域 Protocol 仓储装配 :class:`PermissionService`（DI）。

    Args:
        tool_repository: 领域 ``ToolRepository`` 实现
            （如 ``astra_database.SqlToolRepository``）。
        tool_permission_repository: 领域 ``ToolPermissionRepository`` 实现
            （如 ``astra_database.SqlToolPermissionRepository``）。
        resource_permission_repository: **可选** 领域 ``ResourcePermissionRepository`` 实现
            （如 ``astra_database.SqlResourcePermissionRepository``）。注入时 ``grant`` /
            ``revoke`` / ``list`` 落 ``resource_permission``（运行期**唯一**判定源，W3 / T2-13
            补丁）；``None`` 时回退 ``tool_permission``（默认策略模板，向后兼容）。
        tool_registry: **可选** 运行期工具注册表（``tool_registry``）。注入时 ``grant`` 会把
            已持久化 ``tool`` 行的真实 id 归一到同名注册表条目，使实例级授权在运行期可命中。
        pep: 可选策略执行点（RP-06）。
        pdp: 可选策略决策点（RP-07）。

    Returns:
        :class:`~astra_tool.services.PermissionService`。
    """
    return PermissionService(
        tool_repository=tool_repository,
        tool_permission_repository=tool_permission_repository,
        resource_permission_repository=resource_permission_repository,
        tool_registry=tool_registry,
        pep=pep,
        pdp=pdp,
    )
