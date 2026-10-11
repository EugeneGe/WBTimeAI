"""``AuthorizationService``——最小 RBAC 判定（设计 §2.6 / §2S.0.1）。

判定链路：``membership → role → role_permission → permission``。
Community 默认 ``admin = *`` **通配放行**（任何权限码均通过）。
"""

from __future__ import annotations

from astra_database import session_scope
from astra_domain import ADMIN_PERMISSION
from sqlalchemy.orm import Session, sessionmaker

from ..repositories import SqlMembershipRepository, SqlRolePermissionRepository

__all__ = ["AuthorizationService"]


class AuthorizationService:
    """最小 RBAC 判定服务（``admin = *`` 通配）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def has_permission(self, user_id: str, code: str) -> bool:
        """判断用户是否拥有指定权限码（含 ``*`` 通配）。

        Args:
            user_id: 用户标识。
            code: 权限码（如 ``workspace:create``）。

        Returns:
            拥有该权限（或被 ``*`` 通配放行）返回 ``True``，否则 ``False``。
        """
        codes = self.permission_codes(user_id)
        return code in codes or ADMIN_PERMISSION in codes

    def permission_codes(self, user_id: str) -> set[str]:
        """汇总用户经全部角色获得的权限码集合。"""
        with session_scope(self._session_factory) as session:
            memberships = SqlMembershipRepository(session).list_by_user(user_id)
            role_ids = {m.role_id for m in memberships if m.role_id}
            if not role_ids:
                return set()
            repo = SqlRolePermissionRepository(session)
            codes: set[str] = set()
            for role_id in role_ids:
                for permission in repo.list_permissions_for_role(role_id):
                    codes.add(permission.code)
            return codes
