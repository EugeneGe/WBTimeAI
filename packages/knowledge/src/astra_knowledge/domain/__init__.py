"""``astra_knowledge`` 领域子模块（实体 / 仓储接口；W5 / T2-27）。

本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from .entities import (
    DOCUMENT_SOURCE_TYPE_FILE,
    DOCUMENT_SOURCE_TYPE_TEXT,
    DOCUMENT_SOURCE_TYPE_URL,
    AgentKnowledge,
    Document,
    DocumentChunk,
    Embedding,
    KnowledgeBase,
)
from .repository import (
    AgentKnowledgeRepository,
    DocumentChunkRepository,
    DocumentRepository,
    EmbeddingRepository,
    KnowledgeBaseRepository,
)

__all__ = [
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
]
