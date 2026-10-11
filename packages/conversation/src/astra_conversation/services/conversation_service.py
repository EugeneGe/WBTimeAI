"""``ConversationService``（会话 CRUD / 消息追加 / 事件追加；设计 §2.6）。

纯服务层（经 DI 注入领域 Protocol 仓储）——**零 ORM 直接依赖**（ORM 仅在 ``repositories/``）。
"""

from __future__ import annotations

from astra_domain import AgentEvent, Conversation, Message

from ..repositories import (
    SqlAgentEventRepository,
    SqlConversationRepository,
    SqlMessageRepository,
)

__all__ = ["ConversationService"]


class ConversationService:
    """会话 / 消息 / 事件的应用服务（薄封装多个仓储）。"""

    def __init__(
        self,
        *,
        conversation_repository: SqlConversationRepository,
        message_repository: SqlMessageRepository,
        event_repository: SqlAgentEventRepository,
    ) -> None:
        self._conversations = conversation_repository
        self._messages = message_repository
        self._events = event_repository

    # -- Conversation -------------------------------------------------------

    def create_conversation(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        title: str,
        status: str = "ACTIVE",
    ) -> Conversation:
        """创建会话。"""
        return self._conversations.add(
            Conversation(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                title=title,
                status=status,
            )
        )

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        """按主键获取会话。"""
        return self._conversations.get(conversation_id)

    def list_conversations(self, tenant_id: str) -> list[Conversation]:
        """列出某租户的全部会话。"""
        return self._conversations.list_by_tenant(tenant_id)

    # -- Message ------------------------------------------------------------

    def append_message(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        content_parts: list[object] | None = None,
        token_count: int | None = None,
    ) -> Message:
        """追加一条消息。"""
        return self._messages.add(
            Message(
                conversation_id=conversation_id,
                run_id=run_id,
                role=role,
                content=content,
                content_parts=list(content_parts or []),
                token_count=token_count,
            )
        )

    def list_messages(self, conversation_id: str) -> list[Message]:
        """按创建顺序列出某会话的全部消息。"""
        return self._messages.list_by_conversation(conversation_id)

    # -- Event --------------------------------------------------------------

    def append_event(
        self,
        *,
        run_id: str,
        type: str,
        payload: dict[str, object] | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> AgentEvent:
        """追加一条事件（``seq`` 由仓储自增）。"""
        return self._events.add(
            AgentEvent(
                run_id=run_id,
                type=type,
                payload=dict(payload or {}),
                trace_id=trace_id,
                span_id=span_id,
            )
        )

    def list_events(self, run_id: str) -> list[AgentEvent]:
        """按 ``seq`` 升序列出某 Run 的全部事件（供回放）。"""
        return self._events.list_by_run(run_id)
