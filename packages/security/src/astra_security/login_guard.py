"""登录爆破防护：连续失败锁定（写入 ``login_attempt``）。"""

from __future__ import annotations

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from astra_domain import LoginAttemptRecord
from sqlalchemy.orm import Session, sessionmaker

from .repositories import SqlLoginAttemptRepository

__all__ = ["LoginGuard"]


class LoginGuard:
    """登录尝试记录与连续失败锁定。

    策略：在某时间窗（``lock_seconds``）内，同一用户名的**连续失败**次数达到
    ``max_attempts`` 即判定锁定（抛 ``AUTH_ACCOUNT_LOCKED``）。
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        max_attempts: int = 5,
        lock_seconds: int = 900,
    ) -> None:
        self._session_factory = session_factory
        self._max_attempts = max_attempts
        self._lock_seconds = lock_seconds

    def record(
        self,
        *,
        username: str,
        success: bool,
        tenant_id: str | None = None,
        ip_address: str | None = None,
    ) -> LoginAttemptRecord:
        """记录一次登录尝试。"""
        with session_scope(self._session_factory) as session:
            return SqlLoginAttemptRepository(session).add(
                LoginAttemptRecord(
                    tenant_id=tenant_id,
                    username=username,
                    ip_address=ip_address,
                    success=success,
                )
            )

    def consecutive_failures(self, username: str, *, tenant_id: str | None = None) -> int:
        """统计最近一次成功之后的连续失败次数。"""
        with session_scope(self._session_factory) as session:
            recent = SqlLoginAttemptRepository(session).recent_for_username(
                username, limit=max(self._max_attempts * 4, 20), tenant_id=tenant_id
            )
        count = 0
        for attempt in recent:
            if attempt.success:
                break
            count += 1
        return count

    def is_locked(self, username: str, *, tenant_id: str | None = None) -> bool:
        """判断用户名是否处于锁定期。"""
        with session_scope(self._session_factory) as session:
            recent = SqlLoginAttemptRepository(session).recent_for_username(
                username, limit=max(self._max_attempts * 4, 20), tenant_id=tenant_id
            )
        failures = 0
        now = utcnow()
        for attempt in recent:
            if attempt.success:
                break
            failures += 1
        if failures < self._max_attempts:
            return False
        # 最近一次失败（列表首条）是否落在锁定窗内。
        last_failure = next((a for a in recent if not a.success), None)
        if last_failure is None:
            return False
        created = last_failure.created_at
        if created is None:
            return True
        if created.tzinfo is None:
            from datetime import UTC

            created = created.replace(tzinfo=UTC)
        return (now - created).total_seconds() <= self._lock_seconds

    def assert_not_locked(self, username: str, *, tenant_id: str | None = None) -> None:
        """若处于锁定期则抛错。

        Raises:
            DomainError: 锁定中（``AUTH_ACCOUNT_LOCKED``）。
        """
        if self.is_locked(username, tenant_id=tenant_id):
            raise DomainError(
                "账号因连续登录失败已被临时锁定",
                code=ErrorCode.AUTH_ACCOUNT_LOCKED,
                data={"username": username, "lock_seconds": self._lock_seconds},
            )

    def register_failure(
        self,
        *,
        username: str,
        tenant_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """登记一次失败尝试（写库）。"""
        self.record(username=username, success=False, tenant_id=tenant_id, ip_address=ip_address)

    def register_success(
        self,
        *,
        username: str,
        tenant_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """登记一次成功尝试（写库，重置连续失败计数）。"""
        self.record(username=username, success=True, tenant_id=tenant_id, ip_address=ip_address)
