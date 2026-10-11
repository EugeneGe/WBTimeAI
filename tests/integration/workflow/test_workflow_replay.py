"""Workflow 运行形态 / 可重建集成测试（W4 / T2-24）。

覆盖（W4 裁定 §5 T2-24 验收）：

- ``INLINE`` 同步路径：``InlineRunner.execute`` 驱动引擎至终态，并落
  ``workflow_run`` / ``workflow_node_run``；
- ``QUEUED`` 异步路径：``QueuedRunner.enqueue`` 建 ``task(PENDING,
  type=workflow.run)`` 挂到 ``WorkflowRun.task_id`` 并入队（**不执行**）；
  Worker 侧 ``execute`` 经注入回调驱动；
- **可重建（``I-P2-06``）**：``ReplayService.replay`` 由持久化记录构造快照，
  **重放 == golden**；``assert_replay_matches_golden`` 不一致即抛；
- 版本引用**固定**：重放回读的 ``workflow_version_id`` 与执行时**恒定**；
- 事件流：``EventBusWorkflowEventSink`` 走**既有** ``Workflow*`` 事件类型。

🔴 分层：``astra_workflow.run`` **不 import** ``astra_api``（能力包禁 Web）；
   SSE 编码 / 通道映射复用既有 ``sse/`` 实现，**不改** ``encoder.py``（F14/R9）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_event import (
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowNodeCompleted,
    WorkflowNodeStarted,
    WorkflowStarted,
)
from astra_workflow import (
    DEFAULT_ATTEMPT,
    NODE_TYPE_END,
    NODE_TYPE_HUMAN_APPROVAL,
    NODE_TYPE_TOOL,
    WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
    WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_RUN_STATUS_FAILED,
    WORKFLOW_RUN_STATUS_PENDING,
    WORKFLOW_RUN_STATUS_RUNNING,
    WORKFLOW_RUN_STATUS_SUCCEEDED,
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_TRIGGER_API,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
    build_definition,
)
from astra_workflow.engine import VariableContext, WorkflowEngine
from astra_workflow.nodes import EndNode, HumanApprovalNode, NodeRegistry, NodeResult
from astra_workflow.run import (
    WORKFLOW_TASK_TYPE,
    EventBusWorkflowEventSink,
    InlineRunner,
    QueuedRunner,
    ReplayService,
    WorkflowReplay,
    assert_replay_matches_golden,
)

from tests.unit.runtime_stubs import EchoTool, allow_tool

# -- 内存仓储 / 桩件 ----------------------------------------------------------


class _MemoryRunRepository:
    """内存版 ``WorkflowRunRepository``。"""

    def __init__(self) -> None:
        self.rows: dict[str, WorkflowRun] = {}

    def get(self, entity_id: str) -> WorkflowRun | None:
        return self.rows.get(entity_id)

    def add(self, entity: WorkflowRun) -> WorkflowRun:
        self.rows[entity.id] = entity
        return entity

    def update(self, entity: WorkflowRun) -> WorkflowRun:
        self.rows[entity.id] = entity
        return entity

    def list(self, **filters: Any) -> list[WorkflowRun]:
        return self._filter(self.rows.values(), filters)

    def delete(self, entity: WorkflowRun) -> None:
        self.rows.pop(entity.id, None)

    def list_by_version(self, workflow_version_id: str) -> list[WorkflowRun]:
        return [r for r in self.rows.values() if r.workflow_version_id == workflow_version_id]

    def list_by_tenant(self, tenant_id: str) -> list[WorkflowRun]:
        return [r for r in self.rows.values() if r.tenant_id == tenant_id]

    def list_by_status(self, tenant_id: str, status: str) -> list[WorkflowRun]:
        return [r for r in self.rows.values() if r.tenant_id == tenant_id and r.status == status]

    @staticmethod
    def _filter(rows: Any, filters: dict[str, Any]) -> list[Any]:
        return [
            row
            for row in rows
            if all(getattr(row, key, None) == value for key, value in filters.items())
        ]


class _MemoryNodeRunRepository:
    """内存版 ``WorkflowNodeRunRepository``（保持插入顺序，供重放断言）。"""

    def __init__(self) -> None:
        self.rows: list[WorkflowNodeRun] = []

    def get(self, entity_id: str) -> WorkflowNodeRun | None:
        for row in self.rows:
            if row.id == entity_id:
                return row
        return None

    def add(self, entity: WorkflowNodeRun) -> WorkflowNodeRun:
        self.rows.append(entity)
        return entity

    def update(self, entity: WorkflowNodeRun) -> WorkflowNodeRun:
        for index, row in enumerate(self.rows):
            if row.id == entity.id:
                self.rows[index] = entity
                return entity
        self.rows.append(entity)
        return entity

    def list(self, **filters: Any) -> list[WorkflowNodeRun]:
        return [
            row
            for row in self.rows
            if all(getattr(row, key, None) == value for key, value in filters.items())
        ]

    def delete(self, entity: WorkflowNodeRun) -> None:
        self.rows = [row for row in self.rows if row.id != entity.id]

    def list_by_run(self, workflow_run_id: str) -> list[WorkflowNodeRun]:
        return [row for row in self.rows if row.workflow_run_id == workflow_run_id]

    def get_by_node(
        self, workflow_run_id: str, node_key: str, attempt: int = DEFAULT_ATTEMPT
    ) -> WorkflowNodeRun | None:
        for row in self.rows:
            if (
                row.workflow_run_id == workflow_run_id
                and row.node_key == node_key
                and int(row.attempt or DEFAULT_ATTEMPT) == attempt
            ):
                return row
        return None


class _MemoryVersionRepository:
    """内存版 ``WorkflowVersionRepository``。"""

    def __init__(self, versions: dict[str, WorkflowVersion] | None = None) -> None:
        self._versions: dict[str, WorkflowVersion] = dict(versions or {})

    def get(self, entity_id: str) -> WorkflowVersion | None:
        return self._versions.get(entity_id)

    def add(self, entity: WorkflowVersion) -> WorkflowVersion:
        self._versions[entity.id] = entity
        return entity

    def update(self, entity: WorkflowVersion) -> WorkflowVersion:
        self._versions[entity.id] = entity
        return entity

    def list(self, **filters: Any) -> list[WorkflowVersion]:
        return list(self._versions.values())

    def delete(self, entity: WorkflowVersion) -> None:
        self._versions.pop(entity.id, None)

    def list_by_workflow(self, workflow_id: str) -> list[WorkflowVersion]:
        return [v for v in self._versions.values() if v.workflow_id == workflow_id]

    def get_by_version(self, workflow_id: str, version: str) -> WorkflowVersion | None:
        for item in self._versions.values():
            if item.workflow_id == workflow_id and item.version == version:
                return item
        return None


@dataclass
class _EchoExecutor:
    """把 ``config`` 回显为 output 的 fake 执行器。"""

    type: str
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        self.calls.append(node.node_key)
        payload = self.outputs.get(node.node_key, {"echo": node.node_key})
        return NodeResult.success(payload)


@dataclass
class _FakeApproval:
    """审批记录桩件（``id`` 供 ``workflow_node_run.approval_id`` 关联）。"""

    id: str = ""


class _ApprovalGateway:
    """记录审批请求的 fake ``ApprovalGateway``。"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._seq = 0

    def request(
        self,
        *,
        subject_type: str,
        subject_ref: str,
        payload: dict[str, Any] | None = None,
        requested_by: str | None = None,
        expires_at: Any | None = None,
        tenant_id: str | None = None,
    ) -> Any:
        """发起一条审批并返回带 ``id`` 的记录。"""
        self._seq += 1
        self.requests.append(
            {
                "subject_type": subject_type,
                "subject_ref": subject_ref,
                "payload": dict(payload or {}),
                "requested_by": requested_by,
                "expires_at": expires_at,
                "tenant_id": tenant_id,
            }
        )
        return _FakeApproval(id=f"approval-{self._seq}")

    def find_by_subject_ref(self, *, subject_type: str, subject_ref: str) -> Any | None:
        """无既有审批（单次执行场景）——满足 ``ApprovalGateway``（T2-26 加性）。"""
        return None


class _RecordingBus:
    """记录已发布事件的 fake ``EventBus``。"""

    def __init__(self) -> None:
        self.published: list[Any] = []

    def publish(self, event: Any) -> None:
        self.published.append(event)

    def subscribe(self, event_type: str, handler: Any) -> None:
        return None

    def unsubscribe(self, event_type: str, handler: Any) -> None:
        return None


# -- 装配辅助 -----------------------------------------------------------------


def _node(key: str, node_type: str, **config: Any) -> WorkflowNode:
    """构造节点实体。"""
    return WorkflowNode(
        workflow_version_id="wv-1", node_key=key, type=node_type, config=dict(config)
    )


def _version(
    nodes: list[WorkflowNode], edges: list[WorkflowEdge], *, entry: str | None = None
) -> WorkflowVersion:
    """构造已发布版本（``definition`` 为完整图快照）。"""
    return WorkflowVersion(
        id="wv-1",
        workflow_id="wf-1",
        version="v1",
        definition=build_definition(nodes, edges, entry=entry),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by="u-1",
    )


def _build_engine(executors: list[Any]) -> WorkflowEngine:
    """由 fake 执行器装配引擎（桥接未装配 → 显式报错语义不需要）。"""
    registry = NodeRegistry()
    for executor in executors:
        registry.register(executor)
    return WorkflowEngine(registry.as_mapping())


def _build_runner(
    engine: WorkflowEngine,
    runs: _MemoryRunRepository,
    *,
    versions: _MemoryVersionRepository,
    node_runs: _MemoryNodeRunRepository | None = None,
    sink: Any = None,
    event_reader: Any = None,
) -> InlineRunner:
    """装配内联运行器。"""
    return InlineRunner(
        engine,
        runs,
        node_runs=node_runs,
        versions=versions,
        sink=sink,
        event_reader=event_reader,
    )


# -- INLINE -------------------------------------------------------------------


def test_inline_runner_executes_to_succeeded() -> None:
    """``INLINE`` 同步路径：驱动引擎至 ``SUCCEEDED`` 并落 ``workflow_run``。"""
    nodes = [_node("t1", NODE_TYPE_TOOL, tool="echo"), _node("end", NODE_TYPE_END)]
    edges = [WorkflowEdge(workflow_version_id="wv-1", from_node_key="t1", to_node_key="end")]
    version = _version(nodes, edges, entry="t1")
    versions = _MemoryVersionRepository({version.id: version})
    runs = _MemoryRunRepository()
    node_runs = _MemoryNodeRunRepository()

    runner = _build_runner(
        _build_engine([_EchoExecutor(NODE_TYPE_TOOL), EndNode()]),
        runs,
        versions=versions,
        node_runs=node_runs,
    )
    run = WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1")
    runs.add(run)

    executed = runner.execute("run-1")
    assert executed.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    assert executed.workflow_version_id == "wv-1"
    assert [row.node_key for row in node_runs.list_by_run("run-1")] == ["t1"]


def test_inline_runner_unknown_run_raises_not_found() -> None:
    """运行不存在 → ``NOT_FOUND``（不静默成功）。"""
    runner = _build_runner(
        _build_engine([EndNode()]),
        _MemoryRunRepository(),
        versions=_MemoryVersionRepository(),
    )
    with pytest.raises(DomainError) as excinfo:
        runner.execute("missing")
    assert excinfo.value.code == ErrorCode.NOT_FOUND


def test_inline_runner_missing_versions_raises_configuration_error() -> None:
    """版本仓储未装配 → ``CONFIGURATION_ERROR``（不可重建即失败）。"""
    runs = _MemoryRunRepository()
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1"))
    runner = InlineRunner(_build_engine([EndNode()]), runs)

    with pytest.raises(DomainError) as excinfo:
        runner.execute("run-1")
    assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR


def test_inline_runner_cancel_sets_terminal_status() -> None:
    """取消运行 → ``CANCELLED`` 终态并落库。"""
    runs = _MemoryRunRepository()
    runs.add(
        WorkflowRun(
            id="run-1",
            workflow_version_id="wv-1",
            tenant_id="tenant-1",
            status=WORKFLOW_RUN_STATUS_RUNNING,
        )
    )
    runner = _build_runner(_build_engine([EndNode()]), runs, versions=_MemoryVersionRepository())

    cancelled = runner.cancel("run-1")
    assert cancelled.status == "CANCELLED"
    assert runs.get("run-1") is not None
    assert runs.get("run-1").status == "CANCELLED"
    # 幂等：重复取消不报错且状态不变。
    assert runner.cancel("run-1").status == "CANCELLED"


def test_inline_runner_run_status_and_events() -> None:
    """``run_status`` 读状态；``list_events`` 走注入读取器（未注入 → 空，不伪造）。"""
    runs = _MemoryRunRepository()
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1"))

    empty = _build_runner(_build_engine([EndNode()]), runs, versions=_MemoryVersionRepository())
    assert empty.run_status("run-1") == WORKFLOW_RUN_STATUS_PENDING
    assert empty.run_status("missing") is None
    assert empty.list_events("run-1") == []

    wired = _build_runner(
        _build_engine([EndNode()]),
        runs,
        versions=_MemoryVersionRepository(),
        event_reader=lambda run_id, last: (
            [{"seq": 1, "type": "workflow.started"}] if last is None else []
        ),
    )
    assert wired.list_events("run-1")[0]["type"] == "workflow.started"
    assert wired.list_events("run-1", 1) == []


# -- QUEUED -------------------------------------------------------------------


def test_queued_runner_enqueues_without_executing() -> None:
    """``QUEUED``：建 ``task(PENDING, workflow.run)`` 挂到 Run 并入队，**不执行**。"""
    runs = _MemoryRunRepository()
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1"))

    enqueued: list[dict[str, Any]] = []
    tasks: list[Any] = []

    class _Tasks:
        def add(self, task: Any) -> Any:
            tasks.append(task)
            return task

        def update(self, task: Any) -> Any:
            return task

    class _Queue:
        def enqueue(self, item: Any) -> None:
            enqueued.append(dict(item))

    runner = QueuedRunner(runs, tasks=_Tasks(), queue=_Queue())
    result = runner.enqueue("run-1", payload={"tenant_id": "tenant-1"})

    assert result.task_id, "入队后 Run 必须挂到 task"
    assert len(tasks) == 1
    assert tasks[0].type == WORKFLOW_TASK_TYPE
    assert enqueued[0]["handler"] == WORKFLOW_TASK_TYPE
    assert enqueued[0]["payload"]["workflow_run_id"] == "run-1"


def test_queued_runner_requires_queue() -> None:
    """队列未装配 → ``CONFIGURATION_ERROR``。"""
    runs = _MemoryRunRepository()
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1"))

    class _Tasks:
        def add(self, task: Any) -> Any:
            return task

        def update(self, task: Any) -> Any:
            return task

    with pytest.raises(DomainError) as excinfo:
        QueuedRunner(runs, tasks=_Tasks(), queue=None).enqueue("run-1")
    assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR


def test_queued_runner_execute_delegates_to_executor() -> None:
    """Worker 侧 ``execute`` 委派给注入回调（Application ``WorkflowService.execute``）。"""
    runs = _MemoryRunRepository()
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1"))
    calls: list[str] = []

    def _executor(run_id: str) -> Any:
        calls.append(run_id)
        return WorkflowRun(
            id=run_id,
            workflow_version_id="wv-1",
            tenant_id="tenant-1",
            status=WORKFLOW_RUN_STATUS_SUCCEEDED,
        )

    runner = QueuedRunner(runs, executor=_executor)
    result = runner.execute("run-1")
    assert calls == ["run-1"]
    assert result.status == WORKFLOW_RUN_STATUS_SUCCEEDED


# -- 可重建（I-P2-06） --------------------------------------------------------


def _simple_graph_run() -> (
    tuple[WorkflowRun, _MemoryRunRepository, _MemoryNodeRunRepository, _MemoryVersionRepository]
):
    """构造并同步执行一次「t1 → end」图，返回 (run, runs, node_runs, versions)。"""
    nodes = [_node("t1", NODE_TYPE_TOOL, tool="echo"), _node("end", NODE_TYPE_END)]
    edges = [WorkflowEdge(workflow_version_id="wv-1", from_node_key="t1", to_node_key="end")]
    version = _version(nodes, edges, entry="t1")
    versions = _MemoryVersionRepository({version.id: version})
    runs = _MemoryRunRepository()
    node_runs = _MemoryNodeRunRepository()

    runner = _build_runner(
        _build_engine([_EchoExecutor(NODE_TYPE_TOOL), EndNode()]),
        runs,
        versions=versions,
        node_runs=node_runs,
    )
    run = WorkflowRun(
        id="run-1",
        workflow_version_id="wv-1",
        tenant_id="tenant-1",
        trigger=WORKFLOW_TRIGGER_API,
        input={"q": "hello"},
    )
    runs.add(run)
    executed = runner.execute("run-1")
    return executed, runs, node_runs, versions


def test_replay_reconstructs_full_snapshot() -> None:
    """重放由 ``workflow_run`` + ``workflow_node_run`` 构造**完整**快照。"""
    run, _runs, node_runs, versions = _simple_graph_run()
    service = ReplayService(_runs, node_runs, versions=versions)

    replay = service.replay("run-1")
    assert isinstance(replay, WorkflowReplay)
    assert replay.run_id == "run-1"
    # 🔴 可重建不变量：版本引用**固定**（经不可变快照回读 workflow_id）。
    assert replay.workflow_version_id == run.workflow_version_id == "wv-1"
    assert replay.workflow_id == "wf-1"
    assert replay.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    assert replay.input == {"q": "hello"}
    assert [node.node_key for node in replay.nodes] == ["t1"]
    assert replay.nodes[0].status == WORKFLOW_NODE_RUN_STATUS_SUCCEEDED


def test_replay_equals_golden_snapshot() -> None:
    """**重放 == golden**（``I-P2-06``）：逐字段断言，不一致即抛。"""
    _run, _runs, node_runs, versions = _simple_graph_run()
    service = ReplayService(_runs, node_runs, versions=versions)

    replay = service.replay("run-1")
    golden = {
        "run_id": "run-1",
        "workflow_id": "wf-1",
        "workflow_version_id": "wv-1",
        "status": WORKFLOW_RUN_STATUS_SUCCEEDED,
        "trigger": WORKFLOW_TRIGGER_API,
        "input": {"q": "hello"},
        "nodes": [
            {
                "node_key": "t1",
                "status": WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
                "attempt": DEFAULT_ATTEMPT,
                "output": {"echo": "t1"},
            }
        ],
    }
    # 逐字段比对（golden 只给关键字段，故逐项断言而非整体相等）。
    actual = replay.to_dict()
    assert actual["run_id"] == golden["run_id"]
    assert actual["workflow_id"] == golden["workflow_id"]
    assert actual["workflow_version_id"] == golden["workflow_version_id"]
    assert actual["status"] == golden["status"]
    assert actual["trigger"] == golden["trigger"]
    assert actual["input"] == golden["input"]
    assert len(actual["nodes"]) == len(golden["nodes"])
    for actual_node, golden_node in zip(actual["nodes"], golden["nodes"], strict=True):
        for key, value in golden_node.items():
            assert actual_node[key] == value, f"字段 {key} 重放不一致"

    # 全量 golden（= 首次重放快照）→ ``assert_replay_matches_golden`` 必须通过。
    assert_replay_matches_golden(replay, replay.to_dict())


def test_assert_replay_matches_golden_detects_drift() -> None:
    """golden 漂移 → ``VALIDATION_ERROR``，且 ``data.diff`` 定位差异路径。"""
    _run, _runs, node_runs, versions = _simple_graph_run()
    service = ReplayService(_runs, node_runs, versions=versions)
    replay = service.replay("run-1")

    drifted = replay.to_dict()
    drifted["status"] = WORKFLOW_RUN_STATUS_FAILED

    with pytest.raises(DomainError) as excinfo:
        assert_replay_matches_golden(replay, drifted)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    diff = excinfo.value.data.get("diff") or []
    assert any(item["path"] == "status" for item in diff), diff


def test_replay_is_deterministic() -> None:
    """同一持久化状态下**重复重放**结果一致（可重建性的稳定性闸门）。"""
    _run, _runs, node_runs, versions = _simple_graph_run()
    service = ReplayService(_runs, node_runs, versions=versions)

    first = service.replay("run-1").to_dict()
    second = service.replay("run-1").to_dict()
    assert first == second


def test_replay_unknown_run_raises_not_found() -> None:
    """重放不存在的运行 → ``NOT_FOUND``。"""
    service = ReplayService(_MemoryRunRepository(), _MemoryNodeRunRepository())
    with pytest.raises(DomainError) as excinfo:
        service.replay("missing")
    assert excinfo.value.code == ErrorCode.NOT_FOUND


def test_replay_suspended_run_is_recoverable() -> None:
    """审批挂起运行：重放可见 ``WAITING_APPROVAL``（**非终态**）+ ``approval_id``。

    端到端路径：``HUMAN_APPROVAL`` 节点 → ``ApprovalGateway.request`` →
    ``WorkflowNodeRun(WAITING_APPROVAL)`` + ``WorkflowRun.WAITING_APPROVAL``
    → 挂起返回 → 重放可重建（裁决后续跑归 T2-26 组合根接线）。
    """
    nodes = [_node("approve", NODE_TYPE_HUMAN_APPROVAL), _node("end", NODE_TYPE_END)]
    edges = [WorkflowEdge(workflow_version_id="wv-1", from_node_key="approve", to_node_key="end")]
    version = _version(nodes, edges, entry="approve")
    versions = _MemoryVersionRepository({version.id: version})
    runs = _MemoryRunRepository()
    node_runs = _MemoryNodeRunRepository()

    gateway = _ApprovalGateway()
    runner = _build_runner(
        _build_engine([HumanApprovalNode(gateway), EndNode()]),
        runs,
        versions=versions,
        node_runs=node_runs,
    )
    runs.add(
        WorkflowRun(
            id="run-1",
            workflow_version_id="wv-1",
            tenant_id="tenant-1",
            trigger=WORKFLOW_TRIGGER_API,
            input={"q": "need-approval"},
        )
    )

    executed = runner.execute("run-1")
    assert executed.status == WORKFLOW_RUN_STATUS_WAITING_APPROVAL

    replay = ReplayService(runs, node_runs, versions=versions).replay("run-1")
    assert replay.suspended is True
    assert [node.node_key for node in replay.nodes] == ["approve"]
    assert replay.nodes[0].status == WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL
    assert replay.nodes[0].approval_id == "approval-1"
    # 审批主体口径（W4 裁定 §6.4 #6）：workflow_node / {run_id}:{node_key}
    assert gateway.requests[0]["subject_type"] == "workflow_node"
    assert gateway.requests[0]["subject_ref"] == "run-1:approve"


def test_replay_resolves_linked_records_via_readers() -> None:
    """重放经注入读取器补全 ``agent_run`` / ``tool_call`` / ``approval`` 关联。"""
    runs = _MemoryRunRepository()
    node_runs = _MemoryNodeRunRepository()
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1"))
    node_runs.add(
        WorkflowNodeRun(
            id="nr-1",
            workflow_run_id="run-1",
            node_key="a1",
            status=WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
            agent_run_id="agent-run-1",
            tool_call_id="tool-call-1",
            approval_id="approval-1",
        )
    )

    @dataclass
    class _Record:
        id: str = ""
        kind: str = ""

    class _Reader:
        def __init__(self, kind: str) -> None:
            self._kind = kind
            self.seen: list[str] = []

        def get(self, record_id: str) -> Any:
            self.seen.append(record_id)
            return _Record(id=record_id, kind=self._kind)

    agent_reader = _Reader("agent_run")
    tool_reader = _Reader("tool_call")
    approval_reader = _Reader("approval")
    service = ReplayService(
        runs,
        node_runs,
        agent_run_reader=agent_reader,
        tool_call_reader=tool_reader,
        approval_reader=approval_reader,
    )

    replay = service.replay("run-1")
    assert agent_reader.seen == ["agent-run-1"]
    assert tool_reader.seen == ["tool-call-1"]
    assert approval_reader.seen == ["approval-1"]
    assert replay.linked["agent_runs"]["agent-run-1"]["kind"] == "agent_run"
    assert replay.linked["tool_calls"]["tool-call-1"]["kind"] == "tool_call"
    assert replay.linked["approvals"]["approval-1"]["kind"] == "approval"
    assert replay.suspended is False


def test_replay_without_readers_has_empty_links() -> None:
    """未注入读取器 → ``linked`` 为空（**不伪造**关联记录）。"""
    runs = _MemoryRunRepository()
    node_runs = _MemoryNodeRunRepository()
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1"))
    node_runs.add(
        WorkflowNodeRun(
            id="nr-1",
            workflow_run_id="run-1",
            node_key="a1",
            status=WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
            agent_run_id="agent-run-1",
        )
    )

    replay = ReplayService(runs, node_runs).replay("run-1")
    assert replay.linked["agent_runs"] == {}
    assert replay.workflow_id == "", "无版本仓储时不得伪造 workflow_id"


def test_replay_collects_linked_records() -> None:
    """重放收集 ``agent_run`` / ``tool_call`` / ``approval`` 关联记录（**不伪造**）。"""
    runs = _MemoryRunRepository()
    node_runs = _MemoryNodeRunRepository()
    # 🔴 领域不变量：存在 ``WAITING_APPROVAL`` 节点 ⇒ 运行本身处于 ``WAITING_APPROVAL``。
    runs.add(
        WorkflowRun(
            id="run-1",
            workflow_version_id="wv-1",
            tenant_id="tenant-1",
            status=WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
        )
    )
    node_runs.add(
        WorkflowNodeRun(
            id="nr-1",
            workflow_run_id="run-1",
            node_key="a1",
            status=WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
            agent_run_id="agent-run-1",
            tool_call_id="tool-call-1",
            approval_id="approval-1",
        )
    )

    class _Reader:
        def __init__(self, prefix: str) -> None:
            self._prefix = prefix

        def get(self, record_id: str) -> Any:
            return {"id": record_id, "kind": self._prefix}

    service = ReplayService(
        runs,
        node_runs,
        agent_run_reader=_Reader("agent_run"),
        tool_call_reader=_Reader("tool_call"),
        approval_reader=_Reader("approval"),
    )
    replay = service.replay("run-1")

    assert replay.linked["agent_runs"]["agent-run-1"]["kind"] == "agent_run"
    assert replay.linked["tool_calls"]["tool-call-1"]["kind"] == "tool_call"
    assert replay.linked["approvals"]["approval-1"]["kind"] == "approval"
    assert replay.suspended is True


# -- 事件流（既有通道，不改 encoder） ------------------------------------------


def test_event_bus_sink_emits_existing_workflow_events() -> None:
    """事件出口走**既有** ``astra_event`` Workflow 类型（通道映射已随 T2-16 冻结）。"""
    bus = _RecordingBus()
    sink = EventBusWorkflowEventSink(bus, workflow_id_resolver=lambda run: "wf-1")
    run = WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id="tenant-1")
    node_run = WorkflowNodeRun(
        id="nr-1", workflow_run_id="run-1", node_key="t1", status="SUCCEEDED"
    )

    sink.run_started(run)
    sink.node_started(run, node_run)
    sink.node_completed(run, node_run)
    sink.run_completed(run)

    types = [event.type for event in bus.published]
    assert types == [
        WorkflowStarted.type,
        WorkflowNodeStarted.type,
        WorkflowNodeCompleted.type,
        WorkflowCompleted.type,
    ]
    assert bus.published[0].payload["workflow_id"] == "wf-1"
    assert bus.published[0].payload["run_id"] == "run-1"


def test_event_bus_sink_maps_approval_expired_error_type() -> None:
    """审批过期终态：``error_type`` ＝ ``APPROVAL_EXPIRED``（W4 裁定 §9-c）。"""
    bus = _RecordingBus()
    sink = EventBusWorkflowEventSink(bus, workflow_id_resolver=lambda run: "wf-1")
    run = WorkflowRun(
        id="run-1",
        workflow_version_id="wv-1",
        tenant_id="tenant-1",
        status=WORKFLOW_RUN_STATUS_FAILED,
        error="APPROVAL_EXPIRED",
    )

    sink.run_failed(run)

    assert bus.published[-1].type == WorkflowFailed.type
    assert bus.published[-1].payload["error_type"] == "APPROVAL_EXPIRED"
    assert bus.published[-1].payload["error"] == "APPROVAL_EXPIRED"


def test_event_bus_sink_without_bus_is_noop() -> None:
    """无事件总线 → 静默跳过（不抛、不伪造事件）。"""
    sink = EventBusWorkflowEventSink(None)
    run = WorkflowRun(id="run-1", workflow_version_id="wv-1")
    sink.run_started(run)
    sink.run_completed(run)
    sink.run_failed(run)


# -- 回归：分层（WR-6） --------------------------------------------------------


def test_run_package_does_not_import_runtime_or_tool() -> None:
    """``run/`` **不 import** ``astra_runtime`` / ``astra_tool``（唯一耦合点仍为 bridges）。"""
    run_dir = Path(__file__).resolve().parents[3] / "packages" / "workflow" / "src"
    run_dir = run_dir / "astra_workflow" / "run"
    forbidden = {
        "import astra_runtime",
        "from astra_runtime",
        "import astra_tool",
        "from astra_tool",
    }
    offenders: list[str] = []
    for path in sorted(run_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name} -> {token}")
    assert not offenders, f"运行形态层 Runtime 耦合扩散：{offenders}"


def test_echo_tool_stub_reusable_in_run_layer() -> None:
    """复用既有 ``EchoTool`` / ``allow_tool`` 桩件（回归闸：判定链未被绕过）。"""
    tool = EchoTool(name="echo", output={"ok": True})
    assert tool.spec.metadata.name == "echo"
    assert allow_tool("echo") is not None
