"""设置 schema（系统 / 个人 / 凭证）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "SystemSettingsResponse",
    "PersonalSettingsResponse",
    "UpdatePersonalSettingsRequest",
    "SaveCredentialRequest",
    "CredentialResponse",
    "FeatureFlagsResponse",
]


class SystemSettingsResponse(BaseModel):
    """系统设置响应（**不含任何密钥类配置**）。"""

    mode: str
    app_name: str
    app_version: str


class PersonalSettingsResponse(BaseModel):
    """个人设置响应。"""

    user_id: str
    username: str
    email: str
    display_name: str | None = None


class UpdatePersonalSettingsRequest(BaseModel):
    """更新个人设置请求（Phase 0 仅 ``display_name``）。"""

    display_name: str | None = Field(default=None, max_length=255)


class SaveCredentialRequest(BaseModel):
    """保存凭证请求（API Key 入口；``value`` 为明文，仅传输）。"""

    provider: str = Field(min_length=1, max_length=100, description="提供方，如 openai")
    key_type: str = Field(default="api_key", max_length=50, description="键类型")
    value: str = Field(min_length=1, description="明文密钥（仅传输，不落库 / 不回显）")
    workspace_id: str | None = Field(default=None, description="所属工作区（可空）")


class CredentialResponse(BaseModel):
    """凭证响应（**仅掩码**，无明文 / 密文）。"""

    id: str
    provider: str
    key_type: str
    masked_value: str
    workspace_id: str | None = None
    created_at: datetime | None = None


class FeatureFlagsResponse(BaseModel):
    """Feature Flag 观测响应（``name`` → 是否启用，T0-21 / 验收 §3-#14）。"""

    flags: dict[str, bool] = Field(default_factory=dict, description="flag 名 → 是否启用")
