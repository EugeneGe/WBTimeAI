"""Workflow 拓扑调度 + 执行引擎（**自研轻量编排**；设计 §2.5 / W4 裁定 R3 §3.5）。

- :class:`WorkflowGraph`：版本快照的图视图（节点 / 连边 / 入口），由
  ``workflow_version.definition``（**完整图快照**）或节点/连边实体构建；
- :func:`build_graph`：构图入口；
- :class:`NodeScheduler`：拓扑排序（Kahn，**环检测**）+ 后继节点选取（CONDITION 分支）；
- :class:`WorkflowEngine`：一次运行的驱动器（``run`` / ``resume``）。

🔴 核心**不依赖 LangGraph**（自研）；引擎**不 import** ``astra_runtime`` /
``astra_tool`` / ``astra_event`` / ``astra_task``（经 :mod:`ports` 注入）。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode

from ..domain import (
    DEFAULT_ATTEMPT,
    NODE_TYPE_END,
    WORKFLOW_NODE_RUN_STATUS_PENDING,
    WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
    WorkflowVersionRepository,
)
from ..nodes import NodeContext
from .ports import (
    ConcurrencyGuard,
    NodeRunRecorder,
    NullConcurrencyGuard,
    NullNodeRunRecorder,
    NullRuntimeBridge,
    NullWorkflowEventSink,
    RuntimeBridge,
    WorkflowEventSink,
)
from .timeout import DEFAULT_MAX_STEPS, RetryPolicy, TimeoutBudget, run_with_retry
from .variables import VariableContext

__all__ = [
    "WorkflowGraph",
    "build_graph",
    "NodeScheduler",
    "WorkflowEngine",
    "NodeDispatcher",
]


# -- 图视图 -----------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowGraph:
    """Workflow 版本快照的图视图（不可变）。

    Attributes:
        version_id: 所属 ``workflow_version.id``。
        nodes: ``node_key`` → 节点实体。
        edges: 版本内全部有向连边。
        entry: 入口 ``node_key``（可空 ⇒ 空图）。
    """

    version_id: str = ""
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    edges: tuple[WorkflowEdge, ...] = ()
    entry: str | None = None

    def node_keys(self) -> list[str]:
        """返回全部 ``node_key``（按插入顺序）。"""
        return list(self.nodes.keys())

    def outgoing(self, node_key: str) -> list[WorkflowEdge]:
        """返回 ``node_key`` 的全部出边（按定义顺序）。"""
        return [edge for edge in self.edges if edge.from_node_key == node_key]

    def next_keys(self, node_key: str, branch: str | None = None) -> list[str]:
        """返回 ``node_key`` 的后继节点键。

        分支语义（``CONDITION`` 节点）：

        - ``branch`` 非空 → 取 ``condition == branch`` 的连边；无命中时回退**无条件**连边；
        - ``branch`` 为空 → 取**无条件**连边（``condition`` 为空）。

        Args:
            node_key: 当前节点键。
            branch: 选中的分支名（``CONDITION`` 节点产出）。

        Returns:
            后继 ``node_key`` 列表（无后继时为空）。
        """
        candidates = self.outgoing(node_key)
        if not candidates:
            return []
        if branch:
            matched = [edge for edge in candidates if edge.condition == branch]
            if matched:
                return [edge.to_node_key for edge in matched]
        unconditional = [edge for edge in candidates if not edge.condition]
        return [edge.to_node_key for edge in unconditional]

    def topo_order(self) -> list[str]:
        """返回拓扑序（Kahn）；**有环** → ``DomainError(VALIDATION_ERROR)``。

        Raises:
            DomainError: 图中有环（``VALIDATION_ERROR``，``reason="cycle"``）。
        """
        indegree: dict[str, int] = {key: 0 for key in self.nodes}
        adjacency: dict[str, list[str]] = {key: [] for key in self.nodes}
        for edge in self.edges:
            if edge.from_node_key not in indegree or edge.to_node_key not in indegree:
                continue
            adjacency[edge.from_node_key].append(edge.to_node_key)
            indegree[edge.to_node_key] += 1

        queue: deque[str] = deque(sorted(key for key, degree in indegree.items() if degree == 0))
        ordered: list[str] = []
        while queue:
            key = queue.popleft()
            ordered.append(key)
            for target in adjacency[key]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if len(ordered) != len(self.nodes):
            raise DomainError(
                "Workflow 图存在环，无法拓扑排序",
                code=ErrorCode.VALIDATION_ERROR,
                data={
                    "reason": "cycle",
                    "resolved": len(ordered),
                    "total": len(self.nodes),
                },
            )
        return ordered


def build_graph(
    version: WorkflowVersion,
    nodes: list[WorkflowNode] | None = None,
    edges: list[WorkflowEdge] | None = None,
) -> WorkflowGraph:
    """构建 :class:`WorkflowGraph`。

    优先使用显式传入的节点 / 连边实体；缺省时**回退**到 ``version.definition``
    （**完整图快照**，``I-P2-06`` 可重建性的数据源）。

    Args:
        version: 版本实体（提供 ``definition`` 与 ``id``）。
        nodes: 可选节点实体列表（来自 ``workflow_node`` 表）。
        edges: 可选连边实体列表（来自 ``workflow_edge`` 表）。

    Returns:
        :class:`WorkflowGraph`。
    """
    if nodes is not None or edges is not None:
        node_list = list(nodes or [])
        edge_list = list(edges or [])
        entry = node_list[0].node_key if node_list else None
        return WorkflowGraph(
            version_id=version.id,
            nodes={node.node_key: node for node in node_list},
            edges=tuple(edge_list),
            entry=entry,
        )

    definition_nodes = version.definition_nodes()
    definition_edges = version.definition_edges()
    built_nodes: dict[str, WorkflowNode] = {}
    for item in definition_nodes:
        key = str(item.get("key") or "")
        if not key:
            continue
        built_nodes[key] = WorkflowNode(
            workflow_version_id=version.id,
            node_key=key,
            type=str(item.get("type") or ""),
            config=dict(item.get("config") or {}),
            position=dict(item.get("position") or {}),
        )
    built_edges = tuple(
        WorkflowEdge(
            workflow_version_id=version.id,
            from_node_key=str(item.get("from") or ""),
            to_node_key=str(item.get("to") or ""),
            condition=item.get("condition"),
        )
        for item in definition_edges
    )
    return WorkflowGraph(
        version_id=version.id,
        nodes=built_nodes,
        edges=built_edges,
        entry=version.entry_node_key(),
    )


class NodeDispatcher:
    """子节点分派器（``PARALLEL`` / ``LOOP`` 驱动子体用）。

    由引擎**按 run** 构造：闭包捕获 ``(engine, run, graph, ctx)``，**无共享可变状态**，
    故可被 ``PARALLEL`` 的分支并发安全调用。
    """

    def __init__(
        self,
        engine: WorkflowEngine,
        run: WorkflowRun,
        graph: WorkflowGraph,
        ctx: NodeContext,
    ) -> None:
        """初始化分派器。"""
        self._engine = engine
        self._run = run
        self._graph = graph
        self._ctx = ctx

    def dispatch(
        self,
        node_key: str,
        var_ctx: VariableContext,
        ctx: Any = None,
        *,
        attempt: int = DEFAULT_ATTEMPT,
    ) -> Any:
        """按 ``node_key`` 执行子节点（**各产生独立 ``node_run``**）。

        Raises:
            DomainError: ``node_key`` 不在图中（``NOT_FOUND``）。
        """
        node = self._graph.nodes.get(node_key)
        if node is None:
            raise DomainError(
                f"节点不存在于图中：{node_key}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "node_not_found", "node_key": node_key},
            )
        return self._engine.execute_node(
            self._run,
            node,
            var_ctx,
            ctx if ctx is not None else self._ctx,
            attempt=attempt,
        )


@dataclass(frozen=True)
class NodeScheduler:
    """节点调度器（拓扑排序 + 后继选取；``I-P2-05``）。

    Attributes:
        graph: 图视图。
    """

    graph: WorkflowGraph

    def order(self) -> list[str]:
        """返回拓扑序（**有环即抛**）。"""
        return self.graph.topo_order()

    def entry(self) -> str | None:
        """返回入口 ``node_key``。"""
        return self.graph.entry

    def successors(self, node_key: str, branch: str | None = None) -> list[str]:
        """返回 ``node_key`` 的后继（含 ``CONDITION`` 分支选取）。"""
        return self.graph.next_keys(node_key, branch)


# -- 执行引擎 ---------------------------------------------------------------


class WorkflowEngine:
    """Workflow 执行引擎（**自研轻量编排**，核心不依赖 LangGraph）。

    职责边界（W4 裁定 §4 / R7）：

    - 引擎**只驱动**节点执行与状态机，**不**持久化 ``workflow_run``（由 Application
      ``WorkflowService`` 负责），**不**发真实领域事件（经 :class:`WorkflowEventSink`
      端口外抛）；
    - 节点内 ``TOOL`` / ``MCP`` 执行**必过** :class:`RuntimeBridge` → ``ToolExecutor``
      （权限单一判定链），引擎**不自建**判定源。
    """

    def __init__(
        self,
        executors: Mapping[str, Any],
        *,
        versions: WorkflowVersionRepository | None = None,
        recorder: NodeRunRecorder | None = None,
        sink: WorkflowEventSink | None = None,
        bridge: RuntimeBridge | None = None,
        concurrency: ConcurrencyGuard | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        run_timeout_ms: int | None = None,
    ) -> None:
        """初始化引擎。

        Args:
            executors: ``node_type → NodeExecutor`` 映射（见 ``nodes/base.py``）。
            versions: 版本仓储（``resume`` 时回读版本快照）；缺省 ``None``。
            recorder: 节点记录持久化端口；缺省 :class:`NullNodeRunRecorder`。
            sink: 事件出口；缺省 :class:`NullWorkflowEventSink`。
            bridge: Runtime 桥接；缺省 :class:`NullRuntimeBridge`。
            concurrency: 并发守卫；缺省 :class:`NullConcurrencyGuard`。
            max_steps: 单次运行的**最大节点步数**（有界，防无界循环）。
            run_timeout_ms: Run 级时间预算（``None`` = 不限）。
        """
        self._executors: dict[str, Any] = dict(executors)
        self._versions = versions
        self._recorder: NodeRunRecorder = (
            recorder if recorder is not None else NullNodeRunRecorder()
        )
        self._sink: WorkflowEventSink = sink if sink is not None else NullWorkflowEventSink()
        self._bridge: RuntimeBridge = bridge if bridge is not None else NullRuntimeBridge()
        self._concurrency: ConcurrencyGuard = (
            concurrency if concurrency is not None else NullConcurrencyGuard()
        )
        self._max_steps = max(1, int(max_steps))
        self._run_timeout_ms = run_timeout_ms

    # -- 只读属性 / 后期绑定（供节点、运行形态与测试使用） --------------------

    @property
    def recorder(self) -> NodeRunRecorder:
        """节点记录持久化端口（可重建数据源）。"""
        return self._recorder

    def bind_recorder(self, recorder: NodeRunRecorder) -> None:
        """**后期绑定**节点记录持久化端口（W4 / T2-24）。

        引擎通常在组合根先于仓储装配（``build_workflow_engine`` 时 ``recorder`` 可能
        仍未知），故运行形态（:class:`~astra_workflow.run.InlineRunner`）拿到
        ``WorkflowNodeRunRepository`` 后经本方法回填——使引擎保持**零 ORM**，
        持久化仍经 Protocol 端口外抛。

        Args:
            recorder: 节点记录持久化端口（不可为空）。
        """
        self._recorder = recorder

    @property
    def bridge(self) -> RuntimeBridge:
        """Runtime 桥接（节点内执行**唯一**出口）。"""
        return self._bridge

    @property
    def concurrency(self) -> ConcurrencyGuard:
        """并发守卫（``PARALLEL`` 上限）。"""
        return self._concurrency

    @property
    def max_steps(self) -> int:
        """单次运行最大节点步数。"""
        return self._max_steps

    # -- 主入口 -------------------------------------------------------------

    def run(
        self,
        version: WorkflowVersion,
        run_input: dict[str, Any] | None = None,
        *,
        ctx: Any | None = None,
        run: WorkflowRun | None = None,
    ) -> WorkflowRun:
        """驱动一次 Workflow 运行。

        Args:
            version: 版本快照（**不可变**；``workflow_run`` 固定引用它）。
            run_input: 运行入参（``${input.xxx}`` 可见）。
            ctx: 运行期上下文（由 Application / Worker 透传给节点，可空）。
            run: 复用既有 ``WorkflowRun``（由 Application 预建）；缺省新建。

        Returns:
            终态或 ``WAITING_APPROVAL`` 的 :class:`WorkflowRun`。

        Raises:
            DomainError: 版本未发布（``VALIDATION_ERROR``）/ 图有环 / 节点类型无执行器。
        """
        if version.status != WORKFLOW_VERSION_STATUS_PUBLISHED:
            raise DomainError(
                f"WorkflowVersion 尚未发布，不可运行：{version.status}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "version_not_published", "workflow_version_id": version.id},
            )
        graph = build_graph(version)
        scheduler = NodeScheduler(graph)
        scheduler.order()  # 有环即抛

        target = run if run is not None else WorkflowRun(workflow_version_id=version.id)
        target.workflow_version_id = version.id
        if target.input is None:
            target.input = dict(run_input or {})
        target.start()
        self._sink.run_started(target)

        var_ctx = VariableContext(inputs=dict(target.input or {}))
        entry = scheduler.entry()
        start_keys = [entry] if entry else []
        return self._drive(
            target,
            graph,
            var_ctx,
            start_keys,
            ctx,
            attempt_of=None,
        )

    def resume(self, run: WorkflowRun, *, ctx: Any | None = None) -> WorkflowRun:
        """自 ``WAITING_APPROVAL`` 续跑（审批决议后；W4 裁定 §3.2 / §4）。

        变量上下文自 ``workflow_run.output`` **重建**（``I-P2-06``）；从**挂起节点**
        以 ``attempt + 1`` 重新执行并继续后续拓扑。

        Args:
            run: 处于 ``WAITING_APPROVAL`` 的运行。
            ctx: 运行期上下文（可空）。

        Returns:
            续跑后的 :class:`WorkflowRun`。

        Raises:
            DomainError: 运行不在 ``WAITING_APPROVAL``；或版本仓储缺失 / 版本不存在。
        """
        if run.status != WORKFLOW_RUN_STATUS_WAITING_APPROVAL:
            raise DomainError(
                f"仅 WAITING_APPROVAL 状态可续跑：{run.status}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "not_waiting_approval", "workflow_run_id": run.id},
            )
        if self._versions is None:
            raise DomainError(
                "续跑需版本仓储（versions）以回读不可变版本快照",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "versions_repository_missing"},
            )
        version = self._versions.get(run.workflow_version_id)
        if version is None:
            raise DomainError(
                f"续跑目标版本不存在：{run.workflow_version_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_version_not_found"},
            )

        graph = build_graph(version)
        scheduler = NodeScheduler(graph)
        scheduler.order()

        suspended: WorkflowNodeRun | None = None
        for node_run in self._recorder.list_by_run(run.id):
            if node_run.status == WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL:
                suspended = node_run
                break

        var_ctx = VariableContext.from_snapshot(run.output)
        run.resume()

        start_keys: list[str] = []
        attempt_of: dict[str, int] = {}
        if suspended is not None:
            start_keys = [suspended.node_key]
            attempt_of[suspended.node_key] = int(suspended.attempt or DEFAULT_ATTEMPT) + 1
        elif scheduler.entry() is not None:
            start_keys = [str(scheduler.entry())]

        return self._drive(run, graph, var_ctx, start_keys, ctx, attempt_of=attempt_of)

    # -- 内部驱动 -----------------------------------------------------------

    def _drive(
        self,
        run: WorkflowRun,
        graph: WorkflowGraph,
        var_ctx: VariableContext,
        start_keys: list[str],
        ctx: Any | None,
        *,
        attempt_of: Mapping[str, int] | None,
    ) -> WorkflowRun:
        """按拓扑驱动节点执行（BFS，确定性顺序）。"""
        budget = TimeoutBudget(self._run_timeout_ms)
        queue: deque[str] = deque(start_keys)
        steps = 0
        node_ctx = self._ensure_context(run, graph, ctx)

        while queue:
            steps += 1
            if steps > self._max_steps:
                return self._finish_failed(run, "MAX_STEPS_EXCEEDED", var_ctx)
            node_key = queue.popleft()
            node = graph.nodes.get(node_key)
            if node is None:
                continue
            if node.type == NODE_TYPE_END:
                continue

            try:
                budget.assert_not_expired()
                result = self._execute_node(run, node, var_ctx, node_ctx, dict(attempt_of or {}))
            except DomainError as error:
                return self._finish_failed(run, str(error.code), var_ctx)
            except Exception as error:  # noqa: BLE001 - 收敛为 FAILED 终态
                return self._finish_failed(run, f"{type(error).__name__}: {error}", var_ctx)

            var_ctx.set_output(node_key, result.output)
            run.output = {"outputs": dict(var_ctx.outputs), "cursor": node_key}

            if result.status == WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL:
                # 挂起为**非终态**：不发 run_failed，交由审批决议后续跑。
                run.wait_approval()
                return run

            if result.failed:
                return self._finish_failed(run, result.error or "NODE_FAILED", var_ctx)

            for successor in graph.next_keys(node_key, result.next_branch):
                queue.append(successor)

        run.succeed({"outputs": dict(var_ctx.outputs)})
        self._sink.run_completed(run)
        return run

    def execute_node(
        self,
        run: WorkflowRun,
        node: WorkflowNode,
        var_ctx: VariableContext,
        ctx: Any | None = None,
        *,
        attempt: int = DEFAULT_ATTEMPT,
    ) -> Any:
        """**公开**执行单个节点（供 ``NodeDispatcher`` 驱动子分支 / 循环体）。

        每个节点**独立**产生一条 ``workflow_node_run``（``I-P2-06`` 重放数据源）。

        Args:
            run: 所属运行。
            node: 节点实体。
            var_ctx: 变量上下文。
            ctx: 节点上下文（``NodeContext``）。
            attempt: 尝试序号。

        Returns:
            节点的 ``NodeResult``。
        """
        return self._execute_node(run, node, var_ctx, ctx, {node.node_key: attempt})

    def _ensure_context(
        self, run: WorkflowRun, graph: WorkflowGraph, ctx: Any | None
    ) -> NodeContext:
        """构造 / 补全**按 run** 的节点上下文（含子体分派器）。"""
        node_ctx = (
            ctx
            if isinstance(ctx, NodeContext)
            else NodeContext(run_id=run.id, tenant_id=run.tenant_id, data={"caller": ctx})
        )
        node_ctx.run_id = run.id
        node_ctx.tenant_id = run.tenant_id
        node_ctx.workflow_run = run
        node_ctx.graph = graph
        node_ctx.dispatcher = NodeDispatcher(self, run, graph, node_ctx)
        return node_ctx

    def _execute_node(
        self,
        run: WorkflowRun,
        node: WorkflowNode,
        var_ctx: VariableContext,
        ctx: Any | None,
        attempt_of: Mapping[str, int],
    ) -> Any:
        """执行单个节点并写入 ``workflow_node_run``。"""
        executor = self._executors.get(node.type)
        if executor is None:
            raise DomainError(
                f"节点类型无执行器：{node.type}",
                code=ErrorCode.NOT_IMPLEMENTED,
                data={"reason": "executor_missing", "node_type": node.type},
            )

        attempt = int(attempt_of.get(node.node_key, DEFAULT_ATTEMPT))
        node_run = WorkflowNodeRun(
            workflow_run_id=run.id,
            node_key=node.node_key,
            attempt=attempt,
            status=WORKFLOW_NODE_RUN_STATUS_PENDING,
            input=self._node_input(node, var_ctx),
        )
        node_run = self._recorder.add(node_run)
        node_run.start()
        self._recorder.update(node_run)
        self._sink.node_started(run, node_run)

        policy = RetryPolicy.from_config(node.config)
        budget = TimeoutBudget(self._run_timeout_ms)

        def once() -> Any:
            return executor.execute(node, var_ctx, ctx)

        result = run_with_retry(once, policy=policy, budget=budget)

        node_run.output = dict(result.output or {})
        node_run.agent_run_id = result.agent_run_id or node_run.agent_run_id
        node_run.tool_call_id = result.tool_call_id or node_run.tool_call_id
        if result.approval_id:
            node_run.approval_id = result.approval_id
        if result.status == WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL:
            node_run.wait_approval(result.approval_id)
        elif result.failed:
            node_run.fail(result.output)
        else:
            node_run.succeed(result.output)
        node_run = self._recorder.update(node_run)
        self._sink.node_completed(run, node_run)
        return result

    def _finish_failed(self, run: WorkflowRun, error: str, var_ctx: VariableContext) -> WorkflowRun:
        """以 ``FAILED`` 终态收束运行。"""
        run.output = {"outputs": dict(var_ctx.outputs)}
        if run.status != WORKFLOW_RUN_STATUS_WAITING_APPROVAL:
            run.fail(error)
        self._sink.run_failed(run)
        return run

    @staticmethod
    def _node_input(node: WorkflowNode, var_ctx: VariableContext) -> dict[str, Any]:
        """解析节点入参（``config`` 中声明的引用表达式）。"""
        raw = node.config.get("input")
        if isinstance(raw, dict):
            return dict(var_ctx.resolve_value(raw))
        if isinstance(raw, str):
            resolved = var_ctx.resolve_value(raw)
            return {"value": resolved} if not isinstance(resolved, dict) else dict(resolved)
        return {}
