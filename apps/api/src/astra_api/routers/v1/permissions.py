"""``/permissions`` 路由（W3 / T2-14；设计 §2.10.2）。

端点：

- ``GET /permissions/check?cap=...``：capability 检查（**后端判定输入源**）。

Router **只**依赖 ``AppServices``（N-8）；授权判定**委托** ``ResourcePermissionChecker``
（单一判定链，T2-13）——Router 无 ORM / Runtime 直调。
"""

from __future__ import annotations

from typing import Annotated

from astra_domain import PermissionQuery
from fastapi import APIRouter, Depends, Query

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.permission import PermissionCheckResponse

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get(
    "/check",
    response_model=PermissionCheckResponse,
    summary="能力检查（can() 数据源）",
)
def check_capability(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
    cap: Annotated[str, Query(min_length=1, description="待判定 capability，如 tool:git.commit")],
) -> PermissionCheckResponse:
    """判定当前用户是否具备某 capability（前端 ``can()`` 唯一输入源）。"""
    query = PermissionQuery(
        tenant_id=user.tenant_id or "",
        subject_type="user",
        subject_id=user.id,
        capability=cap,
    )
    decision = services.permission.check_capability(query)
    return PermissionCheckResponse(
        capability=cap,
        allowed=decision.allowed,
        effect=decision.effect,
        reason=decision.reason,
        source=decision.source,
    )
