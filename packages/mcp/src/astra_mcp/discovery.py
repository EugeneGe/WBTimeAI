"""MCP 发现（``tools/list`` → 落 ``mcp_tool`` 发现目录；设计 §2.4；W2 / T2-11；R9/R11）。

:class:`MCPDiscovery` 编排：``client.list_tools()`` → **upsert** 到 ``mcp_tool``（发现目录）。
**执行注册表**（``tool`` 表）的写入与适配器注册归 T2-12（``MCPRegistry.sync_to_tool_registry``），
本模块只负责**发现目录**。

🔴 本模块**零 Web**；ORM 经**注入的**领域仓储（:class:`~astra_mcp.domain.MCPToolRepository`）。
"""

from __future__ import annotations

from .client import MCPClient
from .domain import MCP_TOOL_STATUS_ACTIVE, MCPServer, MCPTool, MCPToolRepository

__all__ = ["MCPDiscovery"]


class MCPDiscovery:
    """MCP Tool 发现器（把 ``tools/list`` 结果落到 ``mcp_tool`` 发现目录）。

    Args:
        tool_repository: ``mcp_tool`` 领域仓储（DI 注入）。
    """

    def __init__(self, *, tool_repository: MCPToolRepository) -> None:
        self._tools = tool_repository

    def discover(self, server: MCPServer, client: MCPClient) -> list[MCPTool]:
        """发现 Server 的 Tools 并 **upsert** 到 ``mcp_tool``（返回落库后的目录条目）。

        Args:
            server: 目标 MCP Server。
            client: 已握手的 :class:`~astra_mcp.client.MCPClient`。

        Returns:
            本次发现的 :class:`~astra_mcp.domain.MCPTool` 列表（含既有条目更新）。
        """
        specs = client.list_tools()
        discovered: list[MCPTool] = []
        for spec in specs:
            existing = self._tools.get_by_name(server.id, spec.name)
            if existing is not None:
                updated = MCPTool(
                    id=existing.id,
                    tenant_id=existing.tenant_id,
                    mcp_server_id=server.id,
                    name=spec.name,
                    description=spec.description,
                    input_schema=dict(spec.input_schema),
                    output_schema=dict(spec.output_schema),
                    status=MCP_TOOL_STATUS_ACTIVE,
                    discovered_at=existing.discovered_at,
                )
                discovered.append(self._tools.update(updated))
            else:
                created = MCPTool(
                    tenant_id=server.tenant_id,
                    mcp_server_id=server.id,
                    name=spec.name,
                    description=spec.description,
                    input_schema=dict(spec.input_schema),
                    output_schema=dict(spec.output_schema),
                    status=MCP_TOOL_STATUS_ACTIVE,
                )
                discovered.append(self._tools.add(created))
        return discovered
