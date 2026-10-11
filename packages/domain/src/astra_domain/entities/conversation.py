"""Conversation 组领域实体（设计 §2.15.1 Conversation 组 / §2.6）。

纯 dataclass，零框架依赖（C-03）。

- :class:`Conversation` / :class:`Message` / :class:`AgentRun` / :class:`ToolCall` /
  :class:`AgentEvent`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..constants import (
    COST_STATUS_UNPRICED,
    MESSAGE_ROLE_USER,
    RUN_MODE_INLINE,
    RUN_STATUS_PENDING,
    RUN_TRIGGER_USER,
    TOOL_CALL_STATUS_PENDING,
    TOOL_TYPE_BUILTIN,
)
from .base import AggregateRoot

__all__ = ["Conversation", "Message", "AgentRun", "ToolCall", "AgentEvent"]


@dataclass
class Conversation(AggregateRoot):
    """会话容器.

    Attributes:
        workspace_id: 归属工作区标识。
        agent_id: 关联 Agent 标识。
        user_id: 关联用户标识。
        title: 标题。
        status: 状态（``ACTIVE`` / ``ARCHIVED``）。
    """

    workspace_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    title: str = ""
    status: str = "ACTIVE"


@dataclass
class Message(AggregateRoot):
    """对话消息.

    Attributes:
        conversation_id: 所属会话标识。
        run_id: 关联 Run 标识（可空）。
        role: 角色（``MessageRole`` 字面值）。
        content: 文本内容。
        content_parts: 结构化内容（多模态 / 工具调用，JSON 结构）。
        token_count: token 数（可空）。
    """

    conversation_id: str = ""
    run_id: str | None = None
    role: str = MESSAGE_ROLE_USER
    content: str = ""
    content_parts: list[Any] = field(default_factory=list)
    token_count: int | None = None


@dataclass
class AgentRun(AggregateRoot):
    """一次执行（含修订列 R-04 / R-07 / R-10）.

    Attributes:
        agent_id: 关联 Agent 标识。
        agent_version_id: 关联 AgentVersion 标识。
        conversation_id: 关联会话标识。
        user_id: 触发用户标识（可空）。
        task_id: 关联任务标识（可空）。
        trigger: 触发来源（``RUN_TRIGGER_*``）。
        run_mode: Run 模式（``RunMode`` 字面值）。
        status: 状态（``RunStatus`` 字面值）。
        trace_id / span_id: 可观测骨架（R-07）。
        last_heartbeat_at: 最近心跳（可空，R-04）。
        idempotency_key: 幂等键（可空，R-10）。
        started_at / completed_at: 起止时刻。
        duration_ms: 耗时（毫秒，可空）。
        token_usage: token 用量（JSON 结构）。
        success: 是否成功（终态派生，可空）。
        error_type: 错误类型（可空）。
        tool_error_count: 工具错误计数。
        cost / cost_currency / cost_price_version / cost_estimated / cost_breakdown /
            cost_status: 成本快照（无匹配价目不得记作 0）。
        error: 错误详情（可空）。
    """

    agent_id: str = ""
    agent_version_id: str = ""
    conversation_id: str = ""
    user_id: str | None = None
    task_id: str | None = None
    trigger: str = RUN_TRIGGER_USER
    run_mode: str = RUN_MODE_INLINE
    status: str = RUN_STATUS_PENDING
    trace_id: str | None = None
    span_id: str | None = None
    last_heartbeat_at: datetime | None = None
    idempotency_key: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    success: bool | None = None
    error_type: str | None = None
    tool_error_count: int = 0
    cost: Decimal | None = None
    cost_currency: str | None = None
    cost_price_version: str | None = None
    cost_estimated: bool = False
    cost_breakdown: dict[str, Any] = field(default_factory=dict)
    cost_status: str = COST_STATUS_UNPRICED
    error: str | None = None


@dataclass
class ToolCall(AggregateRoot):
    """工具调用明细（含修订列 R-07 / R-09 / R-22）.

    Attributes:
        run_id: 所属 Run 标识。
        tool_id: 工具标识（可空）。
        tool_name: 工具名。
        tool_type: 工具类型（``TOOL_TYPE_*``，R-22）。
        tool_ref: 工具引用（``{kind,id,name,version}``）。
        attempt: 尝试次数（R-09，失败重试递增）。
        trace_id / span_id: 可观测骨架（R-07）。
        input / output: 入参 / 出参（JSON 结构）。
        status: 状态（``ToolCallStatus`` 字面值）。
        duration_ms: 耗时（毫秒，可空）。
        sandbox_session_id: 关联沙箱会话标识（可空）。
        error: 错误详情（可空）。
    """

    run_id: str = ""
    tool_id: str | None = None
    tool_name: str = ""
    tool_type: str = TOOL_TYPE_BUILTIN
    tool_ref: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    trace_id: str | None = None
    span_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    status: str = TOOL_CALL_STATUS_PENDING
    duration_ms: int | None = None
    sandbox_session_id: str | None = None
    error: str | None = None


@dataclass
class AgentEvent(AggregateRoot):
    """生命周期事件（``seq`` 递增，可回放）.

    Attributes:
        run_id: 所属 Run 标识。
        seq: 序列号（自增）。
        type: 事件类型（9 类之一）。
        payload: 事件载荷（JSON 结构）。
        trace_id / span_id: 可观测骨架（R-07）。
    """

    run_id: str = ""
    seq: int = 0
    type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None
