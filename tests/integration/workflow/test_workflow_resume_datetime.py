"""``INLINE`` resume 路径 datetime 归一回归测试（W4 / T2-26 修复）。

**本轮暴露的漏洞**：``InlineRunner.resume`` 从 SQLite **回读** ``workflow_run`` 时，
``started_at`` 为 **naive**（``mappers.workflow_run_to_domain`` 未做 UTC 归一）；
而 ``run.succeed()`` 置 ``completed_at`` 为 **aware**；
``EventBusWorkflowEventSink._duration_ms`` 直接相减 → ``TypeError``（naive − aware）→
``InlineRunner.resume`` 的 ``runs.update(resumed)`` **不执行** → DB 中 run 仍 ``WAITING_APPROVAL``。

本用例**忠实复现**该盲区：run 先落库（SQLite）→ 回读为 naive → ``resume`` → 应变 ``SUCCEEDED``。
（首轮 ``execute`` 不触发；仅 ``resume``（从 DB 回读）触发。）

🔴 分层：仅用 ``astra_workflow`` 公开面 + ``astra_database``（能力包允许的 ORM 落点）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from astra_common.time import utcnow
from astra_database import Base, create_session_factory
from astra_database.models.workflow import WorkflowRun as OrmWorkflowRun
from astra_workflow import (
    NODE_TYPE_END,
    NODE_TYPE_HUMAN_APPROVAL,
    WORKFLOW_RUN_STATUS_SUCCEEDED,
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    WorkflowEdge,
    WorkflowNode,
    WorkflowRun,
    WorkflowVersion,
    build_definition,
)
from astra_workflow.engine import VariableContext, WorkflowEngine
from astra_workflow.nodes import EndNode, NodeResult
from astra_workflow.repositories import (
    SqlWorkflowNodeRunRepository,
    SqlWorkflowRunRepository,
    SqlWorkflowVersionRepository,
)
from astra_workflow.run import EventBusWorkflowEventSink, InlineRunner

_TENANT = "tenant-1"


class _FakeBus:
    """记录已发布事件的 fake ``EventBus``。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


class _SuspendThenSucceedExecutor:
    """首次挂起、二次放行的 fake ``HUMAN_APPROVAL`` 执行器。"""

    type = NODE_TYPE_HUMAN_APPROVAL

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, node: WorkflowNode, var_ctx: VariableContext, ctx: Any = None) -> NodeResult:
        self.calls.append(node.node_key)
        if len(self.calls) == 1:
            return NodeResult.suspended_for_approval("approval-1")
        return NodeResult.success({"approved": True})


@pytest.fixture()
def session_factory():  # noqa: ANN201 - 与仓库既有 fixture 约定一致
    """**进程内** SQLite 会话工厂（``StaticPool``，注册全部 ORM 表；零临时文件）。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
    )
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _version() -> WorkflowVersion:
    """构造「``HUMAN_APPROVAL`` → ``END``」的已发布版本。"""
    nodes = [
        WorkflowNode(
            workflow_version_id="wv-1",
            node_key="approve",
            type=NODE_TYPE_HUMAN_APPROVAL,
            config={},
        ),
        WorkflowNode(workflow_version_id="wv-1", node_key="end", type=NODE_TYPE_END, config={}),
    ]
    edges = [WorkflowEdge(workflow_version_id="wv-1", from_node_key="approve", to_node_key="end")]
    return WorkflowVersion(
        id="wv-1",
        workflow_id="wf-1",
        version="v1",
        definition=build_definition(nodes, edges, entry="approve"),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by="u-1",
    )


def _build_runner(session_factory: Any) -> InlineRunner:
    """装配 DB 落底的 ``InlineRunner``（SQL 仓储 + ``EventBusWorkflowEventSink``）。"""
    versions = SqlWorkflowVersionRepository(session_factory)
    versions.add(_version())
    runs = SqlWorkflowRunRepository(session_factory)
    node_runs = SqlWorkflowNodeRunRepository(session_factory)
    runs.add(WorkflowRun(id="run-1", workflow_version_id="wv-1", tenant_id=_TENANT))

    executor = _SuspendThenSucceedExecutor()
    engine = WorkflowEngine({"HUMAN_APPROVAL": executor, "END": EndNode()}, versions=versions)
    runner = InlineRunner(
        engine,
        runs,
        node_runs=node_runs,
        versions=versions,
        sink=EventBusWorkflowEventSink(_FakeBus()),
    )
    return runner


def test_resume_after_db_roundtrip_converges(session_factory: Any) -> None:
    """run 落库 → 回读（naive）→ ``resume`` → **``SUCCEEDED``** 并持久化（漏洞回归）。"""
    runner = _build_runner(session_factory)

    executed = runner.execute("run-1")
    assert executed.status == WORKFLOW_RUN_STATUS_WAITING_APPROVAL

    # 前置条件：SQLite 原样存储的时间戳是 **naive**（绕过 mapper 直读 ORM 行）。
    with session_factory() as session:
        orm_row = session.get(OrmWorkflowRun, "run-1")
        assert orm_row is not None
        assert orm_row.started_at is not None
        assert orm_row.started_at.tzinfo is None  # SQLite 回读为 naive（漏洞触发前提）

    # 回读经 mapper：``started_at`` 应已归一到 UTC-aware（修复点）。
    reloaded = runner.runs.get("run-1")
    assert reloaded is not None
    assert reloaded.started_at is not None
    assert reloaded.started_at.tzinfo is not None

    # 续跑：既有漏洞在此抛 ``TypeError`` → run 不落终态。
    resumed = runner.resume("run-1")
    assert resumed.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    # DB 中确已落终态（漏洞时因 sink 抛错而 update 不执行）。
    assert runner.runs.get("run-1").status == WORKFLOW_RUN_STATUS_SUCCEEDED


def test_duration_ms_defends_against_naive_vs_aware() -> None:
    """``_duration_ms`` 对 naive / aware 混用**不抛错**（防御；修复点 2）。"""
    record = WorkflowRun(
        id="r",
        started_at=datetime(2026, 1, 1, 0, 0, 0),  # naive
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),  # aware
    )
    assert EventBusWorkflowEventSink._duration_ms(record) == 1000


def test_mappers_normalize_nullable_run_datetimes(session_factory: Any) -> None:
    """``workflow_run_to_domain`` 归一 ``started_at`` / ``completed_at``；可空字段保持 ``None``。"""
    runs = SqlWorkflowRunRepository(session_factory)
    runs.add(
        WorkflowRun(
            id="run-x",
            workflow_version_id="wv-1",
            tenant_id=_TENANT,
            started_at=utcnow(),
            status=WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
        )
    )
    reloaded = runs.get("run-x")
    assert reloaded is not None
    assert reloaded.started_at is not None
    assert reloaded.started_at.tzinfo is not None
    assert reloaded.completed_at is None  # 可空字段**不得**被 ``_dt()`` 回填成 now
