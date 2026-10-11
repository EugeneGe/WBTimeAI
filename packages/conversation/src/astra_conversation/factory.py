"""Conversation 组组合工厂（能力包）——``build_conversation_services(session_factory)``。

装配 Conversation 组的 SQL 仓储（实现 ``astra_domain`` 领域 Protocol）与领域服务。
可选注入 ``task_repository``（``astra_database.repositories.SqlTaskRepository``）以启用
:class:`~astra_conversation.services.run_service.RunService`（T1-26）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astra_domain import SandboxSessionRepository, TaskRepository
from sqlalchemy.orm import Session, sessionmaker

from .repositories import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlConversationRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from .services import ConversationService, RunService

__all__ = ["ConversationServices", "build_conversation_services"]


@dataclass
class ConversationServices:
    """Conversation 组装配结果（仓储 + 服务）。"""

    conversations: SqlConversationRepository
    runs: SqlAgentRunRepository
    messages: SqlMessageRepository
    tool_calls: SqlToolCallRepository
    events: SqlAgentEventRepository
    conversation_service: ConversationService
    run_service: RunService | None


def build_conversation_services(
    session_factory: sessionmaker[Session],
    *,
    task_repository: TaskRepository | None = None,
    sandbox_repository: SandboxSessionRepository | None = None,
    sandbox_provider: Any = None,
) -> ConversationServices:
    """构造 Conversation 组仓储与服务。

    Args:
        session_factory: SQLAlchemy 会话工厂。
        task_repository: 可选的 ``TaskRepository``（提供后启用 ``RunService``）。
        sandbox_repository: 可选的 ``SandboxSessionRepository``（供兜底扫描回收沙箱）。
        sandbox_provider: 可选的 ``SandboxProvider``（回收时 ``destroy``）。
    """
    conversations = SqlConversationRepository(session_factory)
    runs = SqlAgentRunRepository(session_factory)
    messages = SqlMessageRepository(session_factory)
    tool_calls = SqlToolCallRepository(session_factory)
    events = SqlAgentEventRepository(session_factory)
    conversation_service = ConversationService(
        conversation_repository=conversations,
        message_repository=messages,
        event_repository=events,
    )
    run_service = (
        RunService(
            run_repository=runs,
            task_repository=task_repository,
            sandbox_repository=sandbox_repository,
            sandbox_provider=sandbox_provider,
        )
        if task_repository is not None
        else None
    )
    return ConversationServices(
        conversations=conversations,
        runs=runs,
        messages=messages,
        tool_calls=tool_calls,
        events=events,
        conversation_service=conversation_service,
        run_service=run_service,
    )
