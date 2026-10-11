"""认证支撑仓储接口（决策 D1）。

对应 ORM 表：``session`` / ``refresh_token`` / ``login_attempt``。
🔴 仅接口；SQLAlchemy 实现位于 ``astra_security/repositories/``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from astra_core import generate_id  # noqa: F401 - 供实现参考（唯一 ID 入口）

__all__ = [
    "SessionRecord",
    "RefreshTokenRecord",
    "LoginAttemptRecord",
    "SessionRepository",
    "RefreshTokenRepository",
    "LoginAttemptRepository",
]


from dataclasses import dataclass, field  # noqa: E402


@dataclass
class SessionRecord:
    """会话记录（认证聚合，非领域实体；仅承载持久化字段）。"""

    id: str = field(default_factory=generate_id)
    tenant_id: str = ""
    user_id: str = ""
    device: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class RefreshTokenRecord:
    """Refresh Token 记录（仅存哈希 ``token_hash``）。"""

    id: str = field(default_factory=generate_id)
    tenant_id: str = ""
    user_id: str = ""
    session_id: str | None = None
    token_hash: str = ""
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class LoginAttemptRecord:
    """登录尝试记录。"""

    id: str = field(default_factory=generate_id)
    tenant_id: str | None = None
    username: str | None = None
    ip_address: str | None = None
    success: bool = False
    created_at: datetime | None = None


@runtime_checkable
class SessionRepository(Protocol):
    """会话仓储接口。"""

    def add(self, record: SessionRecord) -> SessionRecord: ...

    def get(self, session_id: str) -> SessionRecord | None: ...

    def list_by_user(self, user_id: str) -> list[SessionRecord]: ...

    def revoke(self, session_id: str, *, revoked_at: datetime) -> None: ...

    def revoke_all_for_user(self, user_id: str, *, revoked_at: datetime) -> int: ...


@runtime_checkable
class RefreshTokenRepository(Protocol):
    """Refresh Token 仓储接口。"""

    def add(self, record: RefreshTokenRecord) -> RefreshTokenRecord: ...

    def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None: ...

    def revoke(self, token_id: str, *, revoked_at: datetime) -> None: ...

    def revoke_by_session(self, session_id: str, *, revoked_at: datetime) -> int: ...

    def revoke_all_for_user(self, user_id: str, *, revoked_at: datetime) -> int: ...


@runtime_checkable
class LoginAttemptRepository(Protocol):
    """登录尝试仓储接口。"""

    def add(self, record: LoginAttemptRecord) -> LoginAttemptRecord: ...

    def recent_for_username(
        self, username: str, *, limit: int = 20, tenant_id: str | None = None
    ) -> list[LoginAttemptRecord]:
        """按时间倒序返回某用户名的最近登录尝试。"""
        ...
