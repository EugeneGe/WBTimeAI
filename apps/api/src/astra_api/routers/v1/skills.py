"""``/skills`` 路由（W3 / T2-17；设计 §2.3 / §2.12）。

端点：

- ``POST /skills`` · ``GET /skills`` · ``GET /skills/{id}`` · ``PUT /skills/{id}``（CRUD）；
- ``POST /skills/{id}/versions`` · ``GET /skills/{id}/versions``（版本）；
- ``POST /skills/{id}/publish``（发布）。

Router **只**依赖 ``AppServices``（N-8）：**不** import ORM / Runtime / 能力包实现
（``test_layering.py::test_api_routers_have_no_orm_dependency``）；面向**领域 Protocol**
取用仓储。跨租户 / 不存在 → **404**（隔离不变量 I-1）。
"""

from __future__ import annotations

from typing import Annotated, Any

from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.skill import (
    CreateSkillRequest,
    CreateSkillVersionRequest,
    SkillResponse,
    SkillVersionResponse,
    UpdateSkillRequest,
)

router = APIRouter(prefix="/skills", tags=["skills"])

#: 生命周期字面值（与 ``astra_skill`` 领域常量一致）。
_SKILL_STATUS_DRAFT = "DRAFT"
_SKILL_VERSION_STATUS_DRAFT = "DRAFT"
_SKILL_VERSION_STATUS_PUBLISHED = "PUBLISHED"


def _tenant_id(user: Any) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


def _to_skill_response(skill: object, *, current_version: str | None = None) -> SkillResponse:
    """Skill 实体 → 响应（泛化只读映射）。"""
    return SkillResponse(
        id=str(getattr(skill, "id")),  # noqa: B009 - 泛化只读映射
        tenant_id=getattr(skill, "tenant_id", None),
        name=str(getattr(skill, "name", "")),
        display_name=str(getattr(skill, "display_name", "") or ""),
        description=getattr(skill, "description", None),
        category=str(getattr(skill, "category", "") or ""),
        status=str(getattr(skill, "status", _SKILL_STATUS_DRAFT)),
        current_version_id=getattr(skill, "current_version_id", None),
        current_version=current_version,
        created_by=str(getattr(skill, "created_by", "") or ""),
        created_at=getattr(skill, "created_at", None),
    )


def _to_version_response(version: object) -> SkillVersionResponse:
    """SkillVersion 实体 → 响应（泛化只读映射）。"""
    return SkillVersionResponse(
        id=str(getattr(version, "id")),  # noqa: B009 - 泛化只读映射
        skill_id=str(getattr(version, "skill_id", "")),
        version=str(getattr(version, "version", "")),
        instructions=str(getattr(version, "instructions", "") or ""),
        manifest=dict(getattr(version, "manifest", {}) or {}),
        status=str(getattr(version, "status", _SKILL_VERSION_STATUS_DRAFT)),
        created_by=str(getattr(version, "created_by", "") or ""),
        created_at=getattr(version, "created_at", None),
    )


def _require_owned_skill(services: AppServices, *, skill_id: str, tenant_id: str) -> Any:
    """取当前租户下的 Skill，不存在 / 跨租户 → 404。"""
    skill = services.skill.get(skill_id)
    if skill is None or getattr(skill, "tenant_id", None) != tenant_id:
        raise DomainError("Skill 不存在", code=ErrorCode.NOT_FOUND, data={"skill_id": skill_id})
    return skill


@router.post("", response_model=SkillResponse, status_code=201, summary="创建 Skill")
def create_skill(
    payload: CreateSkillRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> SkillResponse:
    """创建一个 Skill（``status = DRAFT``）。"""
    from astra_skill import Skill

    tenant_id = _tenant_id(user)
    existing = services.skill.get_by_name(tenant_id, payload.name)
    if existing is not None:
        raise DomainError(
            "Skill 名已存在",
            code=ErrorCode.CONFLICT,
            data={"name": payload.name},
        )
    skill = services.skill.add(
        Skill(
            tenant_id=tenant_id,
            name=payload.name,
            display_name=payload.display_name or payload.name,
            description=payload.description,
            category=payload.category,
            status=_SKILL_STATUS_DRAFT,
            created_by=user.id,
        )
    )
    return _to_skill_response(skill)


@router.get("", response_model=list[SkillResponse], summary="Skill 列表")
def list_skills(
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[SkillResponse]:
    """列出当前租户的全部 Skill。"""
    return [_to_skill_response(skill) for skill in services.skill.list_by_tenant(_tenant_id(user))]


@router.get("/{skill_id}", response_model=SkillResponse, summary="Skill 详情")
def get_skill(
    skill_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> SkillResponse:
    """按 id 获取 Skill（跨租户 / 不存在 → 404）。"""
    skill = _require_owned_skill(services, skill_id=skill_id, tenant_id=_tenant_id(user))
    return _to_skill_response(skill)


@router.put("/{skill_id}", response_model=SkillResponse, summary="更新 Skill")
def update_skill(
    skill_id: str,
    payload: UpdateSkillRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> SkillResponse:
    """更新 Skill 元数据（仅提供需变更字段）。"""
    skill = _require_owned_skill(services, skill_id=skill_id, tenant_id=_tenant_id(user))
    if payload.display_name is not None:
        skill.display_name = payload.display_name
    if payload.description is not None:
        skill.description = payload.description
    if payload.category is not None:
        skill.category = payload.category
    if payload.status is not None:
        skill.status = payload.status
    updated = services.skill.update(skill)
    return _to_skill_response(updated)


@router.post(
    "/{skill_id}/versions",
    response_model=SkillVersionResponse,
    status_code=201,
    summary="创建 Skill 版本",
)
def create_skill_version(
    skill_id: str,
    payload: CreateSkillVersionRequest,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> SkillVersionResponse:
    """为某 Skill 创建一个 ``DRAFT`` 版本。"""
    from astra_skill import SkillVersion

    _require_owned_skill(services, skill_id=skill_id, tenant_id=_tenant_id(user))
    existing = services.skill_versions.get_by_version(skill_id, payload.version)
    if existing is not None:
        raise DomainError(
            "Skill 版本已存在",
            code=ErrorCode.CONFLICT,
            data={"skill_id": skill_id, "version": payload.version},
        )
    version = services.skill_versions.add(
        SkillVersion(
            skill_id=skill_id,
            version=payload.version,
            instructions=payload.instructions,
            manifest=dict(payload.manifest),
            status=_SKILL_VERSION_STATUS_DRAFT,
            created_by=user.id,
        )
    )
    return _to_version_response(version)


@router.get(
    "/{skill_id}/versions",
    response_model=list[SkillVersionResponse],
    summary="Skill 版本列表",
)
def list_skill_versions(
    skill_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[SkillVersionResponse]:
    """列出某 Skill 的全部版本。"""
    _require_owned_skill(services, skill_id=skill_id, tenant_id=_tenant_id(user))
    return [
        _to_version_response(version) for version in services.skill_versions.list_by_skill(skill_id)
    ]


@router.post(
    "/{skill_id}/publish",
    response_model=SkillVersionResponse,
    summary="发布 Skill 版本",
)
def publish_skill_version(
    skill_id: str,
    user: CurrentUser,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> SkillVersionResponse:
    """发布某 Skill 的**最新** ``DRAFT`` 版本（发布即冻结；``current_version_id`` 更新）。"""
    skill = _require_owned_skill(services, skill_id=skill_id, tenant_id=_tenant_id(user))
    drafts = [
        version
        for version in services.skill_versions.list_by_skill(skill_id)
        if getattr(version, "status", None) == _SKILL_VERSION_STATUS_DRAFT
    ]
    if not drafts:
        raise DomainError(
            "无可发布的 Skill 版本",
            code=ErrorCode.CONFLICT,
            data={"skill_id": skill_id},
        )
    latest = drafts[-1]
    published = services.skill_versions.update(latest.publish())
    skill.current_version_id = published.id
    skill.touch()
    services.skill.update(skill)
    return _to_version_response(published)
