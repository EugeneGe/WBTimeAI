"""Astra AI Knowledge 能力包（``astra_knowledge``；设计 §2.6 / W5 裁定 R1）。

- 领域实体 / 仓储接口：``astra_knowledge.domain``（``KnowledgeBase`` / ``Document`` /
  ``DocumentChunk`` / ``Embedding`` / ``AgentKnowledge``）；
- 状态机：``astra_knowledge.status``（``DocumentStatus`` 等）；
- SQL 仓储：``astra_knowledge.repositories``（能力包 ORM 落点）；
- ``Parser`` / ``Chunker`` / ``Embedder`` / ``Retriever`` / 索引任务归 T2-28 ~ T2-31。

包性质：能力包（仅禁 Web；SQL 仓储留本包 ``repositories/``）——W5 裁定 §3。
"""

from __future__ import annotations

from .chunker import ChunkDraft, FixedChunker
from .domain import (
    DOCUMENT_SOURCE_TYPE_FILE,
    DOCUMENT_SOURCE_TYPE_TEXT,
    DOCUMENT_SOURCE_TYPE_URL,
    AgentKnowledge,
    AgentKnowledgeRepository,
    Document,
    DocumentChunk,
    DocumentChunkRepository,
    DocumentRepository,
    Embedding,
    EmbeddingRepository,
    KnowledgeBase,
    KnowledgeBaseRepository,
)
from .embedder import DEFAULT_EMBEDDING_DIMENSIONS, Embedder
from .embedding_store import EmbeddingStore
from .factory import (
    KnowledgeRepositories,
    build_knowledge_index_task,
    build_knowledge_repositories,
    build_knowledge_retriever,
    resolve_vector_search_capability,
)
from .index_task import KnowledgeIndexTask
from .parser import (
    PARSER_EXTRA_NAME,
    DocxParser,
    HtmlParser,
    MarkdownParser,
    ParsedDocument,
    Parser,
    ParserRegistry,
    PdfParser,
    TextParser,
    missing_dependency_error,
)
from .repositories import (
    SqlAgentKnowledgeRepository,
    SqlDocumentChunkRepository,
    SqlDocumentRepository,
    SqlEmbeddingRepository,
    SqlKnowledgeBaseRepository,
)
from .retriever import (
    DEFAULT_KNOWLEDGE_TOP_K,
    KnowledgeRetriever,
    RetrievedChunk,
)
from .retriever_fts import FtsRetriever
from .retriever_semantic import SemanticRetriever
from .status import (
    DOCUMENT_STATUS_CHUNKING,
    DOCUMENT_STATUS_EMBEDDING,
    DOCUMENT_STATUS_FAILED,
    DOCUMENT_STATUS_PARSING,
    DOCUMENT_STATUS_PENDING,
    DOCUMENT_STATUS_READY,
    DOCUMENT_TERMINAL_STATUSES,
    DOCUMENT_TRANSITIONS,
    KNOWLEDGE_BASE_STATUS_ACTIVE,
    KNOWLEDGE_BASE_STATUS_DISABLED,
    KNOWLEDGE_BASE_STATUS_INDEXING,
    DocumentStatus,
    KnowledgeBaseStatus,
    assert_document_transition,
    can_transition_document,
)

__all__ = [
    # 状态常量
    "KNOWLEDGE_BASE_STATUS_ACTIVE",
    "KNOWLEDGE_BASE_STATUS_INDEXING",
    "KNOWLEDGE_BASE_STATUS_DISABLED",
    "DOCUMENT_STATUS_PENDING",
    "DOCUMENT_STATUS_PARSING",
    "DOCUMENT_STATUS_CHUNKING",
    "DOCUMENT_STATUS_EMBEDDING",
    "DOCUMENT_STATUS_READY",
    "DOCUMENT_STATUS_FAILED",
    # 枚举
    "KnowledgeBaseStatus",
    "DocumentStatus",
    # 状态迁移 / 判定
    "DOCUMENT_TRANSITIONS",
    "DOCUMENT_TERMINAL_STATUSES",
    "can_transition_document",
    "assert_document_transition",
    # 实体
    "KnowledgeBase",
    "Document",
    "DocumentChunk",
    "Embedding",
    "AgentKnowledge",
    # 源类型常量
    "DOCUMENT_SOURCE_TYPE_FILE",
    "DOCUMENT_SOURCE_TYPE_URL",
    "DOCUMENT_SOURCE_TYPE_TEXT",
    # 仓储接口
    "KnowledgeBaseRepository",
    "DocumentRepository",
    "DocumentChunkRepository",
    "EmbeddingRepository",
    "AgentKnowledgeRepository",
    # SQL 仓储
    "SqlKnowledgeBaseRepository",
    "SqlDocumentRepository",
    "SqlDocumentChunkRepository",
    "SqlEmbeddingRepository",
    "SqlAgentKnowledgeRepository",
    # Parser / Chunker（W5 / T2-28）
    "ParsedDocument",
    "Parser",
    "ParserRegistry",
    "PARSER_EXTRA_NAME",
    "missing_dependency_error",
    "TextParser",
    "MarkdownParser",
    "HtmlParser",
    "PdfParser",
    "DocxParser",
    "ChunkDraft",
    "FixedChunker",
    # Embedder / EmbeddingStore（W5 / T2-29）
    "Embedder",
    "EmbeddingStore",
    "DEFAULT_EMBEDDING_DIMENSIONS",
    # Retriever（W5 / T2-30）
    "RetrievedChunk",
    "KnowledgeRetriever",
    "SemanticRetriever",
    "FtsRetriever",
    "DEFAULT_KNOWLEDGE_TOP_K",
    # 组合工厂（W5 / T2-30）
    "KnowledgeRepositories",
    "build_knowledge_repositories",
    "build_knowledge_retriever",
    "resolve_vector_search_capability",
    # 索引任务（W5 / T2-31）
    "KnowledgeIndexTask",
    "build_knowledge_index_task",
]
