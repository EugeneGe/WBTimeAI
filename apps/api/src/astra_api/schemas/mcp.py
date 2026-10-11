"""MCP schema（W3 / T2-17；设计 §2.4 / §2.12）。

``/mcp/servers`` 注册 / 发现 + ``/mcp/tools`` 目录 + ``/mcp/permissions`` 授权。

🔴 凭据**仅掩码 / 仅引用**：响应**不回显明文**；``credential_id`` 为引用，``env_ref`` 为
   引用（不含明文）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "RegisterMCPServerRequest",
    "MCPServerResponse",
    "MCPToolResponse",
    "CreateMCPPermissionRequest",
    "MCPPermissionResponse",
]


class RegisterMCPServerRequest(BaseModel):
    """注册 MCP Server 请求。"""

    name: str = Field(min_length=1, max_length=150, description="Server 名（租户内唯一）")
    transport: str = Field(default="stdio", description="传输（stdio/sse/http）")
    endpoint: str | None = Field(default=None, description="出网端点（http/sse 必填）")
    command: str | None = Field(default=None, description="启动命令（stdio 用）")
    args: list[str] = Field(default_factory=list, description="启动参数（stdio 用）")
    env_ref: dict[str, Any] = Field(default_factory=dict, description="环境变量引用（不含明文）")
    credential_id: str | None = Field(default=None, description="凭证引用（复用 credential 表）")
    workspace_id: str | None = Field(default=None)


class MCPServerResponse(BaseModel):
    """MCP Server 响应（**无明文**）。"""

    id: str
    tenant_id: str | None = Field(default=None)
    name: str
    transport: str = "stdio"
    endpoint: str | None = Field(default=None)
    command: str | None = Field(default=None)
    args: list[str] = Field(default_factory=list)
    env_ref: dict[str, Any] = Field(default_factory=dict)
    credential_id: str | None = Field(default=None)
    status: str = "ACTIVE"
    workspace_id: str | None = Field(default=None)
    created_at: datetime | None = Field(default=None)


class MCPToolResponse(BaseModel):
    """MCP Tool（发现目录）响应。"""

    id: str
    mcp_server_id: str
    name: str
    description: str | None = Field(default=None)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    status: str = "ACTIVE"
    discovered_at: datetime | None = Field(default=None)


class CreateMCPPermissionRequest(BaseModel):
    """MCP Tool 授权请求（agent × mcp_tool × effect × scope）。"""

    agent_id: str | None = Field(default=None, description="适用 Agent（空 = 租户级默认）")
    agent_version_id: str | None = Field(default=None)
    mcp_tool_id: str = Field(min_length=1, description="目标 MCPTool 标识")
    action: str = Field(default="EXECUTE", description="动作（EXECUTE/READ/WRITE）")
    effect: str = Field(default="DENY", description="效果（ALLOW/DENY）")
    scope: dict[str, Any] = Field(default_factory=dict, description="细粒度范围")


class MCPPermissionResponse(BaseModel):
    """MCP Tool 授权响应。"""

    id: str
    tenant_id: str | None = Field(default=None)
    agent_id: str | None = Field(default=None)
    agent_version_id: str | None = Field(default=None)
    mcp_tool_id: str
    action: str = "EXECUTE"
    effect: str = "DENY"
    scope: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = Field(default=None)
