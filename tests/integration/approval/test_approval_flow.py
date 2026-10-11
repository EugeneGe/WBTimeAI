"""Approval 机制端到端集成测试（W4 / T2-26；裁定 §3.2 / §3.4 / §4）。

覆盖**组合根装配 + 工作流级端到端**（审批「机制核心」由 ``engineer-1`` 覆盖）：

- **I-P2-15**：``HUMAN_APPROVAL`` 节点 → run 落 ``WAITING_APPROVAL`` →
  ``ApprovalService.decide(APPROVED)`` → emit ``ApprovalDecided`` → 组合根订阅 →
  ``WorkflowService.resume`` → run **续跑至 ``SUCCEEDED``**；
- **I-P2-28**：``expires_at ≤ now``（fake clock）→ ``expire_due`` → 审批 ``EXPIRED``
  且 ``workflow_run`` 终态 **``FAILED``（``error=APPROVAL_EXPIRED``）**；
- **决议拒绝**：``decide(REJECTED)`` → run 终态 ``FAILED``（``error=APPROVAL_REJECTED``）；
- **默认不自动生成审批**（无 ``HUMAN_APPROVAL`` / 显式配置时不产生 ``approval`` 记录）。

🔴 组合根装配（``apps/api/src/astra_api/dependencies/services.py``）由 lifespan 完成；
   本测试经 ``client.app.state.services`` 取用**真实** ``ApprovalService`` /
   ``WorkflowService``（非桩件），端到端验证「决议 → 续跑」订阅链。

🔴 到期语义（裁定 §9-c）：``expire_due`` 以**显式 ``now``**（fake clock）驱动，不依赖真实时钟。
   node ``config`` 为 JSON（无法承载 ``datetime``），故到期时间在挂起后经审批仓储落库。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from astra_database import session_scope
from astra_database.models import Approval as ApprovalRow
from astra_domain import ApprovalStatus
from astra_security.repositories import SqlApprovalRepository
from sqlalchemy import func, select

#: 运行 / 审批终态字面值（与领域口径一致，防拼写漂移）。
_STATUS_WAITING_APPROVAL = "WAITING_APPROVAL"
_STATUS_SUCCEEDED = "SUCCEEDED"
_STATUS_FAILED = "FAILED"
_STATUS_PENDING = "PENDING"
_STATUS_APPROVED = "APPROVED"
_STATUS_REJECTED = "REJECTED"
_STATUS_EXPIRED = "EXPIRED"

#: 审批到期 / 被拒后运行终态错误码（裁定 §3.2 / §9-c）。
ERROR_APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
ERROR_APPROVAL_REJECTED = "APPROVAL_REJECTED"


# -- 辅助 ---------------------------------------------------------------------


def _data(response: Any) -> Any:
    """从统一响应壳取 ``data``。"""
    body = response.json()
    assert "data" in body, response.text
    return body["data"]


def _status(value: Any) -> str:
    """把审批状态（枚举 / 字符串）归一为字面值。"""
    return str(getattr(value, "value", value) or "")


def _publish_approval_workflow(client: Any, headers: dict[str, str], *, name: str) -> str:
    """创建并发布「``HUMAN_APPROVAL`` → ``END``」流程，返回 ``workflow_id``。"""
    created = client.post("/api/v1/workflows", headers=headers, json={"name": name})
    assert created.status_code == 201, created.text
    workflow_id = _data(created)["id"]

    payload: dict[str, Any] = {
        "nodes": [
            {"key": "approve", "type": "HUMAN_APPROVAL", "config": {}},
            {"key": "end", "type": "END"},
        ],
        "edges": [{"from": "approve", "to": "end"}],
        "entry": "approve",
    }
    published = client.post(
        f"/api/v1/workflows/{workflow_id}/publish", headers=headers, json=payload
    )
    assert published.status_code == 201, published.text
    return workflow_id


def _run_inline(client: Any, headers: dict[str, str], workflow_id: str) -> dict[str, Any]:
    """以 ``INLINE`` 运行一次流程（显式 ``Accept: application/json``），返回运行摘要。"""
    response = client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers={**headers, "Accept": "application/json"},
        json={"execution_mode": "INLINE"},
    )
    assert response.status_code == 200, response.text
    return _data(response)


def _approval_id_for(services: Any, run_id: str) -> str:
    """经重放快照取挂起节点的 ``approval_id``（**不伪造**）。"""
    replay = services.workflow.replay(run_id)
    for node in replay["nodes"]:
        approval_id = node.get("approval_id")
        if approval_id:
            return str(approval_id)
    raise AssertionError(f"运行 {run_id} 未产生 approval_id 节点记录")


# -- 组合根装配 ---------------------------------------------------------------


def test_approval_service_wired_in_composition_root(client: Any) -> None:
    """``ApprovalService`` 已登记于 ``AppServices`` 并装配到 ``app.state.services``。"""
    from astra_api.dependencies.services import AppServices

    assert "approval" in {field.name for field in AppServices.__dataclass_fields__.values()}
    assert client.app.state.services.approval is not None


# -- I-P2-15：决议通过 → 续跑至成功 -------------------------------------------


def test_human_approval_approved_resumes_run(client: Any, auth_headers: dict[str, str]) -> None:
    """``decide(APPROVED)`` → ``ApprovalDecided`` → ``resume`` → run ``SUCCEEDED``（I-P2-15）。"""
    services = client.app.state.services
    workflow_id = _publish_approval_workflow(client, auth_headers, name="approval-approve")

    run = _run_inline(client, auth_headers, workflow_id)
    assert run["status"] == _STATUS_WAITING_APPROVAL, run
    run_id = run["run_id"]

    approval_id = _approval_id_for(services, run_id)
    approval = services.approval.get(approval_id)
    assert approval is not None
    assert _status(approval.status) == _STATUS_PENDING

    # 决议通过：组合根订阅的 ``ApprovalDecided`` 处理器**同步**触发 ``WorkflowService.resume``。
    services.approval.decide(approval_id, status=ApprovalStatus.APPROVED, decided_by="system")

    assert _status(services.approval.get(approval_id).status) == _STATUS_APPROVED
    resumed = services.workflow.get_run(run_id)
    assert resumed.status == _STATUS_SUCCEEDED, resumed
    assert resumed.error is None


# -- I-P2-28：到期 → 运行终态 FAILED（error=APPROVAL_EXPIRED） ------------------


def test_human_approval_expired_fails_run(client: Any, auth_headers: dict[str, str]) -> None:
    """``expires_at ≤ now``（fake clock）→ ``EXPIRED`` + run ``FAILED``（I-P2-28）。"""
    services = client.app.state.services
    workflow_id = _publish_approval_workflow(client, auth_headers, name="approval-expire")

    run = _run_inline(client, auth_headers, workflow_id)
    assert run["status"] == _STATUS_WAITING_APPROVAL, run
    run_id = run["run_id"]
    approval_id = _approval_id_for(services, run_id)

    # 到期时间（过去）经审批仓储落库（node config 为 JSON，无法承载 ``datetime``）。
    session_factory = services.providers.database.session_factory
    approval_repository = SqlApprovalRepository(session_factory)
    approval = approval_repository.get(approval_id)
    assert approval is not None
    approval.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    approval_repository.update(approval)

    # fake clock：显式 ``now``（远晚于 ``expires_at``）驱动到期扫描 → EXPIRED → run FAILED。
    expired = services.approval.expire_due(now=datetime(2001, 1, 1, tzinfo=UTC))
    assert approval_id in {item.id for item in expired}, expired

    assert _status(services.approval.get(approval_id).status) == _STATUS_EXPIRED
    failed = services.workflow.get_run(run_id)
    assert failed.status == _STATUS_FAILED, failed
    assert failed.error == ERROR_APPROVAL_EXPIRED


# -- 决议拒绝 → 运行终态 FAILED（error=APPROVAL_REJECTED） ---------------------


def test_human_approval_rejected_fails_run(client: Any, auth_headers: dict[str, str]) -> None:
    """``decide(REJECTED)`` → ``ApprovalDecided`` → run 终态 ``FAILED``（裁定 §3.2）。"""
    services = client.app.state.services
    workflow_id = _publish_approval_workflow(client, auth_headers, name="approval-reject")

    run = _run_inline(client, auth_headers, workflow_id)
    assert run["status"] == _STATUS_WAITING_APPROVAL, run
    run_id = run["run_id"]
    approval_id = _approval_id_for(services, run_id)

    services.approval.decide(approval_id, status=ApprovalStatus.REJECTED, decided_by="system")

    assert _status(services.approval.get(approval_id).status) == _STATUS_REJECTED
    failed = services.workflow.get_run(run_id)
    assert failed.status == _STATUS_FAILED, failed
    assert failed.error == ERROR_APPROVAL_REJECTED


# -- 默认不自动生成审批 --------------------------------------------------------


def test_no_approval_generated_without_human_approval_node(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """无 ``HUMAN_APPROVAL`` / 显式配置时**不产生** ``approval`` 记录（裁定 §3.4）。"""
    services = client.app.state.services
    created = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "no-approval"})
    assert created.status_code == 201, created.text
    workflow_id = _data(created)["id"]

    published = client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers=auth_headers,
        json={"nodes": [{"key": "end", "type": "END"}], "edges": [], "entry": "end"},
    )
    assert published.status_code == 201, published.text

    run = _run_inline(client, auth_headers, workflow_id)
    assert run["status"] == _STATUS_SUCCEEDED, run
    run_id = run["run_id"]

    # 该运行**不得**产生任何审批记录（按 ``subject_ref`` ＝ ``{run_id}:{node_key}`` 断言）。
    session_factory = services.providers.database.session_factory
    with session_scope(session_factory) as session:
        total = int(
            session.execute(
                select(func.count())
                .select_from(ApprovalRow)
                .where(ApprovalRow.subject_ref.like(f"{run_id}:%"))
            ).scalar_one()
        )
    assert total == 0, "无 HUMAN_APPROVAL / 显式配置时不得自动生成审批"
