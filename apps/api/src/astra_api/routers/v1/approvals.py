"""``/approvals`` 路由（W10 / T2-49；设计 §2.10 / §2.12）。

端点：

- ``GET  /approvals``：待办列表（``list_pending(tenant_id=...)``，分页）；
- ``GET  /approvals/{approval_id}``：详情（跨租户 / 不存在 → 404）；
- ``POST /approvals/{approval_id}/approve``：决议通过（``APPROVED``）；
- ``POST /approvals/{approval_id}/reject``：决议驳回（``REJECTED``）。

Router **只**依赖 ``AppServices`` / ``CurrentUser``（N-8）：**不** import ``astra_security`` /
``astra_domain`` / ``astra_database`` / ``sqlalchemy``（守
``test_api_routers_have_no_orm_dependency``）；只读列表经 ``services.approval_repository``
（领域 ``ApprovalRepository`` Protocol，**只读**），决议**必须经** ``services.approval.decide(...)``
（保状态机 + ``ApprovalDecided`` 事件 + 工作流续跑消费），**禁**直接 ``repository.update``
（裁定 R-W10-03）。

🔴 跨租户 / 不存在 → **404**（不泄漏存在性）；已决议（非 ``PENDING``）再决议 → **409**。
"""

from __future__ import annotations

from typing import Annotated, Any

from astra_application.dto import UserDTO
from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends, Query

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.approval import ApprovalResponse

router = APIRouter(prefix="/approvals", tags=["approvals"])

#: 决议状态字面值（与 ``astra_domain.ApprovalStatus`` 同口径，避免拼写漂移）。
_STATUS_APPROVED = "APPROVED"
_STATUS_REJECTED = "REJECTED"


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_response(approval: Any) -> ApprovalResponse:
    """审批实体 → 响应。"""
    return ApprovalResponse(
        id=str(approval.id),
        tenant_id=approval.tenant_id,
        subject_type=str(approval.subject_type or ""),
        subject_ref=str(approval.subject_ref or ""),
        requested_by=approval.requested_by,
        status=str(approval.status),
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        payload=dict(approval.payload or {}),
        expires_at=approval.expires_at,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


def _require_owned_approval(services: AppServices, *, approval_id: str, tenant_id: str) -> Any:
    """取当前租户下的审批记录，不存在 / 跨租户 → 404（隔离 I-1）。"""
    approval = services.approval.get(approval_id)
    if approval is None or str(getattr(approval, "tenant_id", "") or "") != tenant_id:
        raise DomainError("审批不存在", code=ErrorCode.NOT_FOUND, data={"approval_id": approval_id})
    return approval


def _decide(
    services: AppServices, *, approval_id: str, tenant_id: str, status: str, decided_by: str
) -> ApprovalResponse:
    """经 ``services.approval.decide`` 决议（保状态机 + 事件）；前置校验 404 / 409。"""
    approval = _require_owned_approval(services, approval_id=approval_id, tenant_id=tenant_id)
    if not approval.is_pending:
        raise DomainError(
            "审批已决议，不可重复决议",
            code=ErrorCode.CONFLICT,
            status_code=409,
            data={"approval_id": approval_id, "status": str(approval.status)},
        )
    updated = services.approval.decide(approval_id, status=status, decided_by=decided_by)
    return _to_response(updated)


@router.get("", response_model=list[ApprovalResponse], summary="待办审批列表")
def list_approvals(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    limit: Annotated[int, Query(ge=1, le=200, description="分页大小")] = 50,
    offset: Annotated[int, Query(ge=0, description="分页偏移")] = 0,
) -> list[ApprovalResponse]:
    """列出当前租户的待决议（``PENDING``）审批（分页）。"""
    pending = services.approval_repository.list_pending(tenant_id=_tenant_id(user))
    page = pending[offset : offset + limit]
    return [_to_response(approval) for approval in page]


@router.get("/{approval_id}", response_model=ApprovalResponse, summary="审批详情")
def get_approval(
    approval_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ApprovalResponse:
    """按 id 获取审批（跨租户 / 不存在 → 404）。"""
    approval = _require_owned_approval(
        services, approval_id=approval_id, tenant_id=_tenant_id(user)
    )
    return _to_response(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse, summary="审批通过")
def approve_approval(
    approval_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ApprovalResponse:
    """决议**通过**（``PENDING → APPROVED``；经 ``ApprovalService.decide``，emit 事件）。"""
    return _decide(
        services,
        approval_id=approval_id,
        tenant_id=_tenant_id(user),
        status=_STATUS_APPROVED,
        decided_by=user.id,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalResponse, summary="审批驳回")
def reject_approval(
    approval_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ApprovalResponse:
    """决议**驳回**（``PENDING → REJECTED``；经 ``ApprovalService.decide``，emit 事件）。"""
    return _decide(
        services,
        approval_id=approval_id,
        tenant_id=_tenant_id(user),
        status=_STATUS_REJECTED,
        decided_by=user.id,
    )
