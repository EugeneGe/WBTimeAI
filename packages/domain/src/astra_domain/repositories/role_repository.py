"""``RoleRepository`` / ``PermissionRepository`` 接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.role import Permission, Role, RolePermission
from .base import Repository

__all__ = ["RoleRepository", "PermissionRepository", "RolePermissionRepository"]


@runtime_checkable
class RoleRepository(Repository[Role], Protocol):
    """角色仓储接口。"""

    def get_by_name(self, tenant_id: str, name: str) -> Role | None:
        """按租户 + 角色名获取角色。"""
        ...


@runtime_checkable
class PermissionRepository(Repository[Permission], Protocol):
    """权限仓储接口。"""

    def get_by_code(self, code: str) -> Permission | None:
        """按权限码获取权限。"""
        ...


@runtime_checkable
class RolePermissionRepository(Repository[RolePermission], Protocol):
    """角色 ↔ 权限 关联仓储接口。"""

    def get_by_role_and_permission(self, role_id: str, permission_id: str) -> RolePermission | None:
        """按角色 + 权限获取关联。"""
        ...

    def list_permissions_for_role(self, role_id: str) -> list[Permission]:
        """列出某角色关联的全部权限。"""
        ...
