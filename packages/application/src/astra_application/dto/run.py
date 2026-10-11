"""Run 相关 DTO（设计 §2.6 / §2.9；应用层，零框架依赖）。

- :class:`RunDTO`：一次执行（Run）视图；
- :class:`RunEventDTO`：生命周期事件（**纯值**，不引用 ``astra_event`` 类型，Q1 §1.5）；
- :class:`ToolCallDTO`：工具调用明细；
- :class:`MessageDTO`：会话消息。

🔴 约定（A27）：业务 DTO 顶层键**不得**同时使用 ``{code, message, data, request_id}``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from astra_domain import AgentEvent, AgentRun, Message, ToolCall

from .base import DTO

__all__ = ["RunDTO", "RunEventDTO", "ToolCallDTO", "MessageDTO"]


@dataclass
class RunDTO(DTO):
    """Agent Run DTO。"""

    id: str
    tenant_id: str | None
    agent_id: str
    agent_version_id: str
    conversation_id: str
    user_id: str | None = None
    task_id: str | None = None
    trigger: str = "user"
    run_mode: str = "INLINE"
    status: str = "PENDING"
    trace_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    success: bool | None = None
    error_type: str | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    cost: Decimal | None = None
    cost_status: str = "UNPRICED"
    error: str | None = None

    @classmethod
    def from_entity(cls, entity: AgentRun) -> RunDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            agent_id=entity.agent_id,
            agent_version_id=entity.agent_version_id,
            conversation_id=entity.conversation_id,
            user_id=entity.user_id,
            task_id=entity.task_id,
            trigger=entity.trigger,
            run_mode=entity.run_mode,
            status=entity.status,
            trace_id=entity.trace_id,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            duration_ms=entity.duration_ms,
            success=entity.success,
            error_type=entity.error_type,
            token_usage=dict(entity.token_usage or {}),
            cost=entity.cost,
            cost_status=entity.cost_status,
            error=entity.error,
        )


@dataclass
class RunEventDTO(DTO):
    """生命周期事件 DTO（**纯值**：``seq`` / ``type`` / ``payload`` / 骨架 / 时刻）。

    **不引用** ``astra_event`` 事件类——事件订阅落 API 层 ``astra_api/sse/``（Q1/Q2）。
    """

    seq: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: AgentEvent) -> RunEventDTO:
        """由领域事件实体构造 DTO。"""
        return cls(
            seq=entity.seq,
            type=entity.type,
            payload=dict(entity.payload or {}),
            trace_id=entity.trace_id,
            span_id=entity.span_id,
            created_at=entity.created_at,
        )


@dataclass
class ToolCallDTO(DTO):
    """工具调用明细 DTO。"""

    id: str
    run_id: str
    tool_name: str
    tool_type: str = "builtin"
    tool_id: str | None = None
    attempt: int = 1
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    status: str = "PENDING"
    duration_ms: int | None = None
    sandbox_session_id: str | None = None
    error: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: ToolCall) -> ToolCallDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            run_id=entity.run_id,
            tool_name=entity.tool_name,
            tool_type=entity.tool_type,
            tool_id=entity.tool_id,
            attempt=entity.attempt,
            input=dict(entity.input or {}),
            output=dict(entity.output) if entity.output is not None else None,
            status=entity.status,
            duration_ms=entity.duration_ms,
            sandbox_session_id=entity.sandbox_session_id,
            error=entity.error,
            created_at=entity.created_at,
        )


@dataclass
class MessageDTO(DTO):
    """会话消息 DTO。"""

    id: str
    conversation_id: str
    role: str
    content: str = ""
    run_id: str | None = None
    content_parts: list[Any] = field(default_factory=list)
    token_count: int | None = None
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: Message) -> MessageDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            conversation_id=entity.conversation_id,
            role=entity.role,
            content=entity.content,
            run_id=entity.run_id,
            content_parts=list(entity.content_parts or []),
            token_count=entity.token_count,
            created_at=entity.created_at,
        )
