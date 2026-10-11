"""Tool 组仓储接口（**仅 Protocol**，零 ORM，C-03）。

对应 ORM 表：``tool`` / ``tool_version`` / ``tool_permission``。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.tool import Tool, ToolPermission, ToolVersion
from .base import Repository

__all__ = ["ToolRepository", "ToolVersionRepository", "ToolPermissionRepository"]


@runtime_checkable
class ToolRepository(Repository[Tool], Protocol):
    """工具目录仓储接口。"""

    def get_by_name(self, name: str, tenant_id: str | None = None) -> Tool | None:
        """按名获取工具（``tenant_id=None`` 表示全局内置工具）。"""
        ...

    def list_builtin(self) -> list[Tool]:
        """列出全部全局内置工具。"""
        ...


@runtime_checkable
class ToolVersionRepository(Repository[ToolVersion], Protocol):
    """工具规格快照仓储接口。"""

    def list_by_tool(self, tool_id: str) -> list[ToolVersion]:
        """列出某工具的全部规格快照。"""
        ...


@runtime_checkable
class ToolPermissionRepository(Repository[ToolPermission], Protocol):
    """Tool 权限仓储接口。"""

    def list_by_agent(self, agent_id: str) -> list[ToolPermission]:
        """列出某 Agent 的全部 Tool 权限。"""
        ...
