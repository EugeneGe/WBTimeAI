"""Model schema（Provider / Model 目录 / 凭证绑定，W6 / T1-29 + T1-30）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "RegisterProviderRequest",
    "RegisterModelRequest",
    "BindCredentialRequest",
    "ModelProviderResponse",
    "ModelResponse",
]


class RegisterProviderRequest(BaseModel):
    """注册模型提供方请求。"""

    name: str = Field(min_length=1, max_length=255)
    provider_type: str = Field(min_length=1, max_length=50)
    endpoint: str | None = None
    credential_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str | None = None


class RegisterModelRequest(BaseModel):
    """注册模型请求。"""

    name: str = Field(min_length=1, max_length=255)
    model_type: str = Field(default="CHAT", max_length=30)
    context_window: int | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class BindCredentialRequest(BaseModel):
    """绑定凭证到 Provider 请求（仅存引用，不复制密文）。"""

    credential_id: str = Field(min_length=1)


class ModelProviderResponse(BaseModel):
    """模型提供方响应（``credential_id`` 仅引用，不含密文 / 明文）。"""

    id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    name: str
    type: str = ""
    endpoint: str | None = None
    credential_id: str | None = None
    status: str = "ACTIVE"
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ModelResponse(BaseModel):
    """模型目录响应。"""

    id: str
    tenant_id: str | None = None
    provider_id: str
    name: str
    type: str = "CHAT"
    context_window: int | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    status: str = "ACTIVE"
    created_at: datetime | None = None
