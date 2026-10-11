"""节点执行器契约（``NodeExecutor`` Protocol + ``NodeResult``；W4 裁定 §3.5）。

- :class:`NodeResult`：节点执行的**统一产出**（状态 / 输出 / 分支 / 关联标识）；
- :class:`NodeExecutor`：8 类节点共同实现的 Protocol（``type`` + ``execute``）；
- :class:`NodeRegistry`：``node_type → NodeExecutor`` 注册表（引擎构造入参）。

🔴 节点内 ``TOOL`` / ``MCP`` **必过** ``RuntimeBridge`` → ``ToolExecutor``
   （内建 ``ResourcePermissionChecker``，**唯一判定链**）；**严禁**在节点内自建判定源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode

from ..domain import (
    WORKFLOW_NODE_RUN_STATUS_FAILED,
    WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
    WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
    WorkflowNode,
)

__all__ = [
    "NodeResult",
    "NodeExecutor",
    "NodeRegistry",
    "NodeContext",
    "NodeDispatcher",
]


@dataclass
class NodeResult:
    """节点执行结果（统一产出；引擎据此推进状态机）。

    Attributes:
        status: 节点状态（``SUCCEEDED`` / ``FAILED`` / ``WAITING_APPROVAL``）。
        output: 节点产出（以 ``node_key`` 命名空间注入变量上下文）。
        next_branch: ``CONDITION`` 选中的分支名（用于匹配 ``workflow_edge.condition``）。
        agent_run_id: ``AGENT`` 节点产出的独立 ``agent_run`` 标识（可空）。
        tool_call_id: ``TOOL`` / ``MCP`` 节点产出的 ``tool_call`` 标识（可空）。
        approval_id: ``HUMAN_APPROVAL`` 节点挂起的 ``approval`` 标识（可空）。
        error: 失败原因（``FAILED`` 时写入 ``workflow_run.error``）。
    """

    status: str = WORKFLOW_NODE_RUN_STATUS_SUCCEEDED
    output: dict[str, Any] = field(default_factory=dict)
    next_branch: str | None = None
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    approval_id: str | None = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        """是否为失败结果。"""
        return self.status == WORKFLOW_NODE_RUN_STATUS_FAILED

    @property
    def suspended(self) -> bool:
        """是否挂起等待审批（**非终态**）。"""
        return self.status == WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL

    @classmethod
    def success(cls, output: dict[str, Any] | None = None, **extra: Any) -> NodeResult:
        """构造成功结果。"""
        return cls(status=WORKFLOW_NODE_RUN_STATUS_SUCCEEDED, output=dict(output or {}), **extra)

    @classmethod
    def failure(cls, error: str, output: dict[str, Any] | None = None) -> NodeResult:
        """构造失败结果。"""
        return cls(
            status=WORKFLOW_NODE_RUN_STATUS_FAILED,
            output=dict(output or {}),
            error=error,
        )

    @classmethod
    def suspended_for_approval(cls, approval_id: str | None = None) -> NodeResult:
        """构造「挂起等待审批」结果（``WAITING_APPROVAL``）。"""
        return cls(
            status=WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
            approval_id=approval_id,
        )


@dataclass
class NodeContext:
    """节点执行期上下文（由引擎按 **per-run** 构造并透传给各节点）。

    ``PARALLEL`` / ``LOOP`` 需**驱动子分支 / 循环体**，故上下文携带：

    - :attr:`dispatcher`：按 ``node_key`` 分派的**闭包**（已绑定本次 run + 图，**无共享
      可变状态**，可安全用于分支并发）；
    - :attr:`graph`：本次运行的图视图（只读）。

    Attributes:
        run_id: 所属 ``workflow_run.id``。
        tenant_id: 租户标识（多租户隔离）。
        requested_by: 发起人（``HUMAN_APPROVAL`` 的 ``requested_by``）。
        workflow_run: 运行实体（只读引用）。
        graph: 图视图（只读引用）。
        dispatcher: 子节点分派器（``NodeDispatcher``）。
        data: 透传数据（Application / Worker 侧自定义）。
    """

    run_id: str = ""
    tenant_id: str | None = None
    requested_by: str | None = None
    workflow_run: Any | None = None
    graph: Any | None = None
    dispatcher: Any | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def dispatch(self, node_key: str, var_ctx: Any, ctx: Any | None = None) -> NodeResult:
        """分派执行 ``node_key`` 对应子节点（无分派器 → ``CONFIGURATION_ERROR``）。

        Raises:
            DomainError: 未装配分派器（``CONFIGURATION_ERROR``）。
        """
        if self.dispatcher is None:
            raise DomainError(
                "节点上下文未装配 dispatcher，无法驱动子节点",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "dispatcher_missing", "node_key": node_key},
            )
        return self.dispatcher.dispatch(node_key, var_ctx, ctx if ctx is not None else self)


@runtime_checkable
class NodeDispatcher(Protocol):
    """子节点分派器（``PARALLEL`` / ``LOOP`` 驱动子体用）。"""

    def dispatch(
        self,
        node_key: str,
        var_ctx: Any,
        ctx: Any = None,
    ) -> NodeResult:
        """按 ``node_key`` 执行子节点并返回 :class:`NodeResult`。"""
        ...


@runtime_checkable
class NodeExecutor(Protocol):
    """节点执行器 Protocol（8 类节点共同契约）。"""

    #: 节点类型字面值（``AGENT`` / ``TOOL`` / …）。
    type: str

    def execute(
        self,
        node: WorkflowNode,
        var_ctx: Any,
        ctx: Any = None,
    ) -> NodeResult:
        """执行节点并返回 :class:`NodeResult`。

        Args:
            node: 节点实体（含 ``config``）。
            var_ctx: 变量上下文（``VariableContext``）。
            ctx: 运行期上下文（可空）。

        Returns:
            :class:`NodeResult`。
        """
        ...


class NodeRegistry:
    """``node_type → NodeExecutor`` 注册表。

    Attributes:
        executors: 内部映射（**只读**访问请经 :meth:`get`）。
    """

    def __init__(self, executors: dict[str, NodeExecutor] | None = None) -> None:
        """初始化注册表。"""
        self.executors: dict[str, NodeExecutor] = dict(executors or {})

    def register(self, executor: NodeExecutor) -> None:
        """登记一个执行器（以 ``executor.type`` 为键；重复登记**覆盖**）。"""
        self.executors[str(executor.type)] = executor

    def get(self, node_type: str) -> NodeExecutor | None:
        """按节点类型取执行器，不存在返回 ``None``。"""
        return self.executors.get(node_type)

    def require(self, node_type: str) -> NodeExecutor:
        """按节点类型取执行器，不存在 → ``DomainError(NOT_IMPLEMENTED)``。

        Raises:
            DomainError: 未登记该节点类型（``NOT_IMPLEMENTED``）。
        """
        executor = self.get(node_type)
        if executor is None:
            raise DomainError(
                f"未登记节点执行器：{node_type}",
                code=ErrorCode.NOT_IMPLEMENTED,
                data={"reason": "executor_missing", "node_type": node_type},
            )
        return executor

    def types(self) -> tuple[str, ...]:
        """返回已登记的全部节点类型。"""
        return tuple(self.executors.keys())

    def as_mapping(self) -> dict[str, NodeExecutor]:
        """返回映射副本（供 :class:`WorkflowEngine` 构造）。"""
        return dict(self.executors)
