"""索引任务韧性集成测试（W5 / T2-31）。

覆盖（W5 开工前架构裁定 §5.1 / §5.3 / B9 / B10 / R-23 / I-P2-21 / I-P2-27）：

- **状态机闭环**：``PENDING → … → READY``；幂等（已 ``READY`` 直接返回）；
- **失败**：原文不可得 → ``document.status=FAILED`` + ``error`` 落库；
- **重试 + 断点续跑**：``FAILED → PARSING`` 重入，已完成 ``(document_id, ordinal)`` 跳过（无重复）；
- **嵌入**：``vector_search=True`` → 落 ``embedding`` + 回填 ``embedding_id``；为假则跳过；
- **worker 处理器**：经 ``ctx.services["knowledge_index"]`` 调用 + ``payload.attempt`` 递增（B9）；
  未注入 → ``NotImplementedYetError``；缺 ``document_id`` → ``VALIDATION_ERROR``；注册表已登记。
"""

from __future__ import annotations

from typing import Any

import pytest
from astra_core import DomainError, ErrorCode, NotImplementedYetError
from astra_knowledge import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    KnowledgeIndexTask,
    SqlDocumentChunkRepository,
    SqlDocumentRepository,
    SqlEmbeddingRepository,
    SqlKnowledgeBaseRepository,
    build_knowledge_index_task,
)
from astra_model import ModelRegistry, ModelRouter
from astra_model.stub import StubModelProvider

_EMBED_DIMENSION = 8
_SOURCE_KEY = "kb/doc.txt"
_SOURCE_BYTES = ("Astra AI knowledge indexing resilience " * 130).encode("utf-8")


class _FakeStorage:
    """最小 ``Storage`` 替身（仅实现 ``get``）。"""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def get(self, key: str) -> bytes:
        """按对象键返回字节内容（缺失 → ``KeyError``）。"""
        return self._objects[key]


def _router() -> ModelRouter:
    """构造 stub Model Router（维度 ``_EMBED_DIMENSION``）。"""
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider(dimension=_EMBED_DIMENSION))
    return ModelRouter(registry)


def _seed(session_factory: object) -> tuple[KnowledgeBase, Document]:
    """植入一个 KB（``fixed/800/100``；stub 维度 8）+ 一个 ``PENDING`` 文档。"""
    kb = SqlKnowledgeBaseRepository(session_factory).add(  # type: ignore[arg-type]
        KnowledgeBase(
            tenant_id="t1",
            name="kb-index",
            created_by="u1",
            status="ACTIVE",
            embedding_model={
                "provider": "stub",
                "model": "stub-embed",
                "dimensions": _EMBED_DIMENSION,
            },
            chunk_config={"strategy": "fixed", "size": 800, "overlap": 100},
        )
    )
    document = SqlDocumentRepository(session_factory).add(  # type: ignore[arg-type]
        Document(
            knowledge_base_id=kb.id,
            title="doc.txt",
            source_type="file",
            storage_key=_SOURCE_KEY,
            mime="text/plain",
            status="PENDING",
        )
    )
    return kb, document


def _storage() -> _FakeStorage:
    """构造含 golden 原文的替身存储。"""
    return _FakeStorage({_SOURCE_KEY: _SOURCE_BYTES})


# -- 状态机闭环 ---------------------------------------------------------------


def test_index_task_runs_to_ready(session_factory) -> None:
    """``PENDING → … → READY``；SQLite（``vector_search=False``）跳过嵌入。"""
    _kb, document = _seed(session_factory)
    task = build_knowledge_index_task(
        session_factory=session_factory, storage=_storage(), vector_search=False
    )
    assert isinstance(task, KnowledgeIndexTask)
    assert task.run(document.id) == "READY"

    reloaded = SqlDocumentRepository(session_factory).get(document.id)
    assert reloaded is not None and reloaded.status == "READY"
    chunks = SqlDocumentChunkRepository(session_factory).list_by_document(document.id)
    assert len(chunks) >= 2
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.embedding_id is None for chunk in chunks)
    assert SqlEmbeddingRepository(session_factory).list() == []


def test_index_task_idempotent_when_ready(session_factory) -> None:
    """已 ``READY`` 的文档直接返回（幂等，不重复分块）。"""
    _kb, document = _seed(session_factory)
    task = build_knowledge_index_task(
        session_factory=session_factory, storage=_storage(), vector_search=False
    )
    assert task.run(document.id) == "READY"
    first = SqlDocumentChunkRepository(session_factory).list_by_document(document.id)
    assert task.run(document.id) == "READY"
    second = SqlDocumentChunkRepository(session_factory).list_by_document(document.id)
    assert len(first) == len(second)


# -- 失败 + 重试 + 断点续跑 ---------------------------------------------------


def test_index_task_failure_marks_failed(session_factory) -> None:
    """原文不可得 → ``DomainError`` + ``document.status=FAILED`` + ``error`` 落库。"""
    _kb, document = _seed(session_factory)
    task = build_knowledge_index_task(
        session_factory=session_factory, storage=None, vector_search=False
    )
    with pytest.raises(DomainError) as exc:
        task.run(document.id)
    assert exc.value.data.get("reason") == "document_source_unavailable"

    reloaded = SqlDocumentRepository(session_factory).get(document.id)
    assert reloaded is not None
    assert reloaded.status == "FAILED"
    assert reloaded.error


def test_index_task_retry_resumes_and_skips_done_chunks(session_factory) -> None:
    """``FAILED → PARSING`` 重入：已完成 ``(document_id, ordinal)`` 跳过，无重复。"""
    _kb, document = _seed(session_factory)
    chunk_repository = SqlDocumentChunkRepository(session_factory)
    # 预插 ordinal 0（模拟上一轮已完成的块）。
    chunk_repository.add(
        DocumentChunk(id="pre-0", document_id=document.id, ordinal=0, content="pre-existing")
    )

    failing = build_knowledge_index_task(
        session_factory=session_factory, storage=None, vector_search=False
    )
    with pytest.raises(DomainError):
        failing.run(document.id)
    assert SqlDocumentRepository(session_factory).get(document.id).status == "FAILED"

    ok = build_knowledge_index_task(
        session_factory=session_factory, storage=_storage(), vector_search=False
    )
    assert ok.run(document.id) == "READY"

    chunks = chunk_repository.list_by_document(document.id)
    ordinals = [chunk.ordinal for chunk in chunks]
    assert ordinals == list(range(len(ordinals))), ordinals
    assert len(ordinals) == len(set(ordinals)), "断点续跑出现重复 ordinal"
    assert chunks[0].id == "pre-0", "既有分块被覆盖 / 重插"


# -- 嵌入路 -------------------------------------------------------------------


def test_index_task_embeds_when_vector_search(session_factory) -> None:
    """``vector_search=True`` → 落 ``embedding`` + 回填 ``document_chunk.embedding_id``。"""
    _kb, document = _seed(session_factory)
    task = build_knowledge_index_task(
        session_factory=session_factory,
        storage=_storage(),
        model_router=_router(),
        vector_search=True,
        embedding_dimensions=_EMBED_DIMENSION,
    )
    assert task.run(document.id) == "READY"

    chunks = SqlDocumentChunkRepository(session_factory).list_by_document(document.id)
    embeddings = SqlEmbeddingRepository(session_factory).list()
    assert len(embeddings) == len(chunks)
    assert all(chunk.embedding_id for chunk in chunks)
    assert all(len(embedding.vector) == _EMBED_DIMENSION for embedding in embeddings)


# -- worker 处理器 ------------------------------------------------------------


def test_worker_handler_increments_attempt() -> None:
    """经 ``ctx.services["knowledge_index"]`` 调用；``payload.attempt`` 进入即 +1（B9）。"""
    from astra_worker import HandlerContext
    from astra_worker.tasks.knowledge_index import handle_knowledge_index

    captured: list[str] = []

    def _runner(document_id: str) -> str:
        captured.append(document_id)
        return "READY"

    message: dict[str, Any] = {"payload": {"document_id": "doc-1"}}
    ctx = HandlerContext(providers=None, services={"knowledge_index": _runner})

    first = handle_knowledge_index(message, ctx)
    assert first == {"document_id": "doc-1", "status": "READY", "attempt": 1}
    assert message["payload"]["attempt"] == 1

    second = handle_knowledge_index(message, ctx)
    assert second["attempt"] == 2
    assert message["payload"]["attempt"] == 2
    assert captured == ["doc-1", "doc-1"]


def test_worker_handler_requires_service() -> None:
    """未注入 ``knowledge_index`` → ``NotImplementedYetError``（**非静默**）。"""
    from astra_worker import HandlerContext
    from astra_worker.tasks.knowledge_index import handle_knowledge_index

    ctx = HandlerContext(providers=None, services={})
    with pytest.raises(NotImplementedYetError):
        handle_knowledge_index({"payload": {"document_id": "doc-1"}}, ctx)


def test_worker_handler_requires_document_id() -> None:
    """缺 ``document_id`` → ``DomainError(VALIDATION_ERROR)``。"""
    from astra_worker import HandlerContext
    from astra_worker.tasks.knowledge_index import handle_knowledge_index

    ctx = HandlerContext(providers=None, services={})
    with pytest.raises(DomainError) as exc:
        handle_knowledge_index({"payload": {}}, ctx)
    assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_worker_handler_registered() -> None:
    """处理器已登记于 ``HANDLERS["knowledge.index"]``（执行体 / 队列正交，R-23）。"""
    from astra_worker.tasks import HANDLERS
    from astra_worker.tasks.knowledge_index import handle_knowledge_index

    assert HANDLERS["knowledge.index"] is handle_knowledge_index
