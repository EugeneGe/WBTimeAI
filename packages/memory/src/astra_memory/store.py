"""``MemoryStore`` 存储抽象（**仅 Protocol**；设计 §2.7 / §5.4；W6 裁定 B7 / T2-34）。

- ``upsert`` / ``search`` / ``delete`` / ``prune`` 四项能力；
- 实现：
  - :class:`~astra_memory.store_sql.SqlMemoryStore`（SQLite / PG 同实现，委派 SQL 仓储）；
  - :class:`~astra_memory.store_vector.VectorMemoryStore`（PG + pgvector，仅
    ``capability.vector_search=true`` 装配）。

🔴 **不得 import** ``astra_runtime``（能力包不依赖 runtime，保无环；W6 裁定 §9-14）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .domain import Memory

__all__ = ["MemoryStore"]


@runtime_checkable
class MemoryStore(Protocol):
    """记忆存储抽象（B7，**冻结**）。"""

    def upsert(self, memory: Memory) -> Memory:
        """写入 / 覆盖一条记忆并返回（按 ``id`` 主键 upsert）。"""
        ...

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
        ...

    def delete(self, memory_id: str, *, tenant_id: str) -> None:
        """按 ``(memory_id, tenant_id)`` 删除记忆（**跨租户不可删**）。"""
        ...

    def prune(self, *, now: datetime) -> int:
        """清理已到期记忆，返回删除条数（TTL / 遗忘）。"""
        ...
