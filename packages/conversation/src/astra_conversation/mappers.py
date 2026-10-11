"""ORM 行 ↔ 领域实体映射（Conversation / Message / AgentRun / ToolCall / AgentEvent）。

将 ``astra_database.models.conversation`` 的 SQLAlchemy 行与 ``astra_domain`` 实体互转，
使 Conversation 组能力包在**服务 / 服务层**保持零 ORM 依赖（ORM 仅在本包 ``repositories/``
与 ``mappers``）。

⚠️ ORM 侧部分表未含 ``created_at`` / ``updated_at``（``agent_run`` 无时间戳列，
   ``message`` / ``tool_call`` / ``agent_event`` 仅有 ``created_at``），
   故 ``to_domain`` 缺失时间戳时以当前 UTC 回退。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_database.models.conversation import AgentEvent as OrmAgentEvent
from astra_database.models.conversation import AgentRun as OrmAgentRun
from astra_database.models.conversation import Conversation as OrmConversation
from astra_database.models.conversation import Message as OrmMessage
from astra_database.models.conversation import ToolCall as OrmToolCall
from astra_domain import AgentEvent, AgentRun, Conversation, Message, ToolCall

__all__ = [
    "conversation_to_domain",
    "conversation_to_orm",
    "run_to_domain",
    "run_to_orm",
    "message_to_domain",
    "message_to_orm",
    "tool_call_to_domain",
    "tool_call_to_orm",
    "event_to_domain",
    "event_to_orm",
]

_MESSAGE_COLS = (
    "id",
    "conversation_id",
    "run_id",
    "role",
    "content",
    "content_parts",
    "token_count",
)
_TOOL_CALL_COLS = (
    "id",
    "run_id",
    "tool_id",
    "tool_name",
    "tool_type",
    "tool_ref",
    "attempt",
    "trace_id",
    "span_id",
    "input",
    "output",
    "status",
    "duration_ms",
    "sandbox_session_id",
    "error",
    "created_at",
)
_EVENT_COLS = (
    "id",
    "run_id",
    "seq",
    "type",
    "payload",
    "trace_id",
    "span_id",
    "created_at",
)
_RUN_COLS = (
    "id",
    "tenant_id",
    "agent_id",
    "agent_version_id",
    "conversation_id",
    "user_id",
    "task_id",
    "trigger",
    "run_mode",
    "status",
    "trace_id",
    "span_id",
    "last_heartbeat_at",
    "idempotency_key",
    "started_at",
    "completed_at",
    "duration_ms",
    "token_usage",
    "success",
    "error_type",
    "tool_error_count",
    "cost",
    "cost_currency",
    "cost_price_version",
    "cost_estimated",
    "cost_breakdown",
    "cost_status",
    "error",
)


def _dt(value: datetime | None) -> datetime:
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


def _from_orm(row: Any, cols: tuple[str, ...]) -> dict[str, Any]:
    """从 ORM 行按列名抽取字典（跨 SQLAlchemy 版本稳健）。"""
    return {col: getattr(row, col, None) for col in cols}


# -- Conversation -----------------------------------------------------------


def conversation_to_domain(row: OrmConversation) -> Conversation:
    """ORM 会话行 → 领域 ``Conversation``。"""
    return Conversation(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        workspace_id=row.workspace_id,
        agent_id=row.agent_id,
        user_id=row.user_id,
        title=row.title,
        status=row.status,
    )


def conversation_to_orm(entity: Conversation) -> OrmConversation:
    """领域 ``Conversation`` → ORM 行。"""
    return OrmConversation(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        agent_id=entity.agent_id,
        user_id=entity.user_id,
        title=entity.title,
        status=entity.status,
    )


# -- AgentRun ---------------------------------------------------------------


def run_to_domain(row: OrmAgentRun) -> AgentRun:
    """ORM Run 行 → 领域 ``AgentRun``。"""
    return AgentRun(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        task_id=row.task_id,
        trigger=row.trigger,
        run_mode=row.run_mode,
        status=row.status,
        trace_id=row.trace_id,
        span_id=row.span_id,
        last_heartbeat_at=row.last_heartbeat_at,
        idempotency_key=row.idempotency_key,
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_ms=row.duration_ms,
        token_usage=dict(row.token_usage or {}),
        success=row.success,
        error_type=row.error_type,
        tool_error_count=row.tool_error_count or 0,
        cost=row.cost,
        cost_currency=row.cost_currency,
        cost_price_version=row.cost_price_version,
        cost_estimated=bool(row.cost_estimated),
        cost_breakdown=dict(row.cost_breakdown or {}),
        cost_status=row.cost_status,
        error=row.error,
    )


def run_to_orm(entity: AgentRun) -> OrmAgentRun:
    """领域 ``AgentRun`` → ORM 行。"""
    return OrmAgentRun(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        agent_id=entity.agent_id,
        agent_version_id=entity.agent_version_id,
        conversation_id=entity.conversation_id,
        user_id=entity.user_id,
        task_id=entity.task_id,
        trigger=entity.trigger,
        run_mode=entity.run_mode,
        status=entity.status,
        trace_id=entity.trace_id,
        span_id=entity.span_id,
        last_heartbeat_at=entity.last_heartbeat_at,
        idempotency_key=entity.idempotency_key,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        duration_ms=entity.duration_ms,
        token_usage=dict(entity.token_usage or {}) or None,
        success=entity.success,
        error_type=entity.error_type,
        tool_error_count=entity.tool_error_count,
        cost=entity.cost,
        cost_currency=entity.cost_currency,
        cost_price_version=entity.cost_price_version,
        cost_estimated=entity.cost_estimated,
        cost_breakdown=dict(entity.cost_breakdown or {}) or None,
        cost_status=entity.cost_status,
        error=entity.error,
    )


# -- Message ----------------------------------------------------------------


def message_to_domain(row: OrmMessage) -> Message:
    """ORM 消息行 → 领域 ``Message``。"""
    return Message(
        id=row.id,
        tenant_id=None,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "created_at", None)),
        conversation_id=row.conversation_id,
        run_id=row.run_id,
        role=row.role,
        content=row.content,
        content_parts=list(row.content_parts or []),
        token_count=row.token_count,
    )


def message_to_orm(entity: Message) -> OrmMessage:
    """领域 ``Message`` → ORM 行。"""
    return OrmMessage(
        id=entity.id,
        conversation_id=entity.conversation_id,
        run_id=entity.run_id,
        role=entity.role,
        content=entity.content,
        content_parts=list(entity.content_parts or []) or None,
        token_count=entity.token_count,
        created_at=_dt(entity.created_at),
    )


# -- ToolCall ---------------------------------------------------------------


def tool_call_to_domain(row: OrmToolCall) -> ToolCall:
    """ORM 工具调用行 → 领域 ``ToolCall``。"""
    return ToolCall(
        id=row.id,
        tenant_id=None,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "created_at", None)),
        run_id=row.run_id,
        tool_id=row.tool_id,
        tool_name=row.tool_name,
        tool_type=row.tool_type,
        tool_ref=dict(row.tool_ref or {}),
        attempt=row.attempt or 1,
        trace_id=row.trace_id,
        span_id=row.span_id,
        input=dict(row.input or {}),
        output=dict(row.output) if row.output is not None else None,
        status=row.status,
        duration_ms=row.duration_ms,
        sandbox_session_id=row.sandbox_session_id,
        error=row.error,
    )


def tool_call_to_orm(entity: ToolCall) -> OrmToolCall:
    """领域 ``ToolCall`` → ORM 行。"""
    return OrmToolCall(
        id=entity.id,
        run_id=entity.run_id,
        tool_id=entity.tool_id,
        tool_name=entity.tool_name,
        tool_type=entity.tool_type,
        tool_ref=dict(entity.tool_ref or {}) or None,
        attempt=entity.attempt,
        trace_id=entity.trace_id,
        span_id=entity.span_id,
        input=dict(entity.input or {}) or None,
        output=dict(entity.output) if entity.output is not None else None,
        status=entity.status,
        duration_ms=entity.duration_ms,
        sandbox_session_id=entity.sandbox_session_id,
        error=entity.error,
        created_at=_dt(entity.created_at),
    )


# -- AgentEvent -------------------------------------------------------------


def event_to_domain(row: OrmAgentEvent) -> AgentEvent:
    """ORM 事件行 → 领域 ``AgentEvent``。"""
    return AgentEvent(
        id=row.id,
        tenant_id=None,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "created_at", None)),
        run_id=row.run_id,
        seq=row.seq,
        type=row.type,
        payload=dict(row.payload or {}),
        trace_id=row.trace_id,
        span_id=row.span_id,
    )


def event_to_orm(entity: AgentEvent, *, seq: int | None = None) -> OrmAgentEvent:
    """领域 ``AgentEvent`` → ORM 行（``seq`` 可覆写）。"""
    return OrmAgentEvent(
        id=entity.id,
        run_id=entity.run_id,
        seq=seq if seq is not None else entity.seq,
        type=entity.type,
        payload=dict(entity.payload or {}) or None,
        trace_id=entity.trace_id,
        span_id=entity.span_id,
        created_at=_dt(entity.created_at),
    )
