"""``SqlMemoryRepository`` / ``SqlMemoryRelationRepository``（``astra_memory`` 域仓储实现）。

- :class:`SqlMemoryRepository`（``memory`` 表；隔离过滤召回 + TTL 清理）；
- :class:`SqlMemoryRelationRepository`（``memory_relation`` 表；``forget`` 显式级联删关系）。

🔴 落在能力包 ``repositories/``（W6 裁定 §5.3；能力包仅禁 Web，ORM 允许）。
🔴 **强制 ``tenant_id`` 过滤**（隔离不变量 I-2/I-3）；跨租户不可读 / 不可删。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_database import apply_scope, session_scope
from astra_database.models.memory import Memory as OrmMemory
from astra_database.models.memory import MemoryRelation as OrmMemoryRelation
from astra_domain import ScopeFilter
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..domain import Memory, MemoryRelation
from .mappers import (
    memory_relation_to_domain,
    memory_relation_to_orm,
    memory_to_domain,
    memory_to_orm,
)

__all__ = ["SqlMemoryRepository", "SqlMemoryRelationRepository"]


class SqlMemoryRepository:
    """基于 SQLAlchemy 的 ``memory`` 仓储（隔离过滤召回 + TTL 清理）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, memory_id: str) -> Memory | None:
        """按主键获取记忆，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMemory, memory_id)
            return memory_to_domain(row) if row is not None else None

    def add(self, entity: Memory) -> Memory:
        """新增记忆并返回。"""
        with session_scope(self._session_factory) as session:
            row = memory_to_orm(entity)
            session.add(row)
            session.flush()
            return memory_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[Memory]:
        """按等值条件列出记忆（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMemory)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmMemory, field) == value)
            statement = apply_scope(statement, OrmMemory, scope)
            rows = session.execute(statement).scalars().all()
            return [memory_to_domain(row) for row in rows]

    def update(self, entity: Memory) -> Memory:
        """更新记忆并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMemory, entity.id)
            if row is None:
                return memory_to_domain(memory_to_orm(entity))
            row.workspace_id = entity.workspace_id
            row.kind = entity.kind
            row.scope_type = entity.scope_type
            row.scope_id = entity.scope_id
            row.visibility = entity.visibility
            row.content = entity.content
            row.memory_type = entity.memory_type
            row.importance = float(entity.importance)
            row.confidence = float(entity.confidence)
            row.source_run_id = entity.source_run_id
            row.vector = list(entity.vector) if entity.vector is not None else None
            row.expires_at = entity.expires_at
            session.flush()
            return memory_to_domain(row)

    def delete(self, memory_id: str, *, tenant_id: str) -> None:
        """按 ``(memory_id, tenant_id)`` 删除记忆（**跨租户不可删**）。"""
        with session_scope(self._session_factory) as session:
            session.execute(
                delete(OrmMemory).where(OrmMemory.id == memory_id, OrmMemory.tenant_id == tenant_id)
            )

    def search(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        visibility: builtins.list[str] | None = None,
        kinds: builtins.list[str] | None = None,
        text: str | None = None,
        limit: int = 10,
        now: datetime | None = None,
    ) -> builtins.list[Memory]:
        """按隔离维度召回记忆（**先过滤再排序**，按 ``created_at`` 倒序）。

        🔴 过滤顺序（W6 裁定 §3.3）：``tenant_id``（**强制**）→ 作用域 → 可见性 → 类别 →
        关键字 → TTL；返回 **top-k**（``limit <= 0`` 视为不限）。
        """
        reference = now or utcnow()
        with session_scope(self._session_factory) as session:
            statement = select(OrmMemory).where(OrmMemory.tenant_id == tenant_id)
            if scope_type is not None:
                statement = statement.where(OrmMemory.scope_type == scope_type)
            if scope_id is not None:
                statement = statement.where(OrmMemory.scope_id == scope_id)
            if visibility:
                statement = statement.where(OrmMemory.visibility.in_(builtins.list(visibility)))
            if kinds:
                statement = statement.where(OrmMemory.kind.in_(builtins.list(kinds)))
            if text:
                statement = statement.where(OrmMemory.content.like(f"%{text}%"))
            # TTL：排除已过期（``expires_at IS NULL`` 或 ``expires_at > now``）。
            statement = statement.where(
                or_(OrmMemory.expires_at.is_(None), OrmMemory.expires_at > reference)
            )
            statement = statement.order_by(OrmMemory.created_at.desc())
            if limit and limit > 0:
                statement = statement.limit(int(limit))
            rows = session.execute(statement).scalars().all()
            return [memory_to_domain(row) for row in rows]

    def list_by_scope(
        self,
        *,
        tenant_id: str,
        scope_type: str,
        scope_id: str,
        limit: int | None = None,
    ) -> builtins.list[Memory]:
        """列出某租户内某作用域下的记忆（按创建时间倒序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmMemory)
                .where(
                    OrmMemory.tenant_id == tenant_id,
                    OrmMemory.scope_type == scope_type,
                    OrmMemory.scope_id == scope_id,
                )
                .order_by(OrmMemory.created_at.desc())
            )
            if limit is not None and limit > 0:
                statement = statement.limit(int(limit))
            rows = session.execute(statement).scalars().all()
            return [memory_to_domain(row) for row in rows]

    def get_by_source_run(self, run_id: str) -> builtins.list[Memory]:
        """列出某 Run 产出的全部记忆（溯源 / 去重）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMemory).where(OrmMemory.source_run_id == run_id)
            rows = session.execute(statement).scalars().all()
            return [memory_to_domain(row) for row in rows]

    def prune(self, *, now: datetime) -> int:
        """清理已到期记忆（并**显式**删除指向其的关系），返回删除的记忆条数。

        🔴 ``forget`` / TTL **显式级联**（非 DB ``ON DELETE CASCADE``，§13-e）。
        """
        with session_scope(self._session_factory) as session:
            expired_ids = list(
                session.execute(
                    select(OrmMemory.id).where(
                        OrmMemory.expires_at.is_not(None), OrmMemory.expires_at <= now
                    )
                )
                .scalars()
                .all()
            )
            if not expired_ids:
                return 0
            session.execute(
                delete(OrmMemoryRelation).where(
                    or_(
                        OrmMemoryRelation.from_memory_id.in_(expired_ids),
                        OrmMemoryRelation.to_memory_id.in_(expired_ids),
                    )
                )
            )
            session.execute(delete(OrmMemory).where(OrmMemory.id.in_(expired_ids)))
            return len(expired_ids)


class SqlMemoryRelationRepository:
    """基于 SQLAlchemy 的 ``memory_relation`` 仓储（``forget`` 显式级联删关系）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, relation_id: str) -> MemoryRelation | None:
        """按主键获取关系，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMemoryRelation, relation_id)
            return memory_relation_to_domain(row) if row is not None else None

    def add(self, entity: MemoryRelation) -> MemoryRelation:
        """新增关系并返回。"""
        with session_scope(self._session_factory) as session:
            row = memory_relation_to_orm(entity)
            session.add(row)
            session.flush()
            return memory_relation_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[MemoryRelation]:
        """按等值条件列出关系（``scope`` 叠加租户过滤；关系表无组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMemoryRelation)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmMemoryRelation, field) == value)
            statement = apply_scope(statement, OrmMemoryRelation, scope)
            rows = session.execute(statement).scalars().all()
            return [memory_relation_to_domain(row) for row in rows]

    def list_by_from(self, from_memory_id: str) -> builtins.list[MemoryRelation]:
        """列出某源记忆的全部出边关系。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMemoryRelation).where(
                OrmMemoryRelation.from_memory_id == from_memory_id
            )
            rows = session.execute(statement).scalars().all()
            return [memory_relation_to_domain(row) for row in rows]

    def list_by_to(self, to_memory_id: str) -> builtins.list[MemoryRelation]:
        """列出某目标记忆的全部入边关系。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMemoryRelation).where(
                OrmMemoryRelation.to_memory_id == to_memory_id
            )
            rows = session.execute(statement).scalars().all()
            return [memory_relation_to_domain(row) for row in rows]

    def delete_by_memory(self, memory_id: str) -> int:
        """删除与某记忆相关的**全部**关系（出边 + 入边），返回删除条数。"""
        with session_scope(self._session_factory) as session:
            result = session.execute(
                delete(OrmMemoryRelation).where(
                    or_(
                        OrmMemoryRelation.from_memory_id == memory_id,
                        OrmMemoryRelation.to_memory_id == memory_id,
                    )
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)
