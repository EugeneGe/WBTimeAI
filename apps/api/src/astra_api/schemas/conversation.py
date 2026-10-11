"""Conversation schema（会话 / 消息，W6 / T1-29）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CreateConversationRequest",
    "ConversationResponse",
    "ConversationMessageResponse",
]


class CreateConversationRequest(BaseModel):
    """创建会话请求。"""

    agent_id: str = Field(min_length=1)
    workspace_id: str = ""
    title: str = Field(default="", max_length=255)


class ConversationResponse(BaseModel):
    """会话响应。"""

    id: str
    tenant_id: str | None = None
    workspace_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    title: str = ""
    status: str = "ACTIVE"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationMessageResponse(BaseModel):
    """会话消息响应。"""

    id: str
    conversation_id: str
    run_id: str | None = None
    role: str = "user"
    content: str = ""
    content_parts: list[Any] = Field(default_factory=list)
    token_count: int | None = None
    created_at: datetime | None = None
