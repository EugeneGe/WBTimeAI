"""ORM 行 ↔ 领域实体 映射。

将 ``astra_database.models.*`` 的 SQLAlchemy 行转换为 ``astra_domain`` 实体
（以及反向），使领域层保持零框架依赖。
"""

from __future__ import annotations

from astra_common.time import utcnow
from astra_database.models.identity import (
    Membership as OrmMembership,
)
from astra_database.models.identity import (
    Organization as OrmOrganization,
)
from astra_database.models.identity import (
    Permission as OrmPermission,
)
from astra_database.models.identity import (
    Role as OrmRole,
)
from astra_database.models.identity import (
    RolePermission as OrmRolePermission,
)
from astra_database.models.identity import (
    Tenant as OrmTenant,
)
from astra_database.models.identity import (
    User as OrmUser,
)
from astra_domain.entities import (
    Membership,
    Organization,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
)

__all__ = [
    "tenant_to_domain",
    "tenant_to_orm",
    "user_to_domain",
    "user_to_orm",
    "organization_to_domain",
    "organization_to_orm",
    "membership_to_domain",
    "membership_to_orm",
    "role_to_domain",
    "role_to_orm",
    "permission_to_domain",
    "permission_to_orm",
    "role_permission_to_domain",
    "role_permission_to_orm",
]


def _dt(value: object):
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


# -- Tenant ------------------------------------------------------------------


def tenant_to_domain(row: OrmTenant) -> Tenant:
    """ORM 租户行 → 领域 ``Tenant``。"""
    return Tenant(
        id=row.id,
        tenant_id=None,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        name=row.name,
        slug=row.slug,
        is_active=row.is_active,
    )


def tenant_to_orm(entity: Tenant) -> OrmTenant:
    """领域 ``Tenant`` → ORM 行。"""
    return OrmTenant(
        id=entity.id,
        name=entity.name,
        slug=entity.slug,
        is_active=entity.is_active,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


# -- User --------------------------------------------------------------------


def user_to_domain(row: OrmUser) -> User:
    """ORM 用户行 → 领域 ``User``。"""
    return User(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        username=row.username,
        email=row.email,
        password_hash=row.password_hash,
        display_name=row.display_name,
        is_active=row.is_active,
        is_superuser=row.is_superuser,
    )


def user_to_orm(entity: User) -> OrmUser:
    """领域 ``User`` → ORM 行。"""
    return OrmUser(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        username=entity.username,
        email=entity.email,
        password_hash=entity.password_hash,
        display_name=entity.display_name,
        is_active=entity.is_active,
        is_superuser=entity.is_superuser,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


# -- Organization ------------------------------------------------------------


def organization_to_domain(row: OrmOrganization) -> Organization:
    """ORM 组织行 → 领域 ``Organization``。"""
    return Organization(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        name=row.name,
        slug=row.slug,
    )


def organization_to_orm(entity: Organization) -> OrmOrganization:
    """领域 ``Organization`` → ORM 行。"""
    return OrmOrganization(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        name=entity.name,
        slug=entity.slug,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


# -- Membership --------------------------------------------------------------


def membership_to_domain(row: OrmMembership) -> Membership:
    """ORM 成员关系行 → 领域 ``Membership``。"""
    return Membership(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        user_id=row.user_id,
        organization_id=row.organization_id,
        role_id=row.role_id,
        status=row.status,
    )


def membership_to_orm(entity: Membership) -> OrmMembership:
    """领域 ``Membership`` → ORM 行。"""
    return OrmMembership(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        user_id=entity.user_id,
        organization_id=entity.organization_id,
        role_id=entity.role_id,
        status=entity.status,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


# -- Role --------------------------------------------------------------------


def role_to_domain(row: OrmRole) -> Role:
    """ORM 角色行 → 领域 ``Role``。"""
    return Role(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        name=row.name,
        description=row.description,
        is_system=row.is_system,
    )


def role_to_orm(entity: Role) -> OrmRole:
    """领域 ``Role`` → ORM 行。"""
    return OrmRole(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        name=entity.name,
        description=entity.description,
        is_system=entity.is_system,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


# -- Permission --------------------------------------------------------------


def permission_to_domain(row: OrmPermission) -> Permission:
    """ORM 权限行 → 领域 ``Permission``。"""
    return Permission(
        id=row.id,
        tenant_id=None,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        code=row.code,
        name=row.name,
        description=row.description,
    )


def permission_to_orm(entity: Permission) -> OrmPermission:
    """领域 ``Permission`` → ORM 行。"""
    return OrmPermission(
        id=entity.id,
        code=entity.code,
        name=entity.name,
        description=entity.description,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


# -- RolePermission ----------------------------------------------------------


def role_permission_to_domain(row: OrmRolePermission) -> RolePermission:
    """ORM 角色权限关联行 → 领域 ``RolePermission``。"""
    return RolePermission(
        id=row.id,
        tenant_id=None,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        role_id=row.role_id,
        permission_id=row.permission_id,
    )


def role_permission_to_orm(entity: RolePermission) -> OrmRolePermission:
    """领域 ``RolePermission`` → ORM 行。"""
    return OrmRolePermission(
        id=entity.id,
        role_id=entity.role_id,
        permission_id=entity.permission_id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )
