"""用户 / 设备 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["UserResponse", "UpdateUserRequest", "DeviceResponse"]


class UserResponse(BaseModel):
    """用户响应（不含敏感字段）。"""

    id: str
    tenant_id: str | None = None
    username: str
    email: str
    display_name: str | None = None
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime | None = None


class UpdateUserRequest(BaseModel):
    """更新本人信息请求（Phase 0 仅 ``display_name``）。"""

    display_name: str | None = Field(default=None, max_length=255, description="显示名")


class DeviceResponse(BaseModel):
    """设备会话响应。"""

    id: str
    device: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
