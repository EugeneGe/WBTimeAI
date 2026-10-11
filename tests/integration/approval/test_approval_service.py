"""``ApprovalService`` 服务级集成测试（W4 / T2-26；设计 §2.10 / W4 裁定 §3.4）。

覆盖：

- **I-P2-15**：``HUMAN_APPROVAL`` 场景 ``request`` → 记录 ``PENDING``（``list_pending`` 命中）
  → ``decide(APPROVED)`` → 记录 ``APPROVED``；
- **I-P2-28**：``expires_at <= now``（fake clock）→ ``expire_due`` → 记录 ``EXPIRED``；
- **默认不自动生成审批**（仅显式 ``request`` 才建记录）；
- 非法迁移（对已决记录二次 ``decide``、非 ``PENDING → APPROVED``）→
  ``DomainError(VALIDATION_ERROR)``；
- 事件：``request`` emit ``ApprovalRequested`` / ``decide`` emit ``ApprovalDecided``；
- ``tenant_id`` 经 ``HUMAN_APPROVAL`` 节点透传落库；服务**结构化满足**
  ``astra_domain.ApprovalGateway``。

🔴 零迁移：表 ``approval`` 随 ``0010`` 建；本测试仅消费。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from astra_core import DomainError, ErrorCode
from astra_database import Base, create_session_factory
from astra_domain import Approval, ApprovalGateway, ApprovalStatus
from astra_event import ApprovalDecided, ApprovalRequested
from astra_security.permission import ApprovalService
from astra_security.repositories import SqlApprovalRepository
from astra_workflow import (
    NODE_TYPE_END,
    WORKFLOW_RUN_STATUS_SUCCEEDED,
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    WorkflowEdge,
    WorkflowRun,
    WorkflowVersion,
    build_definition,
)
from astra_workflow.domain import (
    NODE_TYPE_HUMAN_APPROVAL,
    WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
    WorkflowNode,
)
from astra_workflow.engine import WorkflowEngine
from astra_workflow.engine.variables import VariableContext
from astra_workflow.nodes import EndNode, HumanApprovalNode, NodeContext

_TENANT = "tenant-approval"
_USER = "user-approver"
_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class _RecordingBus:
    """记录已发布事件的内存事件总线（结构化满足 ``EventBus``）。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)

    def subscribe(self, event_type: str, handler: Any) -> None:  # pragma: no cover - 未使用
        raise NotImplementedError

    def unsubscribe(self, event_type: str, handler: Any) -> None:  # pragma: no cover - 未使用
        raise NotImplementedError


class _MemoryNodeRunRecorder:
    """内存版 ``NodeRunRecorder``（供引擎 ``resume`` 回读挂起节点）。"""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def add(self, node_run: Any) -> Any:
        self.rows.append(node_run)
        return node_run

    def update(self, node_run: Any) -> Any:
        for index, row in enumerate(self.rows):
            if row.id == node_run.id:
                self.rows[index] = node_run
                break
        return node_run

    def list_by_run(self, workflow_run_id: str) -> list[Any]:
        return [row for row in self.rows if row.workflow_run_id == workflow_run_id]


class _MemoryVersionRepo:
    """内存版版本仓储（``WorkflowEngine.resume`` 回读不可变版本快照）。"""

    def __init__(self, versions: dict[str, Any]) -> None:
        self._versions = versions

    def get(self, entity_id: str) -> Any | None:
        return self._versions.get(entity_id)

    def add(self, entity: Any) -> Any:
        self._versions[entity.id] = entity
        return entity


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


@pytest.fixture()
def clock() -> list[datetime]:
    """fake clock（单元素列表作可变当前时间）。"""
    return [_NOW]


@pytest.fixture()
def bus() -> _RecordingBus:
    """记录总线。"""
    return _RecordingBus()


@pytest.fixture()
def service(session_factory: Any, clock: list[datetime], bus: _RecordingBus) -> ApprovalService:
    """装配服务（SQL 仓储 + 记录总线 + fake clock）。"""
    repository = SqlApprovalRepository(session_factory)
    return ApprovalService(repository, event_bus=bus, clock=lambda: clock[0])


def _repo(session_factory: Any) -> SqlApprovalRepository:
    """新建一个仓储读取句柄（与写入句柄共享同一 DB）。"""
    return SqlApprovalRepository(session_factory)


# -- I-P2-15：request → PENDING → decide(APPROVED) ---------------------------


def test_i_p2_15_request_then_approve(service: ApprovalService, session_factory: Any) -> None:
    """``request`` 落 ``PENDING``（``list_pending`` 命中）→ ``decide`` 落 ``APPROVED``。"""
    approval = service.request(
        subject_type="workflow_node",
        subject_ref="run-1:approve",
        payload={"reason": "deploy"},
        requested_by=_USER,
        tenant_id=_TENANT,
    )
    assert approval.id
    assert approval.status == ApprovalStatus.PENDING
    assert approval.is_pending is True

    repo = _repo(session_factory)
    pending = repo.list_pending(tenant_id=_TENANT)
    assert [item.id for item in pending] == [approval.id]
    assert pending[0].payload == {"reason": "deploy"}

    decided = service.decide(approval.id, status="APPROVED", decided_by=_USER)
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.decided_by == _USER
    assert decided.decided_at is not None

    assert repo.get(approval.id).status == ApprovalStatus.APPROVED
    assert repo.list_pending(tenant_id=_TENANT) == []


def test_i_p2_15_reject_flow(service: ApprovalService, session_factory: Any) -> None:
    """``decide(REJECTED)`` 落 ``REJECTED``。"""
    approval = service.request(subject_type="tool", subject_ref="tool-1", tenant_id=_TENANT)
    decided = service.decide(approval.id, status="REJECTED", decided_by=_USER)
    assert decided.status == ApprovalStatus.REJECTED
    assert _repo(session_factory).get(approval.id).status == ApprovalStatus.REJECTED


# -- 默认不自动生成审批 ------------------------------------------------------


def test_no_auto_approval_by_default(session_factory: Any) -> None:
    """无显式 ``request`` → 不产生任何审批记录。"""
    repo = _repo(session_factory)
    assert repo.list_pending() == []
    assert repo.list_pending(tenant_id=_TENANT) == []


# -- I-P2-28：到期扫描（fake clock） ----------------------------------------


def test_i_p2_28_expire_due(
    service: ApprovalService, session_factory: Any, clock: list[datetime]
) -> None:
    """``expires_at <= now`` → ``expire_due`` → ``EXPIRED``。"""
    before = clock[0]
    approval = service.request(
        subject_type="tool",
        subject_ref="tool-1",
        expires_at=before + timedelta(minutes=5),
        tenant_id=_TENANT,
    )

    # 未到期 → 不处理。
    assert service.expire_due() == []
    assert _repo(session_factory).get(approval.id).status == ApprovalStatus.PENDING

    # 推进 fake clock 越过到期时间 → 置 EXPIRED。
    clock[0] = before + timedelta(minutes=10)
    expired = service.expire_due()
    assert [item.id for item in expired] == [approval.id]
    assert expired[0].status == ApprovalStatus.EXPIRED
    assert _repo(session_factory).get(approval.id).status == ApprovalStatus.EXPIRED
    assert _repo(session_factory).list_pending() == []


def test_expire_due_ignores_no_expiry(service: ApprovalService, clock: list[datetime]) -> None:
    """``expires_at=None``（永不过期）→ 即使推进时钟也不过期。"""
    service.request(subject_type="tool", subject_ref="t", tenant_id=_TENANT)
    clock[0] = _NOW + timedelta(days=3650)
    assert service.expire_due() == []


# -- 非法迁移 ----------------------------------------------------------------


def test_double_decide_is_illegal(service: ApprovalService) -> None:
    """对已决记录二次 ``decide`` → ``DomainError(VALIDATION_ERROR)``。"""
    approval = service.request(subject_type="tool", subject_ref="t", tenant_id=_TENANT)
    service.decide(approval.id, status="APPROVED", decided_by=_USER)
    with pytest.raises(DomainError) as excinfo:
        service.decide(approval.id, status="REJECTED", decided_by=_USER)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_decide_expired_after_expire_is_illegal(
    service: ApprovalService, clock: list[datetime]
) -> None:
    """已 ``EXPIRED`` 记录再 ``decide`` → ``DomainError(VALIDATION_ERROR)``。"""
    before = clock[0]
    approval = service.request(
        subject_type="tool",
        subject_ref="t",
        expires_at=before + timedelta(minutes=1),
        tenant_id=_TENANT,
    )
    clock[0] = before + timedelta(minutes=2)
    assert len(service.expire_due()) == 1
    with pytest.raises(DomainError) as excinfo:
        service.decide(approval.id, status="APPROVED", decided_by=_USER)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_invalid_decision_status_is_rejected(service: ApprovalService) -> None:
    """``decide(status="EXPIRED")``（非决议状态）→ ``DomainError(VALIDATION_ERROR)``。"""
    approval = service.request(subject_type="tool", subject_ref="t", tenant_id=_TENANT)
    with pytest.raises(DomainError) as excinfo:
        service.decide(approval.id, status="EXPIRED", decided_by=None)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


def test_decide_missing_approval_raises_not_found(service: ApprovalService) -> None:
    """``decide`` 不存在的审批 → ``DomainError(NOT_FOUND)``。"""
    with pytest.raises(DomainError) as excinfo:
        service.decide("missing-id", status="APPROVED", decided_by=_USER)
    assert excinfo.value.code == ErrorCode.NOT_FOUND


def test_request_requires_subject_fields(service: ApprovalService) -> None:
    """``request`` 缺主体字段 → ``DomainError(VALIDATION_ERROR)``。"""
    with pytest.raises(DomainError) as excinfo:
        service.request(subject_type="", subject_ref="x", tenant_id=_TENANT)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR


# -- 事件 --------------------------------------------------------------------


def test_request_and_decide_emit_events(service: ApprovalService, bus: _RecordingBus) -> None:
    """``request`` emit ``ApprovalRequested``；``decide`` emit ``ApprovalDecided``。"""
    approval = service.request(
        subject_type="mcp", subject_ref="server-1", requested_by=_USER, tenant_id=_TENANT
    )
    service.decide(approval.id, status="APPROVED", decided_by=_USER)

    kinds = [type(event) for event in bus.events]
    assert ApprovalRequested in kinds
    assert ApprovalDecided in kinds

    requested = next(e for e in bus.events if isinstance(e, ApprovalRequested))
    assert requested.payload["approval_id"] == approval.id
    assert requested.payload["subject_type"] == "mcp"
    assert requested.payload["subject_ref"] == "server-1"

    decided = next(e for e in bus.events if isinstance(e, ApprovalDecided))
    assert decided.payload["approval_id"] == approval.id
    assert decided.payload["status"] == "APPROVED"


def test_expire_due_emits_decided(
    service: ApprovalService, bus: _RecordingBus, clock: list[datetime]
) -> None:
    """``expire_due`` emit ``ApprovalDecided(status=EXPIRED)``。"""
    before = clock[0]
    service.request(
        subject_type="tool",
        subject_ref="t",
        expires_at=before + timedelta(minutes=1),
        tenant_id=_TENANT,
    )
    clock[0] = before + timedelta(minutes=2)
    service.expire_due()
    decided = next(e for e in bus.events if isinstance(e, ApprovalDecided))
    assert decided.payload["status"] == "EXPIRED"


def test_no_event_bus_is_persist_only(session_factory: Any) -> None:
    """``event_bus=None`` → 仅持久化、不发事件（不报错）。"""
    svc = ApprovalService(SqlApprovalRepository(session_factory), clock=lambda: _NOW)
    approval = svc.request(subject_type="tool", subject_ref="t", tenant_id=_TENANT)
    assert svc.get(approval.id).is_pending is True


# -- 结构化满足 ApprovalGateway + 节点透传 tenant ----------------------------


def test_service_structurally_satisfies_gateway(service: ApprovalService) -> None:
    """``ApprovalService`` 结构化满足 :class:`astra_domain.ApprovalGateway`。"""
    assert isinstance(service, ApprovalGateway)


def test_human_approval_node_passes_tenant(session_factory: Any, clock: list[datetime]) -> None:
    """``HUMAN_APPROVAL`` 节点以关键字调用网关，``tenant_id`` 经 ``ctx`` 透传落库。"""
    svc = ApprovalService(SqlApprovalRepository(session_factory), clock=lambda: clock[0])
    node = WorkflowNode(
        node_key="approve",
        type=NODE_TYPE_HUMAN_APPROVAL,
        config={"payload": {"k": "v"}},
    )
    var_ctx = VariableContext(inputs={})
    ctx = NodeContext(run_id="run-1", tenant_id=_TENANT, requested_by=_USER)

    result = HumanApprovalNode(svc).execute(node, var_ctx, ctx)

    assert result.suspended is True
    assert result.approval_id is not None

    stored = _repo(session_factory).get(result.approval_id)
    assert stored is not None
    assert stored.tenant_id == _TENANT
    assert stored.requested_by == _USER
    assert stored.subject_type == "workflow_node"
    assert stored.subject_ref == "run-1:approve"
    assert stored.status == ApprovalStatus.PENDING
    assert stored.payload == {"k": "v"}


def test_approval_status_transitions_table() -> None:
    """合法迁移表口径：``PENDING`` 可转；终态不可转。"""
    from astra_domain import APPROVAL_ALLOWED_TRANSITIONS
    from astra_domain import ApprovalStatus as _S

    assert _S.APPROVED in APPROVAL_ALLOWED_TRANSITIONS[_S.PENDING]
    assert APPROVAL_ALLOWED_TRANSITIONS[_S.APPROVED] == frozenset()
    # ``Approval`` 实体二次决议直接抛错（不经服务）。
    entity = Approval(status=_S.PENDING, subject_type="tool", subject_ref="t")
    entity.decide(status=_S.APPROVED)
    with pytest.raises(DomainError):
        entity.decide(status=_S.REJECTED)


# -- T2-26 resume-aware：HUMAN_APPROVAL 节点重入幂等 -------------------------


def test_human_approval_node_reentry_does_not_duplicate(
    session_factory: Any, clock: list[datetime]
) -> None:
    """重入同一 ``subject_ref`` → 不产生第 2 条审批，返回同一 ``approval_id``。"""
    svc = ApprovalService(SqlApprovalRepository(session_factory), clock=lambda: clock[0])
    node = HumanApprovalNode(svc)
    wf_node = WorkflowNode(node_key="approve", type=NODE_TYPE_HUMAN_APPROVAL, config={})
    ctx = NodeContext(run_id="run-1", tenant_id=_TENANT, requested_by=_USER)

    first = node.execute(wf_node, VariableContext(), ctx)
    second = node.execute(wf_node, VariableContext(), ctx)

    assert first.suspended is True
    assert second.suspended is True
    assert first.approval_id is not None
    assert first.approval_id == second.approval_id

    repo = _repo(session_factory)
    assert len(repo.list_pending(tenant_id=_TENANT)) == 1


def test_human_approval_node_reentry_after_approve_succeeds(
    session_factory: Any, clock: list[datetime]
) -> None:
    """既有审批 ``APPROVED`` → 重入直接放行（成功），不再发起第 2 条。"""
    svc = ApprovalService(SqlApprovalRepository(session_factory), clock=lambda: clock[0])
    node = HumanApprovalNode(svc)
    wf_node = WorkflowNode(node_key="approve", type=NODE_TYPE_HUMAN_APPROVAL, config={})
    ctx = NodeContext(run_id="run-1", tenant_id=_TENANT, requested_by=_USER)

    first = node.execute(wf_node, VariableContext(), ctx)
    svc.decide(first.approval_id, status="APPROVED", decided_by=_USER)

    result = node.execute(wf_node, VariableContext(), ctx)

    assert result.status == WORKFLOW_NODE_RUN_STATUS_SUCCEEDED
    assert result.suspended is False
    repo = _repo(session_factory)
    assert repo.list_pending(tenant_id=_TENANT) == []
    existing = repo.get_by_subject_ref(subject_type="workflow_node", subject_ref="run-1:approve")
    assert existing is not None
    assert existing.status == ApprovalStatus.APPROVED


def test_human_approval_node_reentry_rejected_raises(
    session_factory: Any, clock: list[datetime]
) -> None:
    """既有审批 ``REJECTED`` → 重入抛 ``DomainError``（防御；不重复发起）。"""
    svc = ApprovalService(SqlApprovalRepository(session_factory), clock=lambda: clock[0])
    node = HumanApprovalNode(svc)
    wf_node = WorkflowNode(node_key="approve", type=NODE_TYPE_HUMAN_APPROVAL, config={})
    ctx = NodeContext(run_id="run-1", tenant_id=_TENANT, requested_by=_USER)

    first = node.execute(wf_node, VariableContext(), ctx)
    svc.decide(first.approval_id, status="REJECTED", decided_by=_USER)

    with pytest.raises(DomainError) as excinfo:
        node.execute(wf_node, VariableContext(), ctx)
    assert excinfo.value.code == ErrorCode.VALIDATION_ERROR
    assert len(_repo(session_factory).list_pending(tenant_id=_TENANT)) == 0


def test_sql_repo_get_by_subject_ref_returns_latest(session_factory: Any) -> None:
    """``get_by_subject_ref`` 取 ``(subject_type, subject_ref)`` 的**最近一条**。"""
    svc = ApprovalService(SqlApprovalRepository(session_factory))
    svc.request(subject_type="workflow_node", subject_ref="r:n", tenant_id=_TENANT)
    latest = svc.request(subject_type="workflow_node", subject_ref="r:n", tenant_id=_TENANT)
    svc.request(subject_type="tool", subject_ref="r:n", tenant_id=_TENANT)

    repo = _repo(session_factory)
    found = repo.get_by_subject_ref(subject_type="workflow_node", subject_ref="r:n")
    assert found is not None
    assert found.id == latest.id
    assert repo.get_by_subject_ref(subject_type="mcp", subject_ref="r:n") is None


# -- T2-26 resume 收敛：真节点 + 真 ApprovalService + 真 WorkflowEngine --------


def test_engine_resume_converges_with_real_node_and_service(
    session_factory: Any, clock: list[datetime]
) -> None:
    """端到端：挂起 → ``decide(APPROVED)`` → ``engine.resume`` 收敛 ``SUCCEEDED``。

    证明 T2-26 resume-aware 修复：重入**不重复发起**审批，且既有 ``APPROVED`` 直接放行。
    """
    svc = ApprovalService(SqlApprovalRepository(session_factory), clock=lambda: clock[0])

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
    version = WorkflowVersion(
        id="wv-1",
        workflow_id="wf-1",
        version="v1",
        definition=build_definition(nodes, edges, entry="approve"),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by="u-1",
    )
    recorder = _MemoryNodeRunRecorder()
    engine = WorkflowEngine(
        {"HUMAN_APPROVAL": HumanApprovalNode(svc), "END": EndNode()},
        versions=_MemoryVersionRepo({version.id: version}),
        recorder=recorder,
    )
    ctx = NodeContext(run_id="run-1", tenant_id=_TENANT, requested_by=_USER)
    run = WorkflowRun(id="run-1", workflow_version_id=version.id, tenant_id=_TENANT, input={})

    suspended = engine.run(version, {}, run=run, ctx=ctx)
    assert suspended.status == WORKFLOW_RUN_STATUS_WAITING_APPROVAL

    approval_id = recorder.rows[0].approval_id
    assert approval_id is not None
    svc.decide(approval_id, status="APPROVED", decided_by=_USER)

    resumed = engine.resume(suspended, ctx=ctx)
    assert resumed.status == WORKFLOW_RUN_STATUS_SUCCEEDED
    # 重入幂等：全程仅 1 条审批（未重复发起）。
    repo = _repo(session_factory)
    assert len(repo.list_pending(tenant_id=_TENANT)) == 0
    existing = repo.get_by_subject_ref(subject_type="workflow_node", subject_ref="run-1:approve")
    assert existing is not None
    assert existing.id == approval_id


def test_engine_resume_pending_approval_still_suspends(
    session_factory: Any, clock: list[datetime]
) -> None:
    """重入时审批仍 ``PENDING``（异常路径）→ 继续挂起，**不重复发起**。"""
    svc = ApprovalService(SqlApprovalRepository(session_factory), clock=lambda: clock[0])

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
    version = WorkflowVersion(
        id="wv-1",
        workflow_id="wf-1",
        version="v1",
        definition=build_definition(nodes, edges, entry="approve"),
        status=WORKFLOW_VERSION_STATUS_PUBLISHED,
        created_by="u-1",
    )
    recorder = _MemoryNodeRunRecorder()
    engine = WorkflowEngine(
        {"HUMAN_APPROVAL": HumanApprovalNode(svc), "END": EndNode()},
        versions=_MemoryVersionRepo({version.id: version}),
        recorder=recorder,
    )
    ctx = NodeContext(run_id="run-1", tenant_id=_TENANT, requested_by=_USER)
    run = WorkflowRun(id="run-1", workflow_version_id=version.id, tenant_id=_TENANT, input={})

    suspended = engine.run(version, {}, run=run, ctx=ctx)
    assert suspended.status == WORKFLOW_RUN_STATUS_WAITING_APPROVAL

    # 未决议即续跑 → 重入后发现仍 PENDING → 继续挂起（幂等）。
    resumed = engine.resume(suspended, ctx=ctx)
    assert resumed.status == WORKFLOW_RUN_STATUS_WAITING_APPROVAL
    assert len(_repo(session_factory).list_pending(tenant_id=_TENANT)) == 1
