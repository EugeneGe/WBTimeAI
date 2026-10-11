"""``SqlSkillRepository`` 等（实现 ``astra_skill`` 的领域仓储 Protocol）。

- :class:`SqlSkillRepository`（``skill`` 表，``(tenant_id, name)`` 唯一）；
- :class:`SqlSkillVersionRepository`（``skill_version`` 表；``update()`` 内置**发布即冻结**
  守卫——已 ``PUBLISHED`` 行的 ``instructions`` / ``manifest`` 变更 → ``CONFLICT``）；
- :class:`SqlSkillResourceRepository`（``skill_resource`` 表）；
- :class:`SqlAgentSkillRepository`（``agent_skill`` 表，``(agent_version_id, skill_id)`` 唯一）。

🔴 落在能力包 ``repositories/``（W2 裁定 R6；能力包仅禁 Web，ORM 允许）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_database import apply_scope, session_scope
from astra_database.models.skill import AgentSkill as OrmAgentSkill
from astra_database.models.skill import Skill as OrmSkill
from astra_database.models.skill import SkillResource as OrmSkillResource
from astra_database.models.skill import SkillVersion as OrmSkillVersion
from astra_domain import AgentSkill, ScopeFilter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..domain import SKILL_VERSION_STATUS_PUBLISHED, Skill, SkillResource, SkillVersion
from .mappers import (
    agent_skill_to_domain,
    agent_skill_to_orm,
    skill_resource_to_domain,
    skill_resource_to_orm,
    skill_to_domain,
    skill_to_orm,
    skill_version_to_domain,
    skill_version_to_orm,
)

__all__ = [
    "SqlSkillRepository",
    "SqlSkillVersionRepository",
    "SqlSkillResourceRepository",
    "SqlAgentSkillRepository",
]


class SqlSkillRepository:
    """基于 SQLAlchemy 的 Skill 仓储（``skill`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Skill | None:
        """按主键获取 Skill，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkill, entity_id)
            return skill_to_domain(row) if row is not None else None

    def get_by_name(self, tenant_id: str, name: str) -> Skill | None:
        """按 ``(tenant_id, name)`` 获取 Skill，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSkill).where(
                OrmSkill.tenant_id == tenant_id, OrmSkill.name == name
            )
            row = session.execute(statement).scalars().first()
            return skill_to_domain(row) if row is not None else None

    def add(self, entity: Skill) -> Skill:
        """新增 Skill 并返回。"""
        with session_scope(self._session_factory) as session:
            row = skill_to_orm(entity)
            session.add(row)
            session.flush()
            return skill_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[Skill]:
        """按等值条件列出 Skill（``scope`` 叠加租户 / 组织过滤；技能表无工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSkill)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmSkill, field) == value)
            statement = apply_scope(statement, OrmSkill, scope)
            rows = session.execute(statement).scalars().all()
            return [skill_to_domain(row) for row in rows]

    def list_by_tenant(self, tenant_id: str) -> builtins.list[Skill]:
        """列出某租户下的全部 Skill。"""
        return self.list(tenant_id=tenant_id)

    def update(self, entity: Skill) -> Skill:
        """更新 Skill 并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkill, entity.id)
            if row is None:
                return skill_to_domain(skill_to_orm(entity))
            row.name = entity.name
            row.display_name = entity.display_name
            row.description = entity.description
            row.category = entity.category
            row.status = entity.status
            row.current_version_id = entity.current_version_id
            session.flush()
            return skill_to_domain(row)

    def delete(self, entity: Skill) -> None:
        """删除 Skill。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkill, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlSkillVersionRepository:
    """基于 SQLAlchemy 的 SkillVersion 仓储（``skill_version`` 表）。

    ``update()`` 内置**发布即冻结**守卫：已 ``PUBLISHED`` 行的 ``instructions`` /
    ``manifest`` 与库中值不一致 → ``DomainError(CONFLICT, published_immutable)``（仅允许
    ``status`` 变更）。此为 R4 §4.1 的**仓储层**不可变保证（域层为第一道保证）。
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> SkillVersion | None:
        """按主键获取版本，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkillVersion, entity_id)
            return skill_version_to_domain(row) if row is not None else None

    def get_by_version(self, skill_id: str, version: str) -> SkillVersion | None:
        """按 ``(skill_id, version)`` 获取版本，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSkillVersion).where(
                OrmSkillVersion.skill_id == skill_id, OrmSkillVersion.version == version
            )
            row = session.execute(statement).scalars().first()
            return skill_version_to_domain(row) if row is not None else None

    def add(self, entity: SkillVersion) -> SkillVersion:
        """新增版本并返回。"""
        with session_scope(self._session_factory) as session:
            row = skill_version_to_orm(entity)
            session.add(row)
            session.flush()
            return skill_version_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[SkillVersion]:
        """按等值条件列出版本（``scope`` 叠加过滤；版本表无租户 / 组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSkillVersion)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmSkillVersion, field) == value)
            statement = apply_scope(statement, OrmSkillVersion, scope)
            rows = session.execute(statement).scalars().all()
            return [skill_version_to_domain(row) for row in rows]

    def list_by_skill(self, skill_id: str) -> builtins.list[SkillVersion]:
        """列出某 Skill 的全部版本（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmSkillVersion)
                .where(OrmSkillVersion.skill_id == skill_id)
                .order_by(OrmSkillVersion.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [skill_version_to_domain(row) for row in rows]

    def update(self, entity: SkillVersion) -> SkillVersion:
        """更新版本并返回；已发布行的 ``instructions`` / ``manifest`` 变更被拒。

        Raises:
            DomainError: 已 ``PUBLISHED`` 行的 ``instructions`` / ``manifest`` 变更
                （``CONFLICT``，``reason="published_immutable"``）。
        """
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkillVersion, entity.id)
            if row is None:
                return skill_version_to_domain(skill_version_to_orm(entity))
            if row.status == SKILL_VERSION_STATUS_PUBLISHED:
                if row.instructions != entity.instructions or dict(row.manifest or {}) != dict(
                    entity.manifest or {}
                ):
                    raise DomainError(
                        "已发布的 SkillVersion 不可变更 instructions / manifest",
                        code=ErrorCode.CONFLICT,
                        data={"reason": "published_immutable", "skill_version_id": entity.id},
                    )
            row.instructions = entity.instructions
            row.manifest = dict(entity.manifest or {})
            row.status = entity.status
            session.flush()
            return skill_version_to_domain(row)

    def delete(self, entity: SkillVersion) -> None:
        """删除版本。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkillVersion, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlSkillResourceRepository:
    """基于 SQLAlchemy 的 SkillResource 仓储（``skill_resource`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> SkillResource | None:
        """按主键获取资源，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkillResource, entity_id)
            return skill_resource_to_domain(row) if row is not None else None

    def add(self, entity: SkillResource) -> SkillResource:
        """新增资源并返回。"""
        with session_scope(self._session_factory) as session:
            row = skill_resource_to_orm(entity)
            session.add(row)
            session.flush()
            return skill_resource_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[SkillResource]:
        """按等值条件列出资源（``scope`` 叠加过滤；资源表无租户 / 组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmSkillResource)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmSkillResource, field) == value)
            statement = apply_scope(statement, OrmSkillResource, scope)
            rows = session.execute(statement).scalars().all()
            return [skill_resource_to_domain(row) for row in rows]

    def list_by_version(self, skill_version_id: str) -> builtins.list[SkillResource]:
        """列出某 SkillVersion 的全部资源（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmSkillResource)
                .where(OrmSkillResource.skill_version_id == skill_version_id)
                .order_by(OrmSkillResource.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [skill_resource_to_domain(row) for row in rows]

    def update(self, entity: SkillResource) -> SkillResource:
        """更新资源并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkillResource, entity.id)
            if row is None:
                return skill_resource_to_domain(skill_resource_to_orm(entity))
            row.path = entity.path
            row.kind = entity.kind
            row.storage_key = entity.storage_key
            row.checksum = entity.checksum
            row.size = entity.size
            session.flush()
            return skill_resource_to_domain(row)

    def delete(self, entity: SkillResource) -> None:
        """删除资源。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmSkillResource, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlAgentSkillRepository:
    """基于 SQLAlchemy 的 AgentSkill 绑定仓储（``agent_skill`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> AgentSkill | None:
        """按主键获取绑定，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentSkill, entity_id)
            return agent_skill_to_domain(row) if row is not None else None

    def add(self, entity: AgentSkill) -> AgentSkill:
        """新增绑定并返回。"""
        with session_scope(self._session_factory) as session:
            row = agent_skill_to_orm(entity)
            session.add(row)
            session.flush()
            return agent_skill_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[AgentSkill]:
        """按等值条件列出绑定（``scope`` 叠加租户过滤；绑定表无组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAgentSkill)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmAgentSkill, field) == value)
            statement = apply_scope(statement, OrmAgentSkill, scope)
            rows = session.execute(statement).scalars().all()
            return [agent_skill_to_domain(row) for row in rows]

    def list_by_agent_version(self, agent_version_id: str) -> builtins.list[AgentSkill]:
        """列出某 AgentVersion 绑定的全部 Skill（按 ``id`` 升序：``id`` 为时间有序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAgentSkill)
                .where(OrmAgentSkill.agent_version_id == agent_version_id)
                .order_by(OrmAgentSkill.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [agent_skill_to_domain(row) for row in rows]

    def update(self, entity: AgentSkill) -> AgentSkill:
        """更新绑定并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentSkill, entity.id)
            if row is None:
                return agent_skill_to_domain(agent_skill_to_orm(entity))
            row.agent_version_id = entity.agent_version_id
            row.skill_id = entity.skill_id
            row.enabled = entity.enabled
            row.config = dict(entity.config or {}) or None
            session.flush()
            return agent_skill_to_domain(row)

    def delete(self, entity: AgentSkill) -> None:
        """删除绑定。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmAgentSkill, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()
