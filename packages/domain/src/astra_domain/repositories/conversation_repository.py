"""Conversation 组仓储接口（**仅 Protocol**，零 ORM，C-03）。

对应 ORM 表：``conversation`` / ``message`` / ``agent_run`` / ``tool_call`` / ``agent_event``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from ..entities.conversation import (
    AgentEvent,
    AgentRun,
    Conversation,
    Message,
    ToolCall,
)
from .base import Repository

__all__ = [
    "ConversationRepository",
    "MessageRepository",
    "AgentRunRepository",
    "ToolCallRepository",
    "AgentEventRepository",
]


@runtime_checkable
class ConversationRepository(Repository[Conversation], Protocol):
    """会话仓储接口。"""

    def list_by_tenant(self, tenant_id: str) -> list[Conversation]:
        """列出某租户下的全部会话。"""
        ...


@runtime_checkable
class MessageRepository(Repository[Message], Protocol):
    """消息仓储接口。"""

    def list_by_conversation(self, conversation_id: str) -> list[Message]:
        """按创建顺序列出某会话的全部消息。"""
        ...


@runtime_checkable
class AgentRunRepository(Repository[AgentRun], Protocol):
    """Run 仓储接口。"""

    def list_by_conversation(self, conversation_id: str) -> list[AgentRun]:
        """列出某会话下的全部 Run。"""
        ...

    def list_active_by_conversation(self, conversation_id: str) -> list[AgentRun]:
        """列出某会话下的**活跃**（非终态）Run（供并发约束检查）。"""
        ...

    def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> AgentRun | None:
        """按 ``(tenant_id, idempotency_key)`` 唯一键获取 Run（幂等去重）。"""
        ...

    def add_guarded(self, entity: AgentRun, *, max_active: int) -> AgentRun | None:
        """**原子**地「检查活跃 Run 数 + 建 Run」（并发约束，设计 §2.7.2）。

        实现方须保证原子性：PostgreSQL 用 ``SELECT ... FOR UPDATE``（或在
        ``conversation`` 行上加锁）；SQLite 用等价的串行化事务。

        Args:
            entity: 待创建的 Run。
            max_active: 该会话允许的最大活跃 Run 数（含本次）。

        Returns:
            创建成功返回落库后的 Run；若创建后会超出 ``max_active`` 则返回 ``None``
            （**不**静默排队，由调用方抛 ``DomainError(CONFLICT)`` → 409）。
        """
        ...

    def touch_heartbeat(self, run_id: str, *, at: datetime | None = None) -> None:
        """更新某 Run 的心跳时刻 ``agent_run.last_heartbeat_at``（W6 / T1-31）。

        Runtime **每轮迭代**调用（经 DI，**零 SQL**）；实现落能力包 ``repositories/``。

        Args:
            run_id: Run 标识。
            at: 心跳时刻（缺省取当前 UTC 时间）。
        """
        ...

    def list_stale_running(self, threshold: datetime) -> list[AgentRun]:
        """列出 ``status=RUNNING`` 且心跳超期（``last_heartbeat_at < threshold``）或
        ``last_heartbeat_at`` 为空且 ``started_at < threshold`` 的 Run（重启兜底扫描）。

        Args:
            threshold: 超期阈值时刻（``now - run_timeout_ms``）。

        Returns:
            超期的进行中 Run 列表。
        """
        ...


@runtime_checkable
class ToolCallRepository(Repository[ToolCall], Protocol):
    """ToolCall 仓储接口。"""

    def list_by_run(self, run_id: str) -> list[ToolCall]:
        """列出某 Run 下的全部工具调用。"""
        ...

    def next_attempt(self, run_id: str, tool_name: str) -> int:
        """返回某 Run 下某工具的**下一次**尝试序号（失败重试产生新行，R-09）。"""
        ...


@runtime_checkable
class AgentEventRepository(Repository[AgentEvent], Protocol):
    """AgentEvent 仓储接口。"""

    def list_by_run(self, run_id: str) -> list[AgentEvent]:
        """按 ``seq`` 升序列出某 Run 的全部事件（供回放）。"""
        ...

    def add_many(self, events: list[AgentEvent]) -> list[AgentEvent]:
        """**批量**写入事件（§5 #13：全量落库 + 批量写入，非逐条）。"""
        ...

    def list_after_seq(self, run_id: str, last_event_id: int | None = None) -> list[AgentEvent]:
        """按 ``seq`` 升序列出 ``seq > last_event_id`` 的事件（``Last-Event-ID`` 续传）。"""
        ...
