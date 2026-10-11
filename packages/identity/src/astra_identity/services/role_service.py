"""``RoleService``（角色 / 权限：默认 ``admin`` 角色 + ``*`` 权限）。"""

from __future__ import annotations

from astra_database import session_scope
from astra_domain import (
    ADMIN_PERMISSION,
    SYSTEM_ROLE_ADMIN,
    Permission,
    Role,
    RolePermission,
)
from sqlalchemy.orm import Session, sessionmaker

from ..repositories import (
    SqlPermissionRepository,
    SqlRolePermissionRepository,
    SqlRoleRepository,
)

__all__ = ["RoleService"]


class RoleService:
    """角色 / 权限领域服务（Community 默认 ``admin = *``）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_system_role(
        self, tenant_id: str, name: str = SYSTEM_ROLE_ADMIN, description: str | None = None
    ) -> Role:
        """幂等确保系统角色存在（按租户 + 角色名）。"""
        with session_scope(self._session_factory) as session:
            repo = SqlRoleRepository(session)
            existing = repo.get_by_name(tenant_id, name)
            if existing is not None:
                return existing
            return repo.add(
                Role(tenant_id=tenant_id, name=name, description=description, is_system=True)
            )

    def ensure_admin_role(self, tenant_id: str) -> Role:
        """幂等确保 ``admin`` 角色存在。"""
        return self.ensure_system_role(tenant_id, SYSTEM_ROLE_ADMIN, "系统管理员（默认全权限）")

    def ensure_permission(self, code: str, name: str | None = None) -> Permission:
        """幂等确保权限码存在。"""
        with session_scope(self._session_factory) as session:
            repo = SqlPermissionRepository(session)
            existing = repo.get_by_code(code)
            if existing is not None:
                return existing
            return repo.add(Permission(code=code, name=name or code))

    def ensure_admin_permission(self) -> Permission:
        """幂等确保通配权限 ``*`` 存在。"""
        return self.ensure_permission(ADMIN_PERMISSION, "全部权限（通配）")

    def ensure_role_permission(self, role_id: str, permission_id: str) -> RolePermission:
        """幂等确保角色 ↔ 权限关联存在。"""
        with session_scope(self._session_factory) as session:
            repo = SqlRolePermissionRepository(session)
            existing = repo.get_by_role_and_permission(role_id, permission_id)
            if existing is not None:
                return existing
            return repo.add(RolePermission(role_id=role_id, permission_id=permission_id))

    def list_permissions_for_role(self, role_id: str) -> list[Permission]:
        """列出某角色关联的全部权限。"""
        with session_scope(self._session_factory) as session:
            return SqlRolePermissionRepository(session).list_permissions_for_role(role_id)
