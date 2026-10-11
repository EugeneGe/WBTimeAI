"""``astra_mcp`` 领域实体（设计 §2.4；W2 / T2-10）。

- :class:`MCPServer`：MCP Server 配置（``transport`` / ``endpoint`` / ``command`` /
  ``env_ref`` / ``credential_id``；``name`` 租户内唯一）；
- :class:`MCPTool`：**发现目录**条目（``tools/list`` 结果；``(mcp_server_id, name)`` 唯一）
  —— 与 ``tool`` 表（**执行注册表**）语义区分（R-22 / R9）；
- :class:`MCPPermission`：MCP Tool **默认策略模板**（``effect`` 含 ``APPROVAL`` 预留；
  W2 不作运行期判定源，运行期唯一判定链归 T2-13）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_domain import AggregateRoot

from .constants import (
    MCP_ACTION_EXECUTE,
    MCP_EFFECT_DENY,
    MCP_SERVER_STATUS_ACTIVE,
    MCP_TOOL_STATUS_ACTIVE,
    MCP_TRANSPORT_STDIO,
)

__all__ = ["MCPServer", "MCPTool", "MCPPermission"]


@dataclass
class MCPServer(AggregateRoot):
    """MCPServer 聚合根（MCP Server 配置与生命周期）。

    Attributes:
        name: 租户内唯一名（``mcp:<server>.<tool>`` 命名空间的 ``server`` 部分）。
        transport: 传输（``stdio`` / ``sse`` / ``http``）。
        endpoint: 出网端点（``http`` / ``sse`` 传输必填；``stdio`` 为空）。
        command: 启动命令（``stdio`` 传输用；可空）。
        args: 启动参数（``stdio`` 传输用；可空）。
        env_ref: 环境变量**引用**（仅引用，不存明文；可空）。
        credential_id: 复用 Phase 0 ``credential`` 的凭证引用（可空）。
        status: Server 状态（``ACTIVE`` / ``DISABLED`` / ``ERROR``）。
        capabilities: 握手缓存的能力协商结果（可空）。
        workspace_id: 归属工作区（可空）。
    """

    name: str = ""
    transport: str = MCP_TRANSPORT_STDIO
    endpoint: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env_ref: dict[str, Any] = field(default_factory=dict)
    credential_id: str | None = None
    status: str = MCP_SERVER_STATUS_ACTIVE
    capabilities: dict[str, Any] = field(default_factory=dict)
    workspace_id: str | None = None


@dataclass
class MCPTool(AggregateRoot):
    """MCPTool（MCP Server 的**发现目录**条目）。

    Attributes:
        mcp_server_id: 归属的 MCPServer 标识。
        name: Tool 名（Server 内唯一）。
        description: 描述。
        input_schema: 输入 JSON Schema（可空）。
        output_schema: 输出 JSON Schema（可空）。
        status: Tool 状态（``ACTIVE`` / ``DISABLED`` / ``DEPRECATED``）。
        discovered_at: 发现时间（UTC）。
    """

    mcp_server_id: str = ""
    name: str = ""
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    status: str = MCP_TOOL_STATUS_ACTIVE
    discovered_at: datetime = field(default_factory=utcnow)


@dataclass
class MCPPermission(AggregateRoot):
    """MCPPermission（MCP Tool **默认策略模板**；非运行期判定源）。

    Attributes:
        agent_id: 适用 Agent（可空 = 租户级默认）。
        agent_version_id: 适用 AgentVersion（可空）。
        mcp_tool_id: 目标 MCPTool 标识。
        action: 动作（``EXECUTE`` / ``READ`` / ``WRITE``）。
        effect: 效果（``ALLOW`` / ``DENY`` / ``APPROVAL``；默认拒绝优先）。
        scope: 细粒度范围（JSON，可空）。
    """

    agent_id: str | None = None
    agent_version_id: str | None = None
    mcp_tool_id: str = ""
    action: str = MCP_ACTION_EXECUTE
    effect: str = MCP_EFFECT_DENY
    scope: dict[str, Any] = field(default_factory=dict)
