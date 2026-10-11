"""Knowledge 索引事件（Phase 2 · W3 / T2-16；设计 §2.11；裁定 §6.1）。

1 类事件，**继承** :class:`astra_core.events.DomainEvent`（事件基类唯一，C-02）：

- ``KnowledgeIndexed``：``knowledge.indexed`` —— 文档索引完成。

🔴 2a **先定义类型**，2c 消费触发；本模块**只定义事件类型**，``EventBus`` Protocol 不变（C-02）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = ["KnowledgeIndexed"]


@dataclass
class KnowledgeIndexed(DomainEvent):
    """知识库文档索引事件（``knowledge.indexed``）。"""

    type: ClassVar[str] = "knowledge.indexed"

    @classmethod
    def create(
        cls,
        *,
        kb_id: str,
        document_id: str,
        chunk_count: int | None = None,
        status: str | None = None,
    ) -> KnowledgeIndexed:
        """便捷构造。"""
        payload: dict[str, Any] = {"kb_id": kb_id, "document_id": document_id}
        if chunk_count is not None:
            payload["chunk_count"] = chunk_count
        if status is not None:
            payload["status"] = status
        return cls(payload=payload)
