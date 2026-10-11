"""``UserRepository`` 接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.user import User
from .base import Repository

__all__ = ["UserRepository"]


@runtime_checkable
class UserRepository(Repository[User], Protocol):
    """用户仓储接口。"""

    def get_by_username(self, tenant_id: str, username: str) -> User | None:
        """按租户 + 用户名获取用户。"""
        ...

    def get_by_email(self, tenant_id: str, email: str) -> User | None:
        """按租户 + 邮箱获取用户。"""
        ...
