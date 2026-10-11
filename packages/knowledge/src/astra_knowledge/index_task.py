"""``KnowledgeIndexTask``：文档索引任务闭环（W5 / T2-31；设计 §2.6 / §2.9）。

驱动 ``document`` 状态机（``PENDING → PARSING → CHUNKING → EMBEDDING → READY | FAILED``）：

1. **PARSING**：经注入的 :class:`~astra_storage.Storage` 读原文 →
   :class:`~astra_knowledge.parser.ParserRegistry` 解析（缺依赖 → ``DEPENDENCY_MISSING``）；
2. **CHUNKING**：:class:`~astra_knowledge.chunker.FixedChunker` 分块（参数取自
   ``kb.chunk_config``）；**断点续跑**：跳过已完成 ``(document_id, ordinal)``（B10）；
3. **EMBEDDING**（``capability.vector_search`` 为真）：``Embedder`` 算向量 →
   ``EmbeddingStore`` 四步写入；为假（SQLite）**跳过**嵌入；
4. **READY**：终态；失败 → ``FAILED`` + ``error`` 落库（重试由 ``TaskQueue`` 驱动，计数落
   ``task.payload["attempt"]``，B9）。

🔴 执行体 / 队列**正交**（R-23）：本类为**纯同步步骤函数**（无 API 依赖），由 Worker /
   ``InProcessBackgroundExecutor`` 调用（大文件解析**不阻塞 API**，I-P2-21）。
🔴 本模块**零 Web / ORM**（数据访问经注入的领域 Protocol）。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_storage import Storage

from .chunker import FixedChunker
from .domain import (
    Document,
    DocumentChunk,
    DocumentChunkRepository,
    DocumentRepository,
    EmbeddingRepository,
    KnowledgeBase,
    KnowledgeBaseRepository,
)
from .embedder import Embedder
from .embedding_store import EmbeddingStore
from .parser import ParsedDocument, ParserRegistry
from .status import (
    DOCUMENT_STATUS_CHUNKING,
    DOCUMENT_STATUS_EMBEDDING,
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_PARSING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_TERMINAL_STATUSES,
)

__all__ = ["KnowledgeIndexTask"]

#: 仅支持的分块策略（结构感知分块后置，``C2-24``）。
SUPPORTED_CHUNK_STRATEGY = "fixed"

#: 落库 ``error`` 的最大长度（防超长文本）。
_MAX_ERROR_LENGTH = 2000


class KnowledgeIndexTask:
    """文档索引任务（状态机 + 四步写入 + 断点续跑；``run(document_id) -> str``）。

    Args:
        knowledge_base_repository: KB 仓储（取 ``embedding_model`` / ``chunk_config``）。
        document_repository: 文档仓储（状态迁移落库）。
        chunk_repository: 分块仓储（断点续跑锚 + 反查缓存回填）。
        embedding_repository: 向量仓储（经 :class:`EmbeddingStore` 使用）。
        storage: 原文读取来源（``source_type`` 为 ``file`` / ``url`` 时必需）。
        embedder: 文本嵌入器（``vector_search=True`` 时必需）。
        vector_search: 是否启用嵌入（能力包汇入；SQLite 为假 → 跳过嵌入）。
        parser_registry: 解析器注册表（缺省 ＝ 内置注册表）。
        chunker: 分块器（缺省 ＝ ``FixedChunker(800, 100)``）。
    """

    def __init__(
        self,
        *,
        knowledge_base_repository: KnowledgeBaseRepository,
        document_repository: DocumentRepository,
        chunk_repository: DocumentChunkRepository,
        embedding_repository: EmbeddingRepository,
        storage: Storage | None = None,
        embedder: Embedder | None = None,
        vector_search: bool = False,
        parser_registry: ParserRegistry | None = None,
        chunker: FixedChunker | None = None,
    ) -> None:
        self._kb_repository = knowledge_base_repository
        self._document_repository = document_repository
        self._chunk_repository = chunk_repository
        self._embedding_repository = embedding_repository
        self._storage = storage
        self._embedder = embedder
        self._vector_search = bool(vector_search)
        self._parser_registry = parser_registry or ParserRegistry.default()
        self._chunker = chunker or FixedChunker()
        self._embedding_store = EmbeddingStore(
            embedding_repository=embedding_repository,
            chunk_repository=chunk_repository,
            vector_search=self._vector_search,
        )

    @property
    def vector_search(self) -> bool:
        """是否启用嵌入（capability）。"""
        return self._vector_search

    def run(self, document_id: str) -> str:
        """执行一次索引（返回终态 ``DocumentStatus`` 字面值）。

        Args:
            document_id: 文档标识。

        Returns:
            终态状态字面值（``READY``）。

        Raises:
            DomainError: 文档 / KB 不存在（``VALIDATION_ERROR``）、原文不可得、
                解析依赖缺失（``DEPENDENCY_MISSING``）、嵌入未配置（``CONFIGURATION_ERROR``）。
        """
        document = self._document_repository.get(document_id)
        if document is None:
            raise _error(
                f"文档不存在：{document_id}",
                reason="document_not_found",
                code=ErrorCode.VALIDATION_ERROR,
            )
        if document.status in DOCUMENT_TERMINAL_STATUSES:
            return document.status  # 幂等：已 READY
        kb = self._kb_repository.get(document.knowledge_base_id)
        if kb is None:
            raise _error(
                f"知识库不存在：{document.knowledge_base_id}",
                reason="knowledge_base_not_found",
                code=ErrorCode.VALIDATION_ERROR,
            )
        try:
            data = self._read_source(document)
            self._transition(document, DOCUMENT_STATUS_PARSING)
            parsed = self._parser_registry.parse(
                data, mime=document.mime, source_type=document.source_type
            )
            self._transition(document, DOCUMENT_STATUS_CHUNKING)
            new_chunks = self._chunk_document(document, kb, parsed)
            if self._vector_search:
                self._transition(document, DOCUMENT_STATUS_EMBEDDING)
                self._embed_document(new_chunks, kb)
            self._transition(document, DOCUMENT_STATUS_READY)
            return DOCUMENT_STATUS_READY
        except DomainError as exc:
            self._fail(document, str(exc))
            raise

    # -- 内部步骤 -----------------------------------------------------------

    def _read_source(self, document: Document) -> bytes:
        """读取文档原文（``source_type=file`` / ``url`` / ``text`` 均经 ``Storage``）。"""
        if document.storage_key and self._storage is not None:
            return self._storage.get(document.storage_key)
        raise _error(
            f"文档原文不可得：storage_key={document.storage_key!r}",
            reason="document_source_unavailable",
            code=ErrorCode.VALIDATION_ERROR,
        )

    def _chunk_document(
        self, document: Document, kb: KnowledgeBase, parsed: ParsedDocument
    ) -> list[DocumentChunk]:
        """分块（跳过已完成 ordinal；返回**本次新增**的分块）。"""
        config = dict(kb.chunk_config or {})
        strategy = str(config.get("strategy", SUPPORTED_CHUNK_STRATEGY))
        if strategy != SUPPORTED_CHUNK_STRATEGY:
            raise _error(
                f"暂不支持的分块策略：{strategy}",
                reason="unsupported_chunk_strategy",
                code=ErrorCode.VALIDATION_ERROR,
            )
        drafts = self._chunker.chunk(
            parsed,
            size=_opt_int(config.get("size")),
            overlap=_opt_int(config.get("overlap")),
        )
        done = self._chunk_repository.exists_ordinals(document.id)
        pending = [draft for draft in drafts if draft.ordinal not in done]
        if not pending:
            return []
        entities = [
            DocumentChunk(
                document_id=document.id,
                ordinal=draft.ordinal,
                content=draft.content,
                token_count=draft.token_count,
                meta=dict(draft.metadata),
                embedding_id=None,
            )
            for draft in pending
        ]
        return self._chunk_repository.add_many(entities)

    def _embed_document(self, chunks: list[DocumentChunk], kb: KnowledgeBase) -> None:
        """对**本次新增**分块算向量并四步写入（无新增则跳过）。"""
        if not chunks:
            return
        if self._embedder is None:
            raise _error(
                "vector_search=True 但未配置 Embedder",
                reason="embedder_not_configured",
                code=ErrorCode.CONFIGURATION_ERROR,
            )
        vectors = self._embedder.embed([chunk.content for chunk in chunks], kb=kb)
        self._embedding_store.write(chunks, vectors, kb=kb)

    def _transition(self, document: Document, target: str) -> None:
        """按状态机迁移并落库（非法迁移抛 ``DomainError(VALIDATION_ERROR)``）。"""
        document.transition_to(target)
        updated = self._document_repository.update_status(document.id, target)
        if updated is not None:
            document.status = updated.status

    def _fail(self, document: Document, message: str) -> None:
        """失败落库（``FAILED`` + ``error``；终态 / 已失败时跳过）。"""
        if (
            document.status in DOCUMENT_TERMINAL_STATUSES
            or document.status == DOCUMENT_STATUS_FAILED
        ):
            return
        self._document_repository.update_status(
            document.id, DOCUMENT_STATUS_FAILED, error=message[:_MAX_ERROR_LENGTH]
        )
        document.status = DOCUMENT_STATUS_FAILED
        document.error = message[:_MAX_ERROR_LENGTH]


def _opt_int(value: Any) -> int | None:  # noqa: ANN401 - kb.chunk_config 原始值
    """把配置值归一化为 ``int | None``（``None`` → 用分块器构造期默认）。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error(message: str, *, reason: str, code: ErrorCode) -> DomainError:
    """构造带 ``reason`` 的 :class:`~astra_core.DomainError`。"""
    return DomainError(message, code=code, data={"reason": reason})
