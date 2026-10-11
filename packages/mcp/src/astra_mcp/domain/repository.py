"""``astra_mcp`` 仓储接口（**仅 Protocol**，零 ORM；设计 §2.4 / W2 裁定 R9）。

- :class:`MCPServerRepository`：MCP Server 仓储（``(tenant_id, name)`` 唯一）；
- :class:`MCPToolRepository`：MCP Tool **发现目录**仓储（``(mcp_server_id, name)`` 唯一）；
- :class:`MCPPermissionRepository`：MCP Tool 默认策略模板仓储。

SQLAlchemy 实现落本包 ``repositories/``（能力包显式允许的 ORM 落点）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import Repository

from .entities import MCPPermission, MCPServer, MCPTool

__all__ = [
    "MCPServerRepository",
    "MCPToolRepository",
    "MCPPermissionRepository",
]


@runtime_checkable
class MCPServerRepository(Repository[MCPServer], Protocol):
    """MCP Server 仓储接口（多租户隔离；``(tenant_id, name)`` 唯一）。"""

    def get_by_name(self, tenant_id: str, name: str) -> MCPServer | None:
        """按 ``(tenant_id, name)`` 获取 Server，不存在返回 ``None``。"""
        ...

    def list_by_tenant(self, tenant_id: str) -> list[MCPServer]:
        """列出某租户下的全部 Server。"""
        ...


@runtime_checkable
class MCPToolRepository(Repository[MCPTool], Protocol):
    """MCP Tool **发现目录**仓储接口（``(mcp_server_id, name)`` 唯一）。"""

    def get_by_name(self, mcp_server_id: str, name: str) -> MCPTool | None:
        """按 ``(mcp_server_id, name)`` 获取 Tool，不存在返回 ``None``。"""
        ...

    def list_by_server(self, mcp_server_id: str) -> list[MCPTool]:
        """列出某 Server 的全部已发现 Tool。"""
        ...


@runtime_checkable
class MCPPermissionRepository(Repository[MCPPermission], Protocol):
    """MCP Tool 默认策略模板仓储接口。"""

    def list_by_tool(self, mcp_tool_id: str) -> list[MCPPermission]:
        """列出某 MCPTool 的全部默认策略条目。"""
        ...
