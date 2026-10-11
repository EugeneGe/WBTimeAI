"""``SqlRoleRepository`` / ``SqlPermissionRepository`` / ``SqlRolePermissionRepository``。

实现领域 ``RoleRepository`` / ``PermissionRepository`` / ``RolePermissionRepository``。
"""

from __future__ import annotations

from typing import Any

from astra_database import BaseRepository
from astra_database.models.identity import Permission as OrmPermission
from astra_database.models.identity import Role as OrmRole
from astra_database.models.identity import RolePermission as OrmRolePermission
from astra_domain import Permission, Role, RolePermission
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..mappers import (
    permission_to_domain,
    permission_to_orm,
    role_permission_to_domain,
    role_permission_to_orm,
    role_to_domain,
    role_to_orm,
)

__all__ = [
    "SqlRoleRepository",
    "SqlPermissionRepository",
    "SqlRolePermissionRepository",
]


class SqlRoleRepository(BaseRepository[OrmRole]):
    """基于 SQLAlchemy 的角色仓储。"""

    model = OrmRole

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmRole)

    def get(self, entity_id: str) -> Role | None:  # type: ignore[override]
        row = super().get(entity_id)
        return role_to_domain(row) if row is not None else None

    def get_by_name(self, tenant_id: str, name: str) -> Role | None:
        statement = select(OrmRole).where(OrmRole.tenant_id == tenant_id, OrmRole.name == name)
        row = self.session.execute(statement).scalar_one_or_none()
        return role_to_domain(row) if row is not None else None

    def add(self, entity: Role) -> Role:  # type: ignore[override]
        row = super().add(role_to_orm(entity))
        return role_to_domain(row)

    def list(self, **filters: Any) -> list[Role]:  # type: ignore[override]
        return [role_to_domain(row) for row in super().list(**filters)]

    def update(self, entity: Role) -> Role:  # type: ignore[override]
        row = super().update(role_to_orm(entity))
        return role_to_domain(row)

    def delete(self, entity: Role) -> None:  # type: ignore[override]
        row = self.session.get(OrmRole, entity.id)
        if row is not None:
            super().delete(row)


class SqlPermissionRepository(BaseRepository[OrmPermission]):
    """基于 SQLAlchemy 的权限仓储。"""

    model = OrmPermission

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmPermission)

    def get(self, entity_id: str) -> Permission | None:  # type: ignore[override]
        row = super().get(entity_id)
        return permission_to_domain(row) if row is not None else None

    def get_by_code(self, code: str) -> Permission | None:
        statement = select(OrmPermission).where(OrmPermission.code == code)
        row = self.session.execute(statement).scalar_one_or_none()
        return permission_to_domain(row) if row is not None else None

    def add(self, entity: Permission) -> Permission:  # type: ignore[override]
        row = super().add(permission_to_orm(entity))
        return permission_to_domain(row)

    def list(self, **filters: Any) -> list[Permission]:  # type: ignore[override]
        return [permission_to_domain(row) for row in super().list(**filters)]

    def update(self, entity: Permission) -> Permission:  # type: ignore[override]
        row = super().update(permission_to_orm(entity))
        return permission_to_domain(row)

    def delete(self, entity: Permission) -> None:  # type: ignore[override]
        row = self.session.get(OrmPermission, entity.id)
        if row is not None:
            super().delete(row)


class SqlRolePermissionRepository(BaseRepository[OrmRolePermission]):
    """基于 SQLAlchemy 的角色权限关联仓储。"""

    model = OrmRolePermission

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmRolePermission)

    def get(self, entity_id: str) -> RolePermission | None:  # type: ignore[override]
        row = super().get(entity_id)
        return role_permission_to_domain(row) if row is not None else None

    def get_by_role_and_permission(self, role_id: str, permission_id: str) -> RolePermission | None:
        statement = select(OrmRolePermission).where(
            OrmRolePermission.role_id == role_id,
            OrmRolePermission.permission_id == permission_id,
        )
        row = self.session.execute(statement).scalar_one_or_none()
        return role_permission_to_domain(row) if row is not None else None

    def list_permissions_for_role(self, role_id: str) -> list[Permission]:
        statement = (
            select(OrmPermission)
            .join(OrmRolePermission, OrmRolePermission.permission_id == OrmPermission.id)
            .where(OrmRolePermission.role_id == role_id)
        )
        rows = self.session.execute(statement).scalars().all()
        return [permission_to_domain(row) for row in rows]

    def add(self, entity: RolePermission) -> RolePermission:  # type: ignore[override]
        row = super().add(role_permission_to_orm(entity))
        return role_permission_to_domain(row)

    def list(self, **filters: Any) -> list[RolePermission]:  # type: ignore[override]
        return [role_permission_to_domain(row) for row in super().list(**filters)]

    def update(self, entity: RolePermission) -> RolePermission:  # type: ignore[override]
        row = super().update(role_permission_to_orm(entity))
        return role_permission_to_domain(row)

    def delete(self, entity: RolePermission) -> None:  # type: ignore[override]
        row = self.session.get(OrmRolePermission, entity.id)
        if row is not None:
            super().delete(row)
