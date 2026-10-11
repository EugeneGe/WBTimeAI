"""身份相关 DTO。

⚠️ DTO **不**承载任何敏感值（如 ``password_hash``），避免敏感信息经应用层外泄。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from astra_domain import (
    Membership,
    Organization,
    Permission,
    Role,
    Tenant,
    User,
)

from .base import DTO

__all__ = [
    "TenantDTO",
    "UserDTO",
    "OrganizationDTO",
    "MembershipDTO",
    "RoleDTO",
    "PermissionDTO",
]


@dataclass
class TenantDTO(DTO):
    """租户 DTO。"""

    id: str
    name: str
    slug: str
    is_active: bool = True

    @classmethod
    def from_entity(cls, entity: Tenant) -> TenantDTO:
        """由领域实体构造 DTO。"""
        return cls(id=entity.id, name=entity.name, slug=entity.slug, is_active=entity.is_active)


@dataclass
class UserDTO(DTO):
    """用户 DTO（不含 ``password_hash``）。"""

    id: str
    tenant_id: str | None
    username: str
    email: str
    display_name: str | None = None
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: User) -> UserDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            username=entity.username,
            email=entity.email,
            display_name=entity.display_name,
            is_active=entity.is_active,
            is_superuser=entity.is_superuser,
            created_at=entity.created_at,
        )


@dataclass
class OrganizationDTO(DTO):
    """组织 DTO。"""

    id: str
    tenant_id: str | None
    name: str
    slug: str

    @classmethod
    def from_entity(cls, entity: Organization) -> OrganizationDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            name=entity.name,
            slug=entity.slug,
        )


@dataclass
class MembershipDTO(DTO):
    """成员关系 DTO。"""

    id: str
    tenant_id: str | None
    user_id: str
    organization_id: str | None = None
    role_id: str | None = None
    status: str = "active"

    @classmethod
    def from_entity(cls, entity: Membership) -> MembershipDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            user_id=entity.user_id,
            organization_id=entity.organization_id,
            role_id=entity.role_id,
            status=entity.status,
        )


@dataclass
class RoleDTO(DTO):
    """角色 DTO。"""

    id: str
    tenant_id: str | None
    name: str
    description: str | None = None
    is_system: bool = False

    @classmethod
    def from_entity(cls, entity: Role) -> RoleDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            name=entity.name,
            description=entity.description,
            is_system=entity.is_system,
        )


@dataclass
class PermissionDTO(DTO):
    """权限 DTO。"""

    id: str
    code: str
    name: str
    description: str | None = None

    @classmethod
    def from_entity(cls, entity: Permission) -> PermissionDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            code=entity.code,
            name=entity.name,
            description=entity.description,
        )
