"""``astra_mcp`` 领域子模块（实体 / 常量 / 仓储接口；W2 / T2-10）。

本子模块**零 Web / ORM**（受 ``test_layering.py::test_phase2_domain_submodules_have_no_orm_or_web``
覆盖）。
"""

from __future__ import annotations

from .constants import (
    MCP_ACTION_EXECUTE,
    MCP_ACTION_READ,
    MCP_ACTION_WRITE,
    MCP_EFFECT_ALLOW,
    MCP_EFFECT_APPROVAL,
    MCP_EFFECT_DENY,
    MCP_SERVER_STATUS_ACTIVE,
    MCP_SERVER_STATUS_DISABLED,
    MCP_SERVER_STATUS_ERROR,
    MCP_TOOL_STATUS_ACTIVE,
    MCP_TOOL_STATUS_DEPRECATED,
    MCP_TOOL_STATUS_DISABLED,
    MCP_TRANSPORT_HTTP,
    MCP_TRANSPORT_SSE,
    MCP_TRANSPORT_STDIO,
    MCP_TRANSPORTS,
)
from .entities import MCPPermission, MCPServer, MCPTool
from .repository import MCPPermissionRepository, MCPServerRepository, MCPToolRepository

__all__ = [
    # 常量
    "MCP_TRANSPORT_STDIO",
    "MCP_TRANSPORT_SSE",
    "MCP_TRANSPORT_HTTP",
    "MCP_TRANSPORTS",
    "MCP_SERVER_STATUS_ACTIVE",
    "MCP_SERVER_STATUS_DISABLED",
    "MCP_SERVER_STATUS_ERROR",
    "MCP_TOOL_STATUS_ACTIVE",
    "MCP_TOOL_STATUS_DISABLED",
    "MCP_TOOL_STATUS_DEPRECATED",
    "MCP_ACTION_EXECUTE",
    "MCP_ACTION_READ",
    "MCP_ACTION_WRITE",
    "MCP_EFFECT_ALLOW",
    "MCP_EFFECT_DENY",
    "MCP_EFFECT_APPROVAL",
    # 实体
    "MCPServer",
    "MCPTool",
    "MCPPermission",
    # 仓储接口
    "MCPServerRepository",
    "MCPToolRepository",
    "MCPPermissionRepository",
]
