"""``MembershipRepository`` 接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.membership import Membership
from .base import Repository

__all__ = ["MembershipRepository"]


@runtime_checkable
class MembershipRepository(Repository[Membership], Protocol):
    """成员关系仓储接口。"""

    def list_by_user(self, user_id: str) -> list[Membership]:
        """列出某用户的全部成员关系。"""
        ...

    def get_by_user_and_org(self, user_id: str, organization_id: str | None) -> Membership | None:
        """按用户 + 组织获取成员关系（组织可为空）。"""
        ...
