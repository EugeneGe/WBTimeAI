"""``VectorMemoryStore``（PG + pgvector，可选；设计 §5.4 / §3.5；W6 裁定 B7 / T2-34）。

- **仅当** ``capability.vector_search=true``（PostgreSQL + pgvector）时由组合根装配；
- 在 :class:`~astra_memory.store_sql.SqlMemoryStore` 之上**加性**：
  - ``upsert`` 时对无向量的记忆计算并写入 ``memory.vector``（经注入 ``embedder``）；
  - ``search`` 时对 ``text`` 计算查询向量并按**余弦相似度**重排（有向量者优先）；
- 未注入 ``embedder``（如本地测试）时退化为 SQL 存储行为（**不强写向量**）。

🔴 SQLite（``vector_search=false``）**不装配**本类（B7）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime

from .domain import Memory
from .store_sql import SqlMemoryStore

__all__ = ["VectorMemoryStore"]

#: 默认向量维度（＝ ``capability.embedding_dimensions``）。
DEFAULT_VECTOR_DIMENSIONS = 1536


class VectorMemoryStore:
    """PG 语义召回存储（在 SQL 存储之上加性：写入 / 按余弦相似度重排）。

    Args:
        store: 底层 :class:`~astra_memory.store_sql.SqlMemoryStore`（SQL 读写）。
        embedder: 文本 → 向量函数（``None`` ＝ 跳过向量写入 / 重排）。
        dimensions: 向量维度（校验用）。
    """

    def __init__(
        self,
        *,
        store: SqlMemoryStore,
        embedder: Callable[[str], list[float]] | None = None,
        dimensions: int = DEFAULT_VECTOR_DIMENSIONS,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._dimensions = int(dimensions)

    @property
    def store(self) -> SqlMemoryStore:
        """底层 SQL 存储（供装配 / 断言）。"""
        return self._store

    @property
    def vector_search(self) -> bool:
        """恒 ``True``（本类仅 ``vector_search=true`` 时装配）。"""
        return True

    def upsert(self, memory: Memory) -> Memory:
        """写入 / 覆盖一条记忆（无向量时按 ``content`` 计算并写入）。"""
        if memory.vector is None and self._embedder is not None and (memory.content or "").strip():
            memory.vector = self._embedder(memory.content)
        return self._store.upsert(memory)

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
        """按隔离维度召回 + 按**余弦相似度**重排（有向量者优先；无向量者置末）。"""
        memories = self._store.search(
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_id=scope_id,
            visibility=visibility,
            kinds=kinds,
            text=text,
            limit=limit,
            now=now,
        )
        if self._embedder is None or not text:
            return memories
        query_vector = self._embedder(text)
        return sorted(
            memories,
            key=lambda memory: _cosine(query_vector, memory.vector),
            reverse=True,
        )

    def delete(self, memory_id: str, *, tenant_id: str) -> None:
        """按 ``(memory_id, tenant_id)`` 删除记忆。"""
        self._store.delete(memory_id, tenant_id=tenant_id)

    def prune(self, *, now: datetime) -> int:
        """清理已到期记忆，返回删除条数。"""
        return self._store.prune(now=now)


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    """余弦相似度；任一为空 / 维度不符 → ``-1.0``（置末）。"""
    if not left or not right or len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return -1.0
    return dot / (norm_left * norm_right)
