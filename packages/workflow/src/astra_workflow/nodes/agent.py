"""``AGENT`` 节点（W4 / T2-22；设计 §2.5 / W4 裁定 §6.4 #2）。

``config`` 约定键：``{agent_id, message}``。

执行**必过** ``RuntimeBridge.run_agent`` → ``AgentRuntime.run``（**复用 Runtime**，
产出**独立** ``agent_run``）；节点**不自建**执行通道。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode

from ..domain import NODE_TYPE_AGENT, WorkflowNode
from ..engine.ports import RuntimeBridge, split_bridge_result
from ..engine.variables import VariableContext
from .base import NodeContext, NodeResult

__all__ = ["AgentNode"]


class AgentNode:
    """``AGENT`` 节点执行器。"""

    type = NODE_TYPE_AGENT

    def __init__(self, bridge: RuntimeBridge) -> None:
        """初始化。

        Args:
            bridge: Runtime 桥接（**唯一** Runtime 出口）。
        """
        self._bridge = bridge

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        """执行 ``AGENT`` 节点。

        Raises:
            DomainError: ``config.agent_id`` 缺失（``VALIDATION_ERROR``）。
        """
        config = dict(node.config or {})
        agent_id = var_ctx.resolve_value(config.get("agent_id"))
        if not agent_id:
            raise DomainError(
                f"AGENT 节点缺少 agent_id：{node.node_key}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "missing_agent_id", "node_key": node.node_key},
            )
        message = var_ctx.resolve_value(config.get("message"))
        if message is not None:
            config = {**config, "message": message}

        raw = self._bridge.run_agent(
            WorkflowNode(
                id=node.id,
                workflow_version_id=node.workflow_version_id,
                node_key=node.node_key,
                type=node.type,
                config={**config, "agent_id": agent_id},
                position=dict(node.position or {}),
            ),
            var_ctx,
            ctx if ctx is not None else NodeContext(),
        )
        output, agent_run_id, _ = split_bridge_result(dict(raw or {}))
        return NodeResult.success(output, agent_run_id=agent_run_id)
