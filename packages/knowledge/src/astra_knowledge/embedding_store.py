"""``EmbeddingStore``（四步写入第 ③④ 步；PG 落库 / SQLite no-op；W5 / T2-29）。

- ``capability.vector_search`` 为真（PG + pgvector）：落 ``embedding`` 行，并回填
  ``document_chunk.embedding_id``（四步写入 ③ 插 embedding → ④ UPDATE 反查缓存）；
- 为假（SQLite，R-40）：**直接 no-op**（不写 ``embedding`` 表，``embedding_id`` 保持 ``NULL``）。

🔴 检索**统一以 ``embedding.chunk_id`` 反查**；``embedding_id`` 仅作反查缓存。
🔴 落在能力包（ORM 经注入的领域 Protocol 使用）。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode

from .domain import (
    DocumentChunk,
    DocumentChunkRepository,
    Embedding,
    EmbeddingRepository,
    KnowledgeBase,
)

__all__ = ["EmbeddingStore"]


class EmbeddingStore:
    """向量写入器（capability 选路；SQLite no-op）。

    Args:
        embedding_repository: 向量仓储（``embedding`` 表）。
        chunk_repository: 分块仓储（回填 ``embedding_id``）。
        vector_search: 能力包汇入的布尔值（组合根按 dialect + 扩展解析，B5）。
    """

    def __init__(
        self,
        *,
        embedding_repository: EmbeddingRepository,
        chunk_repository: DocumentChunkRepository,
        vector_search: bool,
    ) -> None:
        self._embedding_repository = embedding_repository
        self._chunk_repository = chunk_repository
        self._vector_search = bool(vector_search)

    @property
    def vector_search(self) -> bool:
        """是否启用向量写入（capability）。"""
        return self._vector_search

    def write(
        self,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        *,
        kb: KnowledgeBase,
    ) -> list[Embedding]:
        """写入向量并回填 ``embedding_id``（SQLite 下 no-op）。

        Args:
            chunks: 已落库的分块（``id`` 非空；四步写入第 ① 步产物）。
            vectors: 与 ``chunks`` 一一对应的向量。
            kb: 知识库（提供 ``embedding_model.model``）。

        Returns:
            已写入的向量实体（SQLite no-op 时为空列表）。

        Raises:
            DomainError: ``chunks`` 与 ``vectors`` 长度不符（``VALIDATION_ERROR``）。
        """
        if not self._vector_search:
            return []
        if len(chunks) != len(vectors):
            raise DomainError(
                f"chunks 与 vectors 数量不符：{len(chunks)} != {len(vectors)}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"reason": "embedding_count_mismatch"},
            )
        if not chunks:
            return []

        model = str((kb.embedding_model or {}).get("model", ""))
        entities = [
            Embedding(
                chunk_id=chunk.id,
                model=model,
                dimensions=len(vector),
                vector=[float(value) for value in vector],
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        saved = self._embedding_repository.add_many(entities)
        # 四步写入 ④：回填反查缓存（可空、可重建；失败**不回滚**主链）。
        for chunk, embedding in zip(chunks, saved, strict=True):
            self._chunk_repository.set_embedding_id(chunk.id, embedding.id)
        return saved
