"""``astra_mcp`` 领域常量（设计 §2.4；W2 / T2-10）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

__all__ = [
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
]

# -- 传输（设计 §2.4：stdio | sse | http） -----------------------------------

#: 本地子进程传输（无出网）。
MCP_TRANSPORT_STDIO = "stdio"
#: Server-Sent Events 传输（出网，须过 ``EgressPolicy``）。
MCP_TRANSPORT_SSE = "sse"
#: Streamable HTTP 传输（出网，须过 ``EgressPolicy``）。
MCP_TRANSPORT_HTTP = "http"

#: 全部合法传输取值。
MCP_TRANSPORTS: tuple[str, ...] = (MCP_TRANSPORT_STDIO, MCP_TRANSPORT_SSE, MCP_TRANSPORT_HTTP)

# -- Server 状态（设计 §2.4：ACTIVE | DISABLED | ERROR） ----------------------

#: Server 可用。
MCP_SERVER_STATUS_ACTIVE = "ACTIVE"
#: Server 被停用。
MCP_SERVER_STATUS_DISABLED = "DISABLED"
#: Server 处于错误态（如握手失败）。
MCP_SERVER_STATUS_ERROR = "ERROR"

# -- Tool 状态 ---------------------------------------------------------------

#: Tool 可用。
MCP_TOOL_STATUS_ACTIVE = "ACTIVE"
#: Tool 被停用。
MCP_TOOL_STATUS_DISABLED = "DISABLED"
#: Tool 已从 Server 消失（发现时标记）。
MCP_TOOL_STATUS_DEPRECATED = "DEPRECATED"

# -- 权限动作（设计 §2.4：EXECUTE | READ | WRITE） ---------------------------

#: 执行动作。
MCP_ACTION_EXECUTE = "EXECUTE"
#: 读取动作。
MCP_ACTION_READ = "READ"
#: 写入动作。
MCP_ACTION_WRITE = "WRITE"

# -- 权限效果（设计 §2.4：ALLOW | DENY | APPROVAL） --------------------------

#: 放行。
MCP_EFFECT_ALLOW = "ALLOW"
#: 拒绝。
MCP_EFFECT_DENY = "DENY"
#: 需人工审批（Phase 3 预留）。
MCP_EFFECT_APPROVAL = "APPROVAL"
