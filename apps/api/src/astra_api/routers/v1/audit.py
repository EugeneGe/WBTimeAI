"""``/audit`` 路由（W3 / T2-17；设计 §2.18 / §2.12）。

端点：

- ``GET /audit``：基础审计消费（按 ``user / action / resource / 时间`` 过滤 + 分页）。

Router **只**依赖 ``AppServices``（N-8）；经领域 Protocol ``AuditRepository`` 读取
（**不** import ORM）。审计记录为**只读消费**（写入经运行时的高层通道）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.audit import AuditLogResponse

router = APIRouter(prefix="/audit", tags=["audit"])


def _tenant_id(user: Any) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_response(record: object) -> AuditLogResponse:
    """AuditLog 实体 → 响应（**四要素** who / action / resource / outcome）。"""
    return AuditLogResponse(
        id=str(getattr(record, "id")),  # noqa: B009 - 泛化只读映射
        tenant_id=getattr(record, "tenant_id", None),
        user_id=getattr(record, "user_id", None),
        agent_id=getattr(record, "agent_id", None),
        run_id=getattr(record, "run_id", None),
        action=str(getattr(record, "action", "") or ""),
        resource_type=getattr(record, "resource_type", None),
        resource_id=getattr(record, "resource_id", None),
        outcome=str(getattr(record, "outcome", "SUCCESS")),
        duration_ms=getattr(record, "duration_ms", None),
        request_id=getattr(record, "request_id", None),
        created_at=getattr(record, "created_at", None),
    )


def _matches(
    record: object,
    *,
    user_id: str | None,
    action: str | None,
    resource_type: str | None,
    resource_id: str | None,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    """按过滤条件判定记录是否命中。"""
    if user_id is not None and getattr(record, "user_id", None) != user_id:
        return False
    if action is not None and getattr(record, "action", None) != action:
        return False
    if resource_type is not None and getattr(record, "resource_type", None) != resource_type:
        return False
    if resource_id is not None and getattr(record, "resource_id", None) != resource_id:
        return False
    created_at = getattr(record, "created_at", None)
    if since is not None and (created_at is None or created_at < since):
        return False
    if until is not None and (created_at is None or created_at > until):
        return False
    return True


@router.get("", response_model=list[AuditLogResponse], summary="审计记录（过滤 + 分页）")
def list_audit(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    user_id: Annotated[str | None, Query(description="按 who（用户）过滤")] = None,
    action: Annotated[str | None, Query(description="按 action 过滤")] = None,
    resource_type: Annotated[str | None, Query(description="按 resource 类型过滤")] = None,
    resource_id: Annotated[str | None, Query(description="按 resource 标识过滤")] = None,
    since: Annotated[datetime | None, Query(description="起始时间（ISO8601）")] = None,
    until: Annotated[datetime | None, Query(description="结束时间（ISO8601）")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="分页大小")] = 50,
    offset: Annotated[int, Query(ge=0, description="分页偏移")] = 0,
) -> list[AuditLogResponse]:
    """列出当前租户的审计记录（按创建时间倒序，支持过滤 + 分页）。"""
    # 拉取略大于 offset+limit 的量再做内存过滤（骨架期；PG 权威实现可下推 SQL）。
    fetch_limit = offset + limit
    records = services.audit_repository.list_by_tenant(_tenant_id(user), limit=max(fetch_limit, 1))
    filtered = [
        record
        for record in records
        if _matches(
            record,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            since=since,
            until=until,
        )
    ]
    page = filtered[offset : offset + limit]
    return [_to_response(record) for record in page]
