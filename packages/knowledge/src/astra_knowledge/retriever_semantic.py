"""``SemanticRetriever``：PG 语义路（pgvector 余弦检索；W5 / T2-30）。

- 经注入的 :class:`~astra_knowledge.embedder.Embedder` 计算 **query 向量**（显式路由，P1-a）；
- 经 :meth:`~astra_knowledge.domain.EmbeddingRepository.search_semantic` 走 pgvector
  （``<=>`` 余弦距离；``hnsw.ef_search`` 由 PG 会话控制，B1）；
- **引用可回溯**：返回 :class:`~astra_knowledge.retriever.RetrievedChunk`
  （附 ``mode="semantic"``）；
🔴 仅 PostgreSQL + pgvector（``capability.vector_search`` 为真）时可用；SQLite 走
   :class:`~astra_knowledge.retriever_fts.FtsRetriever`（不经本类）。
🔴 本模块**零 Web / ORM**。
"""

from __future__ import annotations

from typing import Any

from .domain import EmbeddingRepository, KnowledgeBaseRepository
from .embedder import Embedder
from .retriever import DEFAULT_KNOWLEDGE_TOP_K, RetrievedChunk, to_retrieved_chunk

__all__ = ["SemanticRetriever"]


class SemanticRetriever:
    """PG 语义检索后端（余弦相似度）。

    Args:
        embedding_repository: 向量仓储（``search_semantic``）。
        knowledge_base_repository: KB 仓储（取 query 路由配置；多 KB 时取首个 KB）。
        embedder: 文本嵌入器（复用 ``ModelProvider.embeddings()``）。
    """

    def __init__(
        self,
        *,
        embedding_repository: EmbeddingRepository,
        knowledge_base_repository: KnowledgeBaseRepository,
        embedder: Embedder,
    ) -> None:
        self._embedding_repository = embedding_repository
        self._kb_repository = knowledge_base_repository
        self._embedder = embedder

    def search(
        self,
        query: str,
        *,
        kb_ids: list[str],
        top_k: int = DEFAULT_KNOWLEDGE_TOP_K,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """按查询文本召回最相似分块（``score`` ＝ 余弦相似度，降序）。

        Args:
            query: 查询文本。
            kb_ids: 命中的 KB 标识集合（非空）。
            top_k: 召回条数上限。
            filters: 保留的过滤参数（当前最小闭环未启用）。

        Returns:
            :class:`~astra_knowledge.retriever.RetrievedChunk` 列表（无 KB 路由 → 空）。
        """
        if not kb_ids or top_k <= 0:
            return []
        # 多 KB 共享同一部署级维度；query 向量按**首个 KB** 的 ``embedding_model`` 显式路由。
        kb = self._kb_repository.get(kb_ids[0])
        if kb is None:
            return []
        vectors = self._embedder.embed([query], kb=kb)
        if not vectors:
            return []
        pairs = self._embedding_repository.search_semantic(
            vectors[0],
            knowledge_base_ids=list(kb_ids),
            top_k=top_k,
            filters=filters,
        )
        return [to_retrieved_chunk(chunk, score, mode="semantic") for chunk, score in pairs]
