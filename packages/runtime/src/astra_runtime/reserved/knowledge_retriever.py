"""RP-02 · ``KnowledgeRetriever``（知识检索预留位；总纲 §12.2）。

Phase 1 仅提供**完整 Protocol 签名 + 可装配空实现**；Phase 2 填充实现时**不得改签名**。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import KnowledgeChunk, KnowledgeQuery

__all__ = ["KnowledgeRetriever", "NullKnowledgeRetriever"]


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """知识检索器（RP-02）。"""

    def retrieve(self, query: KnowledgeQuery) -> list[KnowledgeChunk]:
        """按查询召回知识片段（无匹配返回空列表）。

        Raises:
            DomainError: 检索失败（``INTERNAL_ERROR``）。
        """
        ...


class NullKnowledgeRetriever:
    """空实现（Phase 1）：恒返回空列表。"""

    def retrieve(self, query: KnowledgeQuery) -> list[KnowledgeChunk]:
        """恒返回空列表。"""
        return []
