"""Embedder / VectorType / EmbeddingStore 方言与维度集成测试（W5 / T2-29）。

覆盖（W5 开工前架构裁定 §2.3 / B4 / B5 / R-40）：

- :class:`VectorType` 在 SQLite 渲染 JSON；PG 缺 ``pgvector`` 时降级 JSON（I-P2-08）；
- :class:`Embedder` 复用 ``ModelProvider.embeddings()``，维度不匹配即拒（I-P2-25）；
- :class:`EmbeddingStore`：``vector_search=False``（SQLite）→ **no-op**（不写 ``embedding``）；
  ``vector_search=True`` → 落库 + 回填 ``embedding_id``（SQLite 侧亦有存储能力，双向可用）。
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from astra_core import DomainError, ErrorCode
from astra_database.types import VectorType
from astra_knowledge import (
    Document,
    DocumentChunk,
    Embedder,
    EmbeddingStore,
    KnowledgeBase,
    SqlDocumentChunkRepository,
    SqlDocumentRepository,
    SqlEmbeddingRepository,
    SqlKnowledgeBaseRepository,
)
from astra_model import ModelRegistry, ModelRouter
from astra_model.stub import StubModelProvider

_EMBED_DIMENSION = 8


# -- VectorType 方言 ----------------------------------------------------------


def test_vector_type_sqlite_renders_json() -> None:
    """SQLite：``VectorType`` 渲染为 ``JSON``。"""
    from sqlalchemy.dialects import sqlite

    impl = VectorType(_EMBED_DIMENSION).load_dialect_impl(sqlite.dialect())
    assert isinstance(impl, sa.JSON)


def test_vector_type_postgres_degrades_without_pgvector() -> None:
    """PG：``pgvector`` 缺失时降级 ``JSON``；可用时为原生 ``vector``。"""
    from sqlalchemy.dialects import postgresql

    try:
        import pgvector.sqlalchemy  # noqa: F401

        has_pgvector = True
    except ImportError:
        has_pgvector = False

    impl = VectorType(_EMBED_DIMENSION).load_dialect_impl(postgresql.dialect())
    if has_pgvector:  # pragma: no cover - 取决于是否安装 pgvector
        assert not isinstance(impl, sa.JSON)
    else:
        assert isinstance(impl, sa.JSON)


# -- Embedder -----------------------------------------------------------------


def _router(dimension: int = _EMBED_DIMENSION) -> ModelRouter:
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider(dimension=dimension))
    return ModelRouter(registry)


def _kb(dimensions: int = _EMBED_DIMENSION) -> KnowledgeBase:
    return KnowledgeBase(
        tenant_id="t1",
        name="kb1",
        created_by="u1",
        embedding_model={
            "provider": "stub",
            "model": "stub-embed",
            "dimensions": dimensions,
        },
        chunk_config={"strategy": "fixed", "size": 800, "overlap": 100},
    )


def test_embedder_returns_vectors() -> None:
    """复用 ``embeddings()``：返回按输入顺序、维度正确的向量。"""
    embedder = Embedder(model_router=_router(), embedding_dimensions=_EMBED_DIMENSION)
    vectors = embedder.embed(["hello", "world"], kb=_kb())
    assert len(vectors) == 2
    assert all(len(vector) == _EMBED_DIMENSION for vector in vectors)


def test_embedder_empty_input() -> None:
    """空输入 → 空输出。"""
    embedder = Embedder(model_router=_router(), embedding_dimensions=_EMBED_DIMENSION)
    assert embedder.embed([], kb=_kb()) == []


def test_embedder_rejects_kb_dimension_mismatch() -> None:
    """KB 维度 ≠ 部署级维度 → 拒绝（I-P2-25）。"""
    embedder = Embedder(model_router=_router(), embedding_dimensions=16)
    with pytest.raises(DomainError) as exc:
        embedder.embed(["x"], kb=_kb(_EMBED_DIMENSION))
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    assert exc.value.data.get("reason") == "embedding_dimension_mismatch"


def test_embedder_rejects_provider_vector_mismatch() -> None:
    """Provider 返回向量长度 ≠ 部署级维度 → 拒绝（I-P2-25）。"""
    embedder = Embedder(model_router=_router(dimension=4), embedding_dimensions=_EMBED_DIMENSION)
    with pytest.raises(DomainError) as exc:
        embedder.embed(["x"], kb=_kb(_EMBED_DIMENSION))
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    assert exc.value.data.get("reason") == "embedding_dimension_mismatch"


# -- EmbeddingStore -----------------------------------------------------------


def _seed(session_factory) -> tuple[KnowledgeBase, SqlDocumentChunkRepository, list[DocumentChunk]]:
    kb_repository = SqlKnowledgeBaseRepository(session_factory)
    document_repository = SqlDocumentRepository(session_factory)
    chunk_repository = SqlDocumentChunkRepository(session_factory)

    saved_kb = kb_repository.add(_kb())
    document = document_repository.add(
        Document(knowledge_base_id=saved_kb.id, title="doc", status="EMBEDDING")
    )
    chunks = chunk_repository.add_many(
        [
            DocumentChunk(document_id=document.id, ordinal=index, content=f"chunk-{index}")
            for index in range(2)
        ]
    )
    return saved_kb, chunk_repository, chunks


def test_embedding_store_noop_when_vector_search_disabled(session_factory) -> None:
    """SQLite（``vector_search=False``）→ 不写 ``embedding`` 表，``embedding_id`` 保持 ``None``。"""
    kb, chunk_repository, chunks = _seed(session_factory)
    store = EmbeddingStore(
        embedding_repository=SqlEmbeddingRepository(session_factory),
        chunk_repository=chunk_repository,
        vector_search=False,
    )
    vectors = [[0.0] * _EMBED_DIMENSION, [0.1] * _EMBED_DIMENSION]
    assert store.write(chunks, vectors, kb=kb) == []
    assert SqlEmbeddingRepository(session_factory).list() == []
    reloaded = [chunk_repository.get(chunk.id) for chunk in chunks]
    assert all(item is not None and item.embedding_id is None for item in reloaded)


def test_embedding_store_writes_and_backfills(session_factory) -> None:
    """``vector_search=True`` → 落库 + 回填 ``embedding_id``（SQLite JSON 存储，双向可用）。"""
    kb, chunk_repository, chunks = _seed(session_factory)
    embedding_repository = SqlEmbeddingRepository(session_factory)
    store = EmbeddingStore(
        embedding_repository=embedding_repository,
        chunk_repository=chunk_repository,
        vector_search=True,
    )
    vectors = [[float(index)] * _EMBED_DIMENSION for index in range(2)]
    saved = store.write(chunks, vectors, kb=kb)
    assert len(saved) == 2
    assert all(item.dimensions == _EMBED_DIMENSION for item in saved)
    reloaded = chunk_repository.get(chunks[0].id)
    assert reloaded is not None
    assert reloaded.embedding_id == saved[0].id
    # 主链反查：embedding.chunk_id → document_chunk.id
    assert embedding_repository.get_by_chunk(chunks[0].id) is not None
