"""``MCP`` 节点（W4 / T2-22；设计 §2.5 / W4 裁定 §6.4 #2/#4/#5）。

``config`` 约定键：``{server, tool, arguments}``。

🔴 **权限单一判定链**：本节点**必过** ``RuntimeBridge.execute_mcp`` → ``ToolExecutor``
   （内建 ``ResourcePermissionChecker``）；MCP 出网（``http`` / ``sse`` 传输）再由
   ``EgressPolicy`` 递归逐跳校验（默认拒绝）。**严禁**在此自建判定源。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode

from ..domain import NODE_TYPE_MCP, WorkflowNode
from ..engine.ports import RuntimeBridge, split_bridge_result
from ..engine.variables import VariableContext
from .base import NodeContext, NodeResult

__all__ = ["McpNode"]


class McpNode:
    """``MCP`` 节点执行器。"""

    type = NODE_TYPE_MCP

    def __init__(self, bridge: RuntimeBridge) -> None:
        """初始化。

        Args:
            bridge: Runtime 桥接（**唯一** Runtime / 权限链出口）。
        """
        self._bridge = bridge

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """执行 ``MCP`` 节点。

        Raises:
            DomainError: ``config.server`` / ``config.tool`` 缺失（``VALIDATION_ERROR``）。
        """
        config = dict(node.config or {})
        server = var_ctx.resolve_value(config.get("server"))
        tool_name = var_ctx.resolve_value(config.get("tool"))
        if not server or not tool_name:
            raise DomainError(
                f"MCP 节点缺少 server / tool：{node.node_key}",
                code=ErrorCode.VALIDATION_ERROR,
                data={
                    "reason": "missing_server_or_tool",
                    "node_key": node.node_key,
                    "server": server,
                    "tool": tool_name,
                },
            )
        arguments = var_ctx.resolve_value(config.get("arguments") or {})
        if not isinstance(arguments, dict):
            raise DomainError(
                f"MCP 节点 arguments 必须为对象：{node.node_key}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "invalid_arguments", "node_key": node.node_key},
            )

        raw = self._bridge.execute_mcp(
            WorkflowNode(
                id=node.id,
                workflow_version_id=node.workflow_version_id,
                node_key=node.node_key,
                type=node.type,
                config={**config, "server": server, "tool": tool_name, "arguments": arguments},
                position=dict(node.position or {}),
            ),
            var_ctx,
            ctx if ctx is not None else NodeContext(),
        )
        output, _agent_run_id, tool_call_id = split_bridge_result(dict(raw or {}))
        return NodeResult.success(output, tool_call_id=tool_call_id)
