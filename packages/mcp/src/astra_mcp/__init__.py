"""Astra AI MCP 能力包（``astra_mcp``；设计 §2.4）。

- 领域实体 / 常量 / 仓储接口：``astra_mcp.domain``（``MCPServer`` / ``MCPTool`` /
  ``MCPPermission``）；
- SQL 仓储：``astra_mcp.repositories``（能力包 ORM 落点）；
- ``Client`` / ``Registry`` / ``Discovery`` / ``Authorization`` / ``runtime.McpExecutor``
  归 **T2-11 / T2-12**（新增模块，不在本文件提前导入）。

包性质：能力包（仅禁 Web；SQL 仓储留本包 ``repositories/``）——W2 裁定 R1/R2。
🗒️ MCP SDK（``mcp>=1.0,<2``）为**可选 extra** ``astra-mcp[mcp]``，**仅函数级延迟导入**（R7）。
"""

from __future__ import annotations

from .authorization import MCPAuthorization
from .client import (
    DefaultMCPClient,
    ManagedProcess,
    MCPClient,
    MCPTransport,
    ProcessSpawner,
    SseTransport,
    StdioTransport,
    StreamableHttpTransport,
    build_mcp_client,
)
from .discovery import MCPDiscovery
from .domain import (
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
    MCPPermission,
    MCPPermissionRepository,
    MCPServer,
    MCPServerRepository,
    MCPTool,
    MCPToolRepository,
)
from .protocol import (
    MCPCapabilities,
    MCPError,
    MCPProtocolError,
    MCPTimeoutError,
    MCPToolSpec,
    MCPTransportError,
    latest_protocol_version,
)
from .registry import MCPRegistry, build_mcp_registry
from .repositories import (
    SqlMCPPermissionRepository,
    SqlMCPServerRepository,
    SqlMCPToolRepository,
)
from .runtime import MCPClientInvoker, McpExecutor
from .services import MCPPermissionService

__all__ = [
    # 常量 · 传输
    "MCP_TRANSPORT_STDIO",
    "MCP_TRANSPORT_SSE",
    "MCP_TRANSPORT_HTTP",
    "MCP_TRANSPORTS",
    # 常量 · Server 状态
    "MCP_SERVER_STATUS_ACTIVE",
    "MCP_SERVER_STATUS_DISABLED",
    "MCP_SERVER_STATUS_ERROR",
    # 常量 · Tool 状态
    "MCP_TOOL_STATUS_ACTIVE",
    "MCP_TOOL_STATUS_DISABLED",
    "MCP_TOOL_STATUS_DEPRECATED",
    # 常量 · 动作 / 效果
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
    # SQL 仓储
    "SqlMCPServerRepository",
    "SqlMCPToolRepository",
    "SqlMCPPermissionRepository",
    # 协议 / DTO / 错误
    "MCPCapabilities",
    "MCPToolSpec",
    "MCPError",
    "MCPProtocolError",
    "MCPTransportError",
    "MCPTimeoutError",
    "latest_protocol_version",
    # 传输 / 客户端
    "MCPTransport",
    "ManagedProcess",
    "ProcessSpawner",
    "StdioTransport",
    "StreamableHttpTransport",
    "SseTransport",
    "MCPClient",
    "DefaultMCPClient",
    "build_mcp_client",
    # 发现 / 注册 / 授权
    "MCPDiscovery",
    "MCPRegistry",
    "build_mcp_registry",
    "MCPAuthorization",
    # 运行时执行器（RP-04；T2-12）
    "McpExecutor",
    "MCPClientInvoker",
    # MCP 授权读写服务（W3 / T2-13 补丁 · 裁定 §21.4 X1/X2）
    "MCPPermissionService",
]
