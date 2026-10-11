"""ORM 行 ↔ 领域实体映射（``Memory`` / ``MemoryRelation``）。

将 ``astra_database.models.memory`` 的 SQLAlchemy 行与领域实体互转。

🔴 可空时间戳映射用 :func:`_opt_dt` / ``ensure_utc``，**禁** ``_dt()`` 误填（承接 ``P2-51``）：
   ``expires_at`` 可空——``None`` 必须保持 ``None``（不可回退当前时间）。
🔴 ``vector`` 可空——``None`` 保持 ``None``（SQLite / ``vector_search=false`` 不写向量）。
🔴 落在能力包 ``repositories/``（显式允许的 ORM 落点，能力包仅禁 Web）。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import ensure_utc, utcnow
from astra_database.models.memory import Memory as OrmMemory
from astra_database.models.memory import MemoryRelation as OrmMemoryRelation

from ..domain import Memory, MemoryRelation

__all__ = [
    "memory_to_domain",
    "memory_to_orm",
    "memory_relation_to_domain",
    "memory_relation_to_orm",
]


def _opt_dt(value: datetime | None) -> datetime | None:
    """归一化**可空**时间戳：``None`` 保持 ``None``，否则转 UTC（禁误填）。"""
    return ensure_utc(value) if value is not None else None


def _dt(value: datetime | None) -> datetime:
    """归一化**非空**时间戳：``None`` 时回退当前 UTC（仅用于非空列 / 基类字段）。"""
    return ensure_utc(value) if value is not None else utcnow()


def _opt_vector(value: object) -> list[float] | None:
    """归一化**可空**向量：``None`` 保持 ``None``，否则转 ``list[float]``。"""
    if value is None:
        return None
    return [float(item) for item in value]  # type: ignore[attr-defined]


# -- Memory -----------------------------------------------------------------


def memory_to_domain(row: OrmMemory) -> Memory:
    """ORM ``memory`` 行 → 领域 :class:`~astra_memory.domain.Memory`。"""
    return Memory(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        workspace_id=row.workspace_id,
        kind=row.kind,
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        visibility=row.visibility,
        content=row.content,
        memory_type=row.memory_type,
        importance=float(row.importance),
        confidence=float(row.confidence),
        source_run_id=row.source_run_id,
        vector=_opt_vector(row.vector),
        expires_at=_opt_dt(row.expires_at),
    )


def memory_to_orm(entity: Memory) -> OrmMemory:
    """领域 :class:`~astra_memory.domain.Memory` → ORM ``memory`` 行。"""
    return OrmMemory(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        kind=entity.kind,
        scope_type=entity.scope_type,
        scope_id=entity.scope_id,
        visibility=entity.visibility,
        content=entity.content,
        memory_type=entity.memory_type,
        importance=float(entity.importance),
        confidence=float(entity.confidence),
        source_run_id=entity.source_run_id,
        vector=(_opt_vector(entity.vector) if entity.vector is not None else None),
        expires_at=_opt_dt(entity.expires_at),
    )


# -- MemoryRelation ---------------------------------------------------------


def memory_relation_to_domain(row: OrmMemoryRelation) -> MemoryRelation:
    """ORM ``memory_relation`` 行 → 领域 :class:`~astra_memory.domain.MemoryRelation`。"""
    created_at = _dt(getattr(row, "created_at", None))
    return MemoryRelation(
        id=row.id,
        created_at=created_at,
        updated_at=created_at,
        from_memory_id=row.from_memory_id,
        to_memory_id=row.to_memory_id,
        relation=row.relation,
    )


def memory_relation_to_orm(entity: MemoryRelation) -> OrmMemoryRelation:
    """领域 :class:`~astra_memory.domain.MemoryRelation` → ORM ``memory_relation`` 行。"""
    return OrmMemoryRelation(
        id=entity.id,
        from_memory_id=entity.from_memory_id,
        to_memory_id=entity.to_memory_id,
        relation=entity.relation,
        created_at=_dt(entity.created_at),
    )
