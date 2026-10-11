"""``astra_knowledge`` 状态机（设计 §2.6；W5 裁定 §4.2 / T2-27 + T2-31）。

- :class:`KnowledgeBaseStatus`：知识库生命周期
  ``ACTIVE|INDEXING|DISABLED``；
- :class:`DocumentStatus`：文档索引状态机
  ``PENDING → PARSING → CHUNKING → EMBEDDING → READY``，任意阶段失败 → ``FAILED``；
  ``FAILED → PARSING``（重试）；
- :func:`can_transition_document` / :func:`assert_document_transition`：非法迁移抛
  ``DomainError(VALIDATION_ERROR)``（仿 ``astra_task.states`` / ``astra_workflow``）。

```
PENDING ─▶ PARSING ─▶ CHUNKING ─▶ EMBEDDING ─▶ READY
   │           │           │            │
   └───────────┴───────────┴────────────┴──────▶ FAILED ──(retry)──▶ PARSING
```

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_core``）。
"""

from __future__ import annotations

from enum import StrEnum

from astra_core import DomainError, ErrorCode

__all__ = [
    # 常量
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
    # 迁移表 / 判定
    "DOCUMENT_TRANSITIONS",
    "DOCUMENT_TERMINAL_STATUSES",
    "can_transition_document",
    "assert_document_transition",
]


# -- KnowledgeBase -----------------------------------------------------------

#: KnowledgeBase 生命周期状态。
KNOWLEDGE_BASE_STATUS_ACTIVE = "ACTIVE"
KNOWLEDGE_BASE_STATUS_INDEXING = "INDEXING"
KNOWLEDGE_BASE_STATUS_DISABLED = "DISABLED"

#: Document 索引状态。
DOCUMENT_STATUS_PENDING = "PENDING"
DOCUMENT_STATUS_PARSING = "PARSING"
DOCUMENT_STATUS_CHUNKING = "CHUNKING"
DOCUMENT_STATUS_EMBEDDING = "EMBEDDING"
DOCUMENT_STATUS_READY = "READY"
DOCUMENT_STATUS_FAILED = "FAILED"


class KnowledgeBaseStatus(StrEnum):
    """KnowledgeBase 生命周期状态（设计 §2.6）。"""

    ACTIVE = KNOWLEDGE_BASE_STATUS_ACTIVE
    INDEXING = KNOWLEDGE_BASE_STATUS_INDEXING
    DISABLED = KNOWLEDGE_BASE_STATUS_DISABLED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class DocumentStatus(StrEnum):
    """Document 索引状态机（设计 §2.6，**冻结**）。"""

    PENDING = DOCUMENT_STATUS_PENDING
    PARSING = DOCUMENT_STATUS_PARSING
    CHUNKING = DOCUMENT_STATUS_CHUNKING
    EMBEDDING = DOCUMENT_STATUS_EMBEDDING
    READY = DOCUMENT_STATUS_READY
    FAILED = DOCUMENT_STATUS_FAILED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


#: Document 合法状态迁移表（当前 → 允许的下一状态集合）。
DOCUMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    DOCUMENT_STATUS_PENDING: frozenset({DOCUMENT_STATUS_PARSING, DOCUMENT_STATUS_FAILED}),
    DOCUMENT_STATUS_PARSING: frozenset({DOCUMENT_STATUS_CHUNKING, DOCUMENT_STATUS_FAILED}),
    DOCUMENT_STATUS_CHUNKING: frozenset(
        {DOCUMENT_STATUS_EMBEDDING, DOCUMENT_STATUS_READY, DOCUMENT_STATUS_FAILED}
    ),
    DOCUMENT_STATUS_EMBEDDING: frozenset({DOCUMENT_STATUS_READY, DOCUMENT_STATUS_FAILED}),
    # 重试：FAILED → PARSING（重入仅处理剩余 chunk）。
    DOCUMENT_STATUS_FAILED: frozenset({DOCUMENT_STATUS_PARSING}),
    DOCUMENT_STATUS_READY: frozenset(),
}

#: Document 终态集合（不可再转移；``FAILED`` 可因重试重入，不列终态）。
DOCUMENT_TERMINAL_STATUSES: frozenset[str] = frozenset({DOCUMENT_STATUS_READY})


def _normalize(status: str | StrEnum) -> str:
    """将枚举 / 字符串统一为字面值。"""
    return status.value if isinstance(status, StrEnum) else str(status)


def can_transition_document(current: str | DocumentStatus, target: str | DocumentStatus) -> bool:
    """判断 Document 的 ``current → target`` 是否合法。"""
    return _normalize(target) in DOCUMENT_TRANSITIONS.get(_normalize(current), frozenset())


def assert_document_transition(current: str | DocumentStatus, target: str | DocumentStatus) -> None:
    """断言 Document 状态迁移合法，否则抛 :class:`DomainError`。

    Raises:
        DomainError: 非法迁移（``VALIDATION_ERROR``）。
    """
    if not can_transition_document(current, target):
        raise DomainError(
            f"非法 Document 状态迁移：{_normalize(current)} → {_normalize(target)}",
            code=ErrorCode.VALIDATION_ERROR,
            data={
                "reason": "invalid_status_transition",
                "from": _normalize(current),
                "to": _normalize(target),
            },
        )
