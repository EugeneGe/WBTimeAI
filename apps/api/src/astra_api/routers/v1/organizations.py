"""``/api/v1/organizations`` 路由（T0-18：默认组织，最小实现）。"""

from __future__ import annotations

from typing import Annotated

from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas import OrganizationResponse

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _to_response(organization) -> OrganizationResponse:
    """由领域组织构造响应。"""
    return OrganizationResponse(
        id=organization.id,
        tenant_id=organization.tenant_id,
        name=organization.name,
        slug=organization.slug,
    )


@router.get("", response_model=list[OrganizationResponse], summary="组织列表（最小）")
def list_organizations(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[OrganizationResponse]:
    """返回当前用户所属租户的默认组织（Phase 0 最小实现）。"""
    result = services.identity.bootstrap.ensure_default_identity()
    if result.tenant.id != user.tenant_id:
        return []
    return [_to_response(result.organization)]


@router.get("/{organization_id}", response_model=OrganizationResponse, summary="组织详情")
def get_organization(
    organization_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> OrganizationResponse:
    """按 id 返回组织（跨租户 / 不存在 → 404）。"""
    result = services.identity.bootstrap.ensure_default_identity()
    if result.tenant.id != user.tenant_id or result.organization.id != organization_id:
        raise DomainError(
            "组织不存在",
            code=ErrorCode.ORGANIZATION_NOT_FOUND,
            data={"organization_id": organization_id},
        )
    return _to_response(result.organization)
