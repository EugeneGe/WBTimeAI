"""Run schema（响应，W6 / T1-28）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["RunResponse", "RunEventResponse", "ToolCallResponse"]


class RunResponse(BaseModel):
    """Run 响应。"""

    id: str
    tenant_id: str | None = None
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
    token_usage: dict[str, Any] = Field(default_factory=dict)
    cost: float | None = None
    cost_status: str = "UNPRICED"
    error: str | None = None


class RunEventResponse(BaseModel):
    """生命周期事件响应。"""

    seq: int
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None
    created_at: datetime | None = None


class ToolCallResponse(BaseModel):
    """工具调用明细响应。"""

    id: str
    run_id: str
    tool_name: str
    tool_type: str = "builtin"
    tool_id: str | None = None
    attempt: int = 1
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    status: str = "PENDING"
    duration_ms: int | None = None
    sandbox_session_id: str | None = None
    error: str | None = None
    created_at: datetime | None = None
