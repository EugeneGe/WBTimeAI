"""可撤销 Session 服务（决策 D1）。

覆盖：创建会话（access + refresh）/ 登出撤销 / 强制退出撤销全部 / 多设备列表。
`refresh_token` **仅存哈希**（``token_hash``）；撤销后旧 refresh **立即失效**。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from astra_domain import (
    RefreshTokenRecord,
    SessionRecord,
)
from sqlalchemy.orm import Session, sessionmaker

from .jwt import REFRESH, TokenService
from .repositories import SqlRefreshTokenRepository, SqlSessionRepository

__all__ = ["SessionTokens", "DeviceSession", "SessionService"]

#: 默认会话有效期（秒）——与 refresh token TTL 对齐。
DEFAULT_SESSION_TTL_SECONDS = 1_209_600


def _hash_token(token: str) -> str:
    """计算 refresh token 的存储哈希（SHA-256）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class SessionTokens:
    """一次登录产生的令牌组。

    Attributes:
        session_id: 会话 ID。
        access_token: 访问令牌。
        refresh_token: 刷新令牌（明文仅此一次返回，服务端仅存哈希）。
    """

    session_id: str
    access_token: str
    refresh_token: str


@dataclass
class DeviceSession:
    """设备会话视图。"""

    id: str
    device: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


class SessionService:
    """会话服务（创建 / 撤销 / 强退 / 列设备）。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        token_service: TokenService,
        *,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._tokens = token_service
        self._session_ttl = session_ttl_seconds

    def create_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        device: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SessionTokens:
        """创建会话并签发 access + refresh 令牌。"""
        with session_scope(self._session_factory) as session:
            session_repo = SqlSessionRepository(session)
            token_repo = SqlRefreshTokenRepository(session)

            record = session_repo.add(
                SessionRecord(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    device=device,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    expires_at=utcnow() + timedelta(seconds=self._session_ttl),
                )
            )

            refresh_token = self._tokens.create_refresh_token(
                user_id, tenant_id=tenant_id, session_id=record.id
            )
            token_repo.add(
                RefreshTokenRecord(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=record.id,
                    token_hash=_hash_token(refresh_token),
                    expires_at=utcnow() + timedelta(seconds=self._session_ttl),
                )
            )
            access_token = self._tokens.create_access_token(
                user_id, tenant_id=tenant_id, session_id=record.id
            )
            return SessionTokens(
                session_id=record.id,
                access_token=access_token,
                refresh_token=refresh_token,
            )

    def authenticate_refresh(self, refresh_token: str) -> RefreshTokenRecord:
        """校验 refresh 令牌，返回有效记录。

        Args:
            refresh_token: refresh 令牌明文。

        Returns:
            :class:`~astra_domain.repositories.auth.RefreshTokenRecord`。

        Raises:
            DomainError: 令牌无效 / 过期（``AUTH_TOKEN_*``）；已撤销 / 会话已撤销
                （``AUTH_TOKEN_REVOKED``）。
        """
        claims = self._tokens.decode(refresh_token, expected_type=REFRESH)
        with session_scope(self._session_factory) as session:
            token_repo = SqlRefreshTokenRepository(session)
            record = token_repo.get_by_hash(_hash_token(refresh_token))
            if record is None:
                raise DomainError("refresh 令牌不存在", code=ErrorCode.AUTH_TOKEN_INVALID)
            if record.revoked_at is not None:
                raise DomainError("refresh 令牌已撤销", code=ErrorCode.AUTH_TOKEN_REVOKED)

            session_repo = SqlSessionRepository(session)
            session_record = session_repo.get(claims.sid) if claims.sid else None
            if session_record is not None and session_record.revoked_at is not None:
                raise DomainError("会话已撤销", code=ErrorCode.AUTH_TOKEN_REVOKED)
            return record

    def revoke_session(self, session_id: str) -> None:
        """登出：撤销指定会话及其 refresh 令牌。"""
        now = utcnow()
        with session_scope(self._session_factory) as session:
            SqlSessionRepository(session).revoke(session_id, revoked_at=now)
            SqlRefreshTokenRepository(session).revoke_by_session(session_id, revoked_at=now)

    def revoke_all_sessions(self, user_id: str) -> int:
        """强制退出：撤销某用户全部会话与 refresh 令牌。

        Returns:
            被撤销的会话数量。
        """
        now = utcnow()
        with session_scope(self._session_factory) as session:
            count = SqlSessionRepository(session).revoke_all_for_user(user_id, revoked_at=now)
            SqlRefreshTokenRepository(session).revoke_all_for_user(user_id, revoked_at=now)
            return count

    def list_devices(self, user_id: str) -> list[DeviceSession]:
        """列出某用户的全部设备会话。"""
        with session_scope(self._session_factory) as session:
            records = SqlSessionRepository(session).list_by_user(user_id)
            return [
                DeviceSession(
                    id=record.id,
                    device=record.device,
                    ip_address=record.ip_address,
                    user_agent=record.user_agent,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                    revoked_at=record.revoked_at,
                )
                for record in records
            ]
