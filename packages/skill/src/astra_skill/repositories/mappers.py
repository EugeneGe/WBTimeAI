"""ORM 行 ↔ 领域实体映射（Skill / SkillVersion / SkillResource / AgentSkill）。

将 ``astra_database.models.skill`` 的 SQLAlchemy 行与领域实体互转。

🔴 落在能力包 ``repositories/``（显式允许的 ORM 落点，能力包仅禁 Web）。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import utcnow
from astra_database.models.skill import AgentSkill as OrmAgentSkill
from astra_database.models.skill import Skill as OrmSkill
from astra_database.models.skill import SkillResource as OrmSkillResource
from astra_database.models.skill import SkillVersion as OrmSkillVersion
from astra_domain import AgentSkill

from ..domain import Skill, SkillResource, SkillVersion

__all__ = [
    "skill_to_domain",
    "skill_to_orm",
    "skill_version_to_domain",
    "skill_version_to_orm",
    "skill_resource_to_domain",
    "skill_resource_to_orm",
    "agent_skill_to_domain",
    "agent_skill_to_orm",
]


def _dt(value: datetime | None) -> datetime:
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


# -- Skill ------------------------------------------------------------------


def skill_to_domain(row: OrmSkill) -> Skill:
    """ORM Skill 行 → 领域 ``Skill``。"""
    return Skill(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        category=row.category,
        status=row.status,
        current_version_id=row.current_version_id,
        created_by=row.created_by,
    )


def skill_to_orm(entity: Skill) -> OrmSkill:
    """领域 ``Skill`` → ORM 行。"""
    return OrmSkill(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        name=entity.name,
        display_name=entity.display_name,
        description=entity.description,
        category=entity.category,
        status=entity.status,
        current_version_id=entity.current_version_id,
        created_by=entity.created_by,
    )


# -- SkillVersion -----------------------------------------------------------


def skill_version_to_domain(row: OrmSkillVersion) -> SkillVersion:
    """ORM SkillVersion 行 → 领域 ``SkillVersion``（不可变）。"""
    return SkillVersion(
        id=row.id,
        skill_id=row.skill_id,
        version=row.version,
        instructions=row.instructions,
        manifest=dict(row.manifest or {}),
        status=row.status,
        created_by=row.created_by,
        created_at=_dt(getattr(row, "created_at", None)),
    )


def skill_version_to_orm(entity: SkillVersion) -> OrmSkillVersion:
    """领域 ``SkillVersion`` → ORM 行。"""
    return OrmSkillVersion(
        id=entity.id,
        skill_id=entity.skill_id,
        version=entity.version,
        instructions=entity.instructions,
        manifest=dict(entity.manifest or {}),
        status=entity.status,
        created_by=entity.created_by,
        created_at=_dt(entity.created_at),
    )


# -- SkillResource ----------------------------------------------------------


def skill_resource_to_domain(row: OrmSkillResource) -> SkillResource:
    """ORM SkillResource 行 → 领域 ``SkillResource``。"""
    return SkillResource(
        id=row.id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "created_at", None)),
        skill_version_id=row.skill_version_id,
        path=row.path,
        kind=row.kind,
        storage_key=row.storage_key,
        checksum=row.checksum,
        size=row.size,
    )


def skill_resource_to_orm(entity: SkillResource) -> OrmSkillResource:
    """领域 ``SkillResource`` → ORM 行。"""
    return OrmSkillResource(
        id=entity.id,
        skill_version_id=entity.skill_version_id,
        path=entity.path,
        kind=entity.kind,
        storage_key=entity.storage_key,
        checksum=entity.checksum,
        size=entity.size,
        created_at=_dt(entity.created_at),
    )


# -- AgentSkill -------------------------------------------------------------


def agent_skill_to_domain(row: OrmAgentSkill) -> AgentSkill:
    """ORM AgentSkill 行 → 领域 ``AgentSkill``。"""
    return AgentSkill(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        agent_version_id=row.agent_version_id,
        skill_id=row.skill_id,
        enabled=bool(row.enabled),
        config=dict(row.config or {}),
    )


def agent_skill_to_orm(entity: AgentSkill) -> OrmAgentSkill:
    """领域 ``AgentSkill`` → ORM 行。"""
    return OrmAgentSkill(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        agent_version_id=entity.agent_version_id,
        skill_id=entity.skill_id,
        enabled=entity.enabled,
        config=dict(entity.config or {}) or None,
    )
