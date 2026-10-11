"""认证相关 DTO（决策 D1）。"""

from __future__ import annotations

from dataclasses import dataclass

from .base import DTO
from .identity import UserDTO

__all__ = ["TokenPairDTO", "AuthResultDTO"]


@dataclass
class TokenPairDTO(DTO):
    """一次性签发的令牌组。

    Attributes:
        access_token: 访问令牌。
        refresh_token: 刷新令牌（明文仅此一次返回）。
        token_type: 令牌类型（默认 ``bearer``）。
        expires_in: access token 有效期（秒）。
        session_id: 会话标识。
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900
    session_id: str = ""


@dataclass
class AuthResultDTO(DTO):
    """认证结果（用户 + 令牌组）。"""

    user: UserDTO
    tokens: TokenPairDTO | None = None
