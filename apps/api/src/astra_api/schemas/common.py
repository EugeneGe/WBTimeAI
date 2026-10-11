"""通用 schema（错误 / 消息）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ErrorResponse", "MessageResponse"]


class ErrorResponse(BaseModel):
    """统一失败响应壳 ``{code, message, data, request_id}``（总纲 §11.1）。"""

    code: str = Field(description="统一错误码（ErrorCode 字面值）")
    message: str = Field(description="人类可读错误信息")
    data: dict[str, Any] = Field(default_factory=dict, description="附加上下文")
    request_id: str | None = Field(default=None, description="本次请求 request_id（UUIDv7）")


class MessageResponse(BaseModel):
    """简单消息响应。"""

    message: str = Field(description="提示信息")
