"""认证 schema（注册 / 登录 / 刷新 / 令牌）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "TokenResponse",
    "AuthUserResponse",
]


class RegisterRequest(BaseModel):
    """注册请求。"""

    username: str = Field(min_length=1, max_length=150, description="用户名")
    email: str = Field(min_length=3, max_length=320, description="邮箱")
    password: str = Field(min_length=6, max_length=256, description="口令（明文，仅传输）")
    display_name: str | None = Field(default=None, max_length=255, description="显示名")


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=150, description="用户名")
    password: str = Field(min_length=1, max_length=256, description="口令")


class RefreshRequest(BaseModel):
    """刷新令牌请求。"""

    refresh_token: str = Field(min_length=1, description="refresh token")


class TokenResponse(BaseModel):
    """令牌响应。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class AuthUserResponse(BaseModel):
    """认证上下文中的用户信息（不含敏感字段）。"""

    id: str
    tenant_id: str | None = None
    username: str
    email: str
    display_name: str | None = None
