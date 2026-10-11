"""Astra AI 身份与多租户（``astra_identity``）。

- SQLAlchemy 仓储实现（复用 ``astra_database.BaseRepository``）：``repositories/``
- ORM ↔ 领域实体映射：``mappers``
- 领域服务：``services/``（含 **幂等默认身份引导** ``IdentityBootstrap``）
- 组合工厂：``factory.build_identity_services``
"""

from __future__ import annotations

from .factory import IdentityServices, build_identity_services
from .mappers import (
    membership_to_domain,
    membership_to_orm,
    organization_to_domain,
    organization_to_orm,
    permission_to_domain,
    permission_to_orm,
    role_permission_to_domain,
    role_permission_to_orm,
    role_to_domain,
    role_to_orm,
    tenant_to_domain,
    tenant_to_orm,
    user_to_domain,
    user_to_orm,
)
from .repositories import (
    SqlMembershipRepository,
    SqlOrganizationRepository,
    SqlPermissionRepository,
    SqlRolePermissionRepository,
    SqlRoleRepository,
    SqlTenantRepository,
    SqlUserRepository,
)
from .services import (
    AuthorizationService,
    BootstrapResult,
    IdentityBootstrap,
    RoleService,
    TenantService,
    UserService,
)

__all__ = [
    # services
    "TenantService",
    "UserService",
    "RoleService",
    "AuthorizationService",
    "IdentityBootstrap",
    "BootstrapResult",
    # factory
    "IdentityServices",
    "build_identity_services",
    # repositories
    "SqlTenantRepository",
    "SqlUserRepository",
    "SqlOrganizationRepository",
    "SqlMembershipRepository",
    "SqlRoleRepository",
    "SqlPermissionRepository",
    "SqlRolePermissionRepository",
    # mappers
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
