"""认证支撑 ORM 表组（决策 D1：JWT + 可撤销 Session）。

⚠️ 仅表结构；认证实现（签发 / 撤销 / 锁定）属 T0-12，本轮不实现。
"""

from __future__ import annotations

from datetime import datetime

from astra_core import generate_id
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID

__all__ = ["UserSession", "RefreshToken", "LoginAttempt"]


class UserSession(Base, TimestampMixin):
    """会话（多设备可见 / 强退支撑）。"""

    __tablename__ = "session"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("user.id"), nullable=False, index=True)
    device: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RefreshToken(Base, TimestampMixin):
    """可撤销的 refresh token（仅存哈希）。"""

    __tablename__ = "refresh_token"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("user.id"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("session.id"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginAttempt(Base, TimestampMixin):
    """登录尝试记录（口令爆破防护与锁定策略支撑）。"""

    __tablename__ = "login_attempt"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=True, index=True
    )
    username: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
