"""``SqlMemoryStore``（SQLite / PG 同实现；设计 §5.4；W6 裁定 B7 / T2-34）。

- 委派 :class:`~astra_memory.repositories.SqlMemoryRepository` 完成 SQL 读写；
- ``vector_search=false``（SQLite）时**跳过向量**（``memory.vector`` 恒 ``NULL``）；
- ``upsert`` ＝ 存在即更新 / 否则插入（按 ``id`` 主键）。

🔴 落在能力包（非 ``domain/``，允许依赖 ORM 实现）。
"""

from __future__ import annotations

from datetime import datetime

from .domain import Memory
from .repositories import SqlMemoryRepository

__all__ = ["SqlMemoryStore"]


class SqlMemoryStore:
    """基于 SQL 仓储的记忆存储（SQLite / PG 同实现）。

    Args:
        repository: ``memory`` SQL 仓储（隔离过滤召回 + TTL 清理）。
    """

    def __init__(self, *, repository: SqlMemoryRepository) -> None:
        self._repository = repository

    @property
    def repository(self) -> SqlMemoryRepository:
        """底层 ``memory`` SQL 仓储（供装配 / 断言）。"""
        return self._repository

    def upsert(self, memory: Memory) -> Memory:
        """写入 / 覆盖一条记忆并返回（按 ``id`` 主键 upsert）。"""
        existing = self._repository.get(memory.id)
        if existing is None:
            return self._repository.add(memory)
        return self._repository.update(memory)

    def search(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        visibility: list[str] | None = None,
        kinds: list[str] | None = None,
        text: str | None = None,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[Memory]:
        """按隔离维度召回记忆（**强制 ``tenant_id`` 过滤**，先过滤再排序）。"""
        return self._repository.search(
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_id=scope_id,
            visibility=visibility,
            kinds=kinds,
            text=text,
            limit=limit,
            now=now,
        )

    def delete(self, memory_id: str, *, tenant_id: str) -> None:
        """按 ``(memory_id, tenant_id)`` 删除记忆（**跨租户不可删**）。"""
        self._repository.delete(memory_id, tenant_id=tenant_id)

    def prune(self, *, now: datetime) -> int:
        """清理已到期记忆（并**显式**删除指向其的关系），返回删除条数。"""
        return int(self._repository.prune(now=now))
