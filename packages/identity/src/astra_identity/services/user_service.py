"""``UserService``（用户查询 / 建立；**不含认证**）。"""

from __future__ import annotations

from astra_database import session_scope
from astra_domain import User
from sqlalchemy.orm import Session, sessionmaker

from ..repositories import SqlUserRepository

__all__ = ["UserService"]


class UserService:
    """用户领域服务（不含认证 / 密码逻辑）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, user_id: str) -> User | None:
        """按 id 获取用户。"""
        with session_scope(self._session_factory) as session:
            return SqlUserRepository(session).get(user_id)

    def get_by_username(self, tenant_id: str, username: str) -> User | None:
        """按租户 + 用户名获取用户。"""
        with session_scope(self._session_factory) as session:
            return SqlUserRepository(session).get_by_username(tenant_id, username)

    def get_by_email(self, tenant_id: str, email: str) -> User | None:
        """按租户 + 邮箱获取用户。"""
        with session_scope(self._session_factory) as session:
            return SqlUserRepository(session).get_by_email(tenant_id, email)

    def ensure_user(
        self,
        *,
        tenant_id: str,
        username: str,
        email: str,
        password_hash: str,
        display_name: str | None = None,
        is_superuser: bool = False,
    ) -> User:
        """幂等确保用户存在（按租户 + 用户名）：存在则返回，否则创建。"""
        with session_scope(self._session_factory) as session:
            repo = SqlUserRepository(session)
            existing = repo.get_by_username(tenant_id, username)
            if existing is not None:
                return existing
            return repo.add(
                User(
                    tenant_id=tenant_id,
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    display_name=display_name,
                    is_superuser=is_superuser,
                )
            )

    def update_profile(self, user_id: str, *, display_name: str | None) -> User:
        """更新用户资料（Phase 0 仅 ``display_name``，**不新增列 / 不新增迁移**）。

        Args:
            user_id: 用户标识。
            display_name: 新显示名。

        Returns:
            更新后的 :class:`~astra_domain.entities.user.User`。

        Raises:
            DomainError: 用户不存在（``USER_NOT_FOUND``）。
        """
        from astra_core import DomainError, ErrorCode

        with session_scope(self._session_factory) as session:
            repo = SqlUserRepository(session)
            user = repo.get(user_id)
            if user is None:
                raise DomainError(
                    "用户不存在",
                    code=ErrorCode.USER_NOT_FOUND,
                    data={"user_id": user_id},
                )
            user.display_name = display_name
            user.touch()
            return repo.update(user)
