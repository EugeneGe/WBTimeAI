"""``TOOL`` 节点（W4 / T2-22；设计 §2.5 / W4 裁定 §6.4 #2/#4/#5）。

``config`` 约定键：``{tool, arguments}``。

🔴 **权限单一判定链**：本节点**必过** ``RuntimeBridge.execute_tool`` → ``ToolExecutor``
   （内建 ``ResourcePermissionChecker``）；``DENIED`` → 不执行。出网工具
   （``http.request``）再由 ``EgressPolicy`` 兜底。**严禁**在此自建判定源。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode

from ..domain import NODE_TYPE_TOOL, WorkflowNode
from ..engine.ports import RuntimeBridge, split_bridge_result
from ..engine.variables import VariableContext
from .base import NodeContext, NodeResult

__all__ = ["ToolNode"]


class ToolNode:
    """``TOOL`` 节点执行器。"""

    type = NODE_TYPE_TOOL

    def __init__(self, bridge: RuntimeBridge) -> None:
        """初始化。

        Args:
            bridge: Runtime 桥接（**唯一** Runtime / 权限链出口）。
        """
        self._bridge = bridge

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """执行 ``TOOL`` 节点。

        Raises:
            DomainError: ``config.tool`` 缺失（``VALIDATION_ERROR``）。
        """
        config = dict(node.config or {})
        tool_name = var_ctx.resolve_value(config.get("tool"))
        if not tool_name:
            raise DomainError(
                f"TOOL 节点缺少 tool：{node.node_key}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "missing_tool", "node_key": node.node_key},
            )
        arguments = var_ctx.resolve_value(config.get("arguments") or {})
        if not isinstance(arguments, dict):
            raise DomainError(
                f"TOOL 节点 arguments 必须为对象：{node.node_key}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "invalid_arguments", "node_key": node.node_key},
            )

        raw = self._bridge.execute_tool(
            WorkflowNode(
                id=node.id,
                workflow_version_id=node.workflow_version_id,
                node_key=node.node_key,
                type=node.type,
                config={**config, "tool": tool_name, "arguments": arguments},
                position=dict(node.position or {}),
            ),
            var_ctx,
            ctx if ctx is not None else NodeContext(),
        )
        output, _agent_run_id, tool_call_id = split_bridge_result(dict(raw or {}))
        return NodeResult.success(output, tool_call_id=tool_call_id)
