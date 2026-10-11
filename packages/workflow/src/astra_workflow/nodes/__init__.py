"""``astra_workflow`` 8 类节点（W4 裁定 §3.1 / §5 T2-22）。

- :mod:`base`：``NodeExecutor`` Protocol + ``NodeResult`` + ``NodeContext`` +
  ``NodeRegistry``；
- 8 类具体节点：``AGENT`` / ``TOOL`` / ``MCP`` / ``CONDITION`` / ``PARALLEL`` / ``LOOP`` /
  ``HUMAN_APPROVAL`` / ``END``；
- :func:`build_default_node_registry`：按注入依赖装配**默认注册表**（组合根入口）。

🔴 节点内 ``TOOL`` / ``MCP`` **必过** ``RuntimeBridge`` → ``ToolExecutor``
   （内建 ``ResourcePermissionChecker``，**唯一判定链**）；出网**必过** ``EgressPolicy``。
"""

from __future__ import annotations

from typing import Any

from astra_domain import ApprovalGateway
from astra_domain.constants import DEFAULT_MAX_ITERATIONS, DEFAULT_MAX_PARALLEL

from ..engine.ports import (
    ConcurrencyGuard,
    NullConcurrencyGuard,
    NullRuntimeBridge,
    RuntimeBridge,
)
from .agent import AgentNode

# 🔴 导入顺序**不可调整**：``.base`` 必须先于任何 ``..engine`` 导入——
#    ``engine.scheduler`` 需从本包取 ``NodeContext``（跨包循环导入的**唯一**安全顺序）。
from .base import NodeContext, NodeDispatcher, NodeExecutor, NodeRegistry, NodeResult
from .condition import (
    DEFAULT_FALSE_BRANCH,
    DEFAULT_OPERATOR_WHITELIST,
    DEFAULT_TRUE_BRANCH,
    ConditionNode,
    evaluate_expression,
)
from .end import EndNode
from .human_approval import APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE, HumanApprovalNode
from .loop import ABSOLUTE_MAX_ITERATIONS, LoopNode
from .mcp import McpNode
from .parallel import ParallelNode
from .tool import ToolNode

__all__ = [
    # 契约
    "NodeExecutor",
    "NodeResult",
    "NodeRegistry",
    "NodeContext",
    "NodeDispatcher",
    # 8 类节点
    "AgentNode",
    "ToolNode",
    "McpNode",
    "ConditionNode",
    "ParallelNode",
    "LoopNode",
    "HumanApprovalNode",
    "EndNode",
    # 常量
    "DEFAULT_TRUE_BRANCH",
    "DEFAULT_FALSE_BRANCH",
    "DEFAULT_OPERATOR_WHITELIST",
    "APPROVAL_SUBJECT_TYPE_WORKFLOW_NODE",
    "ABSOLUTE_MAX_ITERATIONS",
    # 工具 / 装配
    "evaluate_expression",
    "build_default_node_registry",
]


def build_default_node_registry(
    *,
    bridge: RuntimeBridge | None = None,
    gateway: ApprovalGateway | None = None,
    concurrency: ConcurrencyGuard | None = None,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    default_max_iterations: int = DEFAULT_MAX_ITERATIONS,
    use_threads: bool = True,
    agent: Any | None = None,
    tool: Any | None = None,
    mcp: Any | None = None,
) -> NodeRegistry:
    """装配 8 类节点的**默认注册表**（组合根入口）。

    Args:
        bridge: Runtime 桥接（``AGENT`` / ``TOOL`` / ``MCP`` 必需）；缺省
            ``NullRuntimeBridge``（未装配时**显式报错**）。
        gateway: 审批网关（``HUMAN_APPROVAL`` 所需；``None`` 时使用
            ``NullRuntimeBridge`` 的同构报错语义——见 :class:`HumanApprovalNode`）。
        concurrency: 并发守卫（``PARALLEL``）；缺省 ``NullConcurrencyGuard``。
        max_parallel: ``PARALLEL`` 引擎侧上限（``ConcurrencyConfig.max_parallel``）。
        default_max_iterations: ``LOOP`` 默认迭代上限。
        use_threads: ``PARALLEL`` 是否以线程池并发执行。
        agent / tool / mcp: 可选**自定义**执行器覆盖（便于测试 / 扩展）。

    Returns:
        已装配的 :class:`NodeRegistry`。
    """
    registry = NodeRegistry()
    registry.register(agent if agent is not None else AgentNode(bridge or NullRuntimeBridge()))
    registry.register(tool if tool is not None else ToolNode(bridge or NullRuntimeBridge()))
    registry.register(mcp if mcp is not None else McpNode(bridge or NullRuntimeBridge()))
    registry.register(ConditionNode())
    registry.register(
        ParallelNode(
            concurrency=concurrency if concurrency is not None else NullConcurrencyGuard(),
            max_parallel=max_parallel,
            use_threads=use_threads,
        )
    )
    registry.register(LoopNode(default_max_iterations=default_max_iterations))
    registry.register(HumanApprovalNode(gateway))
    registry.register(EndNode())
    return registry
