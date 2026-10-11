"""Memory fixture 语料包（W6 / T2-32）：假记忆 / 假 Run 消息构造器。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_memory import (
    MEMORY_KIND_LONG_TERM,
    SCOPE_TYPE_USER,
    VISIBILITY_PRIVATE,
    Memory,
    MemoryRelation,
)
from astra_model import ChatMessage

__all__ = ["make_memory", "make_relation", "make_chat_messages"]

#: 默认测试租户 / 用户（隔离断言基线）。
DEFAULT_TENANT = "tenant-test"
DEFAULT_USER = "user-test"


def make_memory(
    *,
    tenant_id: str = DEFAULT_TENANT,
    scope_type: str = SCOPE_TYPE_USER,
    scope_id: str = DEFAULT_USER,
    kind: str = MEMORY_KIND_LONG_TERM,
    visibility: str = VISIBILITY_PRIVATE,
    content: str = "记忆内容",
    memory_type: str = "fact",
    importance: float = 1.0,
    confidence: float = 1.0,
    source_run_id: str | None = None,
    vector: list[float] | None = None,
    expires_at: datetime | None = None,
    workspace_id: str | None = None,
    **overrides: Any,
) -> Memory:
    """构造一条测试记忆（缺省：本人可见的 ``LONG_TERM`` 事实）。"""
    return Memory(
        tenant_id=tenant_id,
        scope_type=scope_type,
        scope_id=scope_id,
        kind=kind,
        visibility=visibility,
        content=content,
        memory_type=memory_type,
        importance=importance,
        confidence=confidence,
        source_run_id=source_run_id,
        vector=vector,
        expires_at=expires_at,
        workspace_id=workspace_id,
        **overrides,
    )


def make_relation(
    *,
    from_memory_id: str,
    to_memory_id: str,
    relation: str = "related",
) -> MemoryRelation:
    """构造一条测试记忆关系。"""
    return MemoryRelation(
        from_memory_id=from_memory_id,
        to_memory_id=to_memory_id,
        relation=relation,
    )


def make_chat_messages(*pairs: tuple[str, str]) -> list[ChatMessage]:
    """由 ``(role, content)`` 对构造 ``ChatMessage`` 序列。"""
    return [ChatMessage(role=role, content=content) for role, content in pairs]
