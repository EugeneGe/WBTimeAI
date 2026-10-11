"""``astra_workflow.engine`` 对外端口（**Protocol，零框架**；fake 可替换）。

W4 裁定 R3 §3.1 / WR-6：``engine/runtime_bridge.py`` 是**唯一** import
``astra_runtime`` / ``astra_tool`` 的模块；本模块只声明**协议**，使引擎可在**无
Runtime / 无 ORM / 无事件总线**的环境下被单测驱动（fake 注入）。

端口清单：

- :class:`RuntimeBridge`：引擎 → Runtime/Tool 的**唯一**出口（**必过**权限单一判定链）；
- :class:`ConcurrencyGuard`：并发配额（``PARALLEL`` 上限 ``max_parallel``）；
- :class:`NodeRunRecorder`：`workflow_node_run` 持久化出口（可重建数据源）；
- :class:`WorkflowEventSink`：领域事件出口（``Workflow*`` / ``Approval*``）。

每个端口均提供**空实现**（``Null*``），使引擎在最小依赖下可用。
"""

from __future__ import annotations

import contextlib
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode

from ..domain import WorkflowNode, WorkflowRun

__all__ = [
    "BRIDGE_KEY_AGENT_RUN_ID",
    "BRIDGE_KEY_TOOL_CALL_ID",
    "RuntimeBridge",
    "NullRuntimeBridge",
    "split_bridge_result",
    "ConcurrencyGuard",
    "NullConcurrencyGuard",
    "NodeRunRecorder",
    "NullNodeRunRecorder",
    "WorkflowEventSink",
    "NullWorkflowEventSink",
]


# -- RuntimeBridge 结果约定 ---------------------------------------------------

#: 桥接结果中承载 ``agent_run_id`` 的保留键（由节点执行器摘出，不计入节点 output）。
BRIDGE_KEY_AGENT_RUN_ID = "agent_run_id"
#: 桥接结果中承载 ``tool_call_id`` 的保留键。
BRIDGE_KEY_TOOL_CALL_ID = "tool_call_id"

_RESERVED_KEYS = (BRIDGE_KEY_AGENT_RUN_ID, BRIDGE_KEY_TOOL_CALL_ID)


def split_bridge_result(result: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    """拆分桥接结果：``(output, agent_run_id, tool_call_id)``。

    Args:
        result: :class:`RuntimeBridge` 返回的字典（节点 output + 可选保留键）。

    Returns:
        三元组：节点 output（**已剥离保留键**）、``agent_run_id``、``tool_call_id``。
    """
    output = {key: value for key, value in result.items() if key not in _RESERVED_KEYS}
    agent_run_id = result.get(BRIDGE_KEY_AGENT_RUN_ID)
    tool_call_id = result.get(BRIDGE_KEY_TOOL_CALL_ID)
    return (
        output,
        str(agent_run_id) if agent_run_id is not None else None,
        str(tool_call_id) if tool_call_id is not None else None,
    )


def _unsupported(kind: str) -> DomainError:
    """构造「桥接未装配」错误。"""
    return DomainError(
        f"RuntimeBridge 未装配，无法执行 {kind} 节点",
        code=ErrorCode.CONFIGURATION_ERROR,
        data={"reason": "runtime_bridge_missing", "kind": kind},
    )


# -- RuntimeBridge -----------------------------------------------------------


@runtime_checkable
class RuntimeBridge(Protocol):
    """引擎 → Runtime / Tool 的**唯一**出口（W4 裁定 §4 / WR-3）。

    🔴 节点内 ``TOOL`` / ``MCP`` **必过** ``ToolExecutor``（内建
       ``ResourcePermissionChecker``）；出网**必过** ``EgressPolicy``。本 Protocol
       只允许**转发**，不允许自建判定源。
    """

    def run_agent(
        self,
        node: WorkflowNode,
        var_ctx: Any,
        ctx: Any = None,
    ) -> dict[str, Any]:
        """执行 ``AGENT`` 节点（复用 ``AgentRuntime``，产出独立 ``agent_run``）。"""
        ...

    def execute_tool(
        self,
        node: WorkflowNode,
        var_ctx: Any,
        ctx: Any = None,
    ) -> dict[str, Any]:
        """执行 ``TOOL`` 节点（**必过** ``ToolExecutor`` + 权限单一判定链）。"""
        ...

    def execute_mcp(
        self,
        node: WorkflowNode,
        var_ctx: Any,
        ctx: Any = None,
    ) -> dict[str, Any]:
        """执行 ``MCP`` 节点（**必过** ``ToolExecutor`` + 权限单一判定链）。"""
        ...

    def resolve_checker(self, agent_id: str) -> Any:
        """解析某 Agent 的权限判定器（组合根注入的 ``permission_checker``）。"""
        ...


class NullRuntimeBridge:
    """``RuntimeBridge`` 空实现（未装配时**显式报错**，不静默放行）。"""

    def run_agent(self, node: WorkflowNode, var_ctx: Any, ctx: Any = None) -> dict[str, Any]:
        """抛出 :class:`DomainError`（``CONFIGURATION_ERROR``）。"""
        raise _unsupported("AGENT")

    def execute_tool(self, node: WorkflowNode, var_ctx: Any, ctx: Any = None) -> dict[str, Any]:
        """抛出 :class:`DomainError`（``CONFIGURATION_ERROR``）。"""
        raise _unsupported("TOOL")

    def execute_mcp(self, node: WorkflowNode, var_ctx: Any, ctx: Any = None) -> dict[str, Any]:
        """抛出 :class:`DomainError`（``CONFIGURATION_ERROR``）。"""
        raise _unsupported("MCP")

    def resolve_checker(self, agent_id: str) -> Any:
        """抛出 :class:`DomainError`（``CONFIGURATION_ERROR``）。"""
        raise _unsupported("checker")


# -- ConcurrencyGuard --------------------------------------------------------


@runtime_checkable
class ConcurrencyGuard(Protocol):
    """并发配额守卫（``PARALLEL`` 上限 ``max_parallel``；W4 裁定 §4 / N-P2-02）。"""

    def acquire(self, slots: int = 1) -> None:
        """申请 ``slots`` 个并发位；**超限即抛** ``RESOURCE_LIMIT_EXCEEDED``（不静默排队）。"""
        ...

    def release(self, slots: int = 1) -> None:
        """归还 ``slots`` 个并发位。"""
        ...


class NullConcurrencyGuard:
    """``ConcurrencyGuard`` 空实现（无配额限制；T2-23 由真实守卫替换）。"""

    def acquire(self, slots: int = 1) -> None:
        """无操作。"""

    def release(self, slots: int = 1) -> None:
        """无操作。"""


@contextlib.contextmanager
def acquire_guard(guard: ConcurrencyGuard, slots: int = 1):
    """以上下文管理器方式申请 / 归还并发位（异常亦归还）。"""
    guard.acquire(slots)
    try:
        yield
    finally:
        guard.release(slots)


# -- NodeRunRecorder ---------------------------------------------------------


@runtime_checkable
class NodeRunRecorder(Protocol):
    """``workflow_node_run`` 持久化出口（可重建数据源 ``I-P2-06``）。"""

    def add(self, node_run: Any) -> Any:
        """写入一条节点执行记录并返回（含持久化后主键）。"""
        ...

    def update(self, node_run: Any) -> Any:
        """更新一条节点执行记录并返回。"""
        ...

    def list_by_run(self, workflow_run_id: str) -> list[Any]:
        """列出某运行下的全部节点记录。"""
        ...


class NullNodeRunRecorder:
    """``NodeRunRecorder`` 空实现（内存直通；不落库）。"""

    def add(self, node_run: Any) -> Any:
        """原样返回。"""
        return node_run

    def update(self, node_run: Any) -> Any:
        """原样返回。"""
        return node_run

    def list_by_run(self, workflow_run_id: str) -> list[Any]:
        """返回空列表。"""
        return []


# -- WorkflowEventSink -------------------------------------------------------


@runtime_checkable
class WorkflowEventSink(Protocol):
    """Workflow 领域事件出口（事件**构造**由实现方负责，引擎只给语义回调）。

    W4 裁定 §6.4 #3：emit 既有 ``Workflow*`` / ``Approval*`` 事件；SSE 通道名已在
    ``encoder.py`` 冻结，**本模块不 import ``astra_event``**（该依赖归 T2-24）。
    """

    def run_started(self, run: WorkflowRun) -> None:
        """运行开始（``WorkflowStarted``）。"""
        ...

    def node_started(self, run: WorkflowRun, node_run: Any) -> None:
        """节点开始（``WorkflowNodeStarted``）。"""
        ...

    def node_completed(self, run: WorkflowRun, node_run: Any) -> None:
        """节点完成 / 挂起 / 失败（``WorkflowNodeCompleted``）。"""
        ...

    def run_completed(self, run: WorkflowRun) -> None:
        """运行成功（``WorkflowCompleted``）。"""
        ...

    def run_failed(self, run: WorkflowRun) -> None:
        """运行失败（``WorkflowFailed``）。"""
        ...


class NullWorkflowEventSink:
    """``WorkflowEventSink`` 空实现（不发事件）。"""

    def run_started(self, run: WorkflowRun) -> None:
        """无操作。"""

    def node_started(self, run: WorkflowRun, node_run: Any) -> None:
        """无操作。"""

    def node_completed(self, run: WorkflowRun, node_run: Any) -> None:
        """无操作。"""

    def run_completed(self, run: WorkflowRun) -> None:
        """无操作。"""

    def run_failed(self, run: WorkflowRun) -> None:
        """无操作。"""
