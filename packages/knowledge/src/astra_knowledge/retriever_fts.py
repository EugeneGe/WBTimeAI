"""``FtsRetriever``：SQLite FTS5 关键字路（``MATCH`` + ``bm25``；W5 / T2-30）。

- 经注入的 :class:`~astra_knowledge.domain.DocumentChunkRepository` 的
  :meth:`~astra_knowledge.domain.DocumentChunkRepository.search_fts` 走 external-content
  FTS5 虚表（``document_chunk_fts``，B11）；
- **引用可回溯**：返回 :class:`~astra_knowledge.retriever.RetrievedChunk`
  （附 ``mode="keyword"``，供 UI 提示「当前存储后端不支持语义检索，已使用关键字检索」，R-40）。

🔴 仅 SQLite（``capability.vector_search`` 为假）时可用；PostgreSQL 走
   :class:`~astra_knowledge.retriever_semantic.SemanticRetriever`（不经本类）。
🔴 本模块**零 Web / ORM**（SQL 落 ``repositories/``）。
"""

from __future__ import annotations

from typing import Any

from .domain import DocumentChunkRepository
from .retriever import DEFAULT_KNOWLEDGE_TOP_K, RetrievedChunk, to_retrieved_chunk

__all__ = ["FtsRetriever"]


class FtsRetriever:
    """SQLite FTS5 关键字检索后端（``bm25`` 排序）。

    Args:
        chunk_repository: 分块仓储（``search_fts``，SQL 落 ``repositories/``）。
    """

    def __init__(self, *, chunk_repository: DocumentChunkRepository) -> None:
        self._chunk_repository = chunk_repository

    def search(
        self,
        query: str,
        *,
        kb_ids: list[str],
        top_k: int = DEFAULT_KNOWLEDGE_TOP_K,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """按关键字召回分块（``score`` ＝ ``-bm25``，**越大越相关**）。

        Args:
            query: 查询文本。
            kb_ids: 命中的 KB 标识集合（非空）。
            top_k: 召回条数上限。
            filters: 保留的过滤参数（当前最小闭环未启用）。

        Returns:
            :class:`~astra_knowledge.retriever.RetrievedChunk` 列表（无匹配 → 空）。
        """
        if not kb_ids or top_k <= 0:
            return []
        pairs = self._chunk_repository.search_fts(
            query, knowledge_base_ids=list(kb_ids), top_k=top_k
        )
        return [to_retrieved_chunk(chunk, score, mode="keyword") for chunk, score in pairs]
