"""``IdentityBootstrap``——默认身份引导（Tenant-ready 核心）。

幂等建立：默认 ``default`` 租户 → 默认组织 → 系统 ``admin`` 角色 → 通配 ``*`` 权限
→ 角色权限关联 →（可选）默认管理员用户与默认成员关系。

对齐设计 §2.4 / §3-#5「Tenant-ready：默认 ``default`` Tenant 自动建立、用户无感」。
"""

from __future__ import annotations

from dataclasses import dataclass

from astra_database import session_scope
from astra_domain import (
    ADMIN_PERMISSION,
    DEFAULT_ORG_NAME,
    DEFAULT_ORG_SLUG,
    DEFAULT_TENANT_NAME,
    DEFAULT_TENANT_SLUG,
    SYSTEM_ROLE_ADMIN,
    Membership,
    Organization,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
)
from sqlalchemy.orm import Session, sessionmaker

from ..repositories import (
    SqlMembershipRepository,
    SqlOrganizationRepository,
    SqlPermissionRepository,
    SqlRolePermissionRepository,
    SqlRoleRepository,
    SqlTenantRepository,
    SqlUserRepository,
)

__all__ = ["BootstrapResult", "IdentityBootstrap"]


@dataclass
class BootstrapResult:
    """默认身份引导结果。

    Attributes:
        tenant: 默认租户。
        organization: 默认组织。
        admin_role: 系统 ``admin`` 角色。
        admin_permission: 通配权限 ``*``。
        admin_user: 默认管理员用户（未提供管理员参数时为 ``None``）。
        membership: 默认成员关系（未提供管理员参数时为 ``None``）。
    """

    tenant: Tenant
    organization: Organization
    admin_role: Role
    admin_permission: Permission
    admin_user: User | None = None
    membership: Membership | None = None


class IdentityBootstrap:
    """默认身份引导器（幂等）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_default_identity(
        self,
        *,
        tenant_name: str | None = None,
        tenant_slug: str = DEFAULT_TENANT_SLUG,
        org_name: str | None = None,
        org_slug: str = DEFAULT_ORG_SLUG,
        admin_username: str | None = None,
        admin_email: str | None = None,
        admin_password_hash: str | None = None,
        admin_display_name: str | None = None,
    ) -> BootstrapResult:
        """幂等建立默认 Tenant / 组织 / admin 角色 / ``*`` 权限 / 默认成员。

        重复调用不会产生重复记录。

        Args:
            tenant_name: 默认租户显示名（缺省 ``Default``）。
            tenant_slug: 默认租户 slug（缺省 ``default``）。
            org_name: 默认组织显示名（缺省 ``Default``）。
            org_slug: 默认组织 slug（缺省 ``default``）。
            admin_username: 可选默认管理员用户名（提供则建立管理员与成员关系）。
            admin_email: 管理员邮箱（提供管理员时必填）。
            admin_password_hash: 管理员密码哈希（**已是哈希**，明文不落库）。
            admin_display_name: 管理员显示名。

        Returns:
            :class:`BootstrapResult`。

        Raises:
            DomainError: 当提供了 ``admin_username`` 却缺少邮箱 / 密码哈希时。
        """
        from astra_core import DomainError, ErrorCode

        if admin_username is not None and (not admin_email or not admin_password_hash):
            raise DomainError(
                "建立默认管理员需同时提供 admin_email 与 admin_password_hash",
                code=ErrorCode.VALIDATION_ERROR,
            )

        with session_scope(self._session_factory) as session:
            tenant = self._ensure_tenant(session, tenant_slug, tenant_name or DEFAULT_TENANT_NAME)
            organization = self._ensure_organization(
                session, tenant.id, org_slug, org_name or DEFAULT_ORG_NAME
            )
            role = self._ensure_role(session, tenant.id, SYSTEM_ROLE_ADMIN)
            permission = self._ensure_permission(session, ADMIN_PERMISSION)
            self._ensure_role_permission(session, role.id, permission.id)

            admin_user: User | None = None
            membership: Membership | None = None
            if admin_username is not None:
                admin_user = self._ensure_user(
                    session,
                    tenant_id=tenant.id,
                    username=admin_username,
                    email=admin_email or "",
                    password_hash=admin_password_hash or "",
                    display_name=admin_display_name,
                )
                membership = self._ensure_membership(
                    session,
                    tenant_id=tenant.id,
                    user_id=admin_user.id,
                    organization_id=organization.id,
                    role_id=role.id,
                )

            return BootstrapResult(
                tenant=tenant,
                organization=organization,
                admin_role=role,
                admin_permission=permission,
                admin_user=admin_user,
                membership=membership,
            )

    def ensure_membership(
        self,
        *,
        tenant_id: str,
        user_id: str,
        organization_id: str | None,
        role_id: str | None,
        status: str | None = None,
    ) -> Membership:
        """幂等确保成员关系存在（按用户 + 组织），供注册授予默认角色使用。

        Args:
            tenant_id: 所属租户标识。
            user_id: 用户标识。
            organization_id: 组织标识（可空）。
            role_id: 角色标识（可空）。
            status: 成员状态（缺省 ``active``）。

        Returns:
            既存或新建的 :class:`~astra_domain.entities.membership.Membership`。
        """
        with session_scope(self._session_factory) as session:
            repo = SqlMembershipRepository(session)
            existing = repo.get_by_user_and_org(user_id, organization_id)
            if existing is not None:
                return existing
            if status is None:
                membership = Membership(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    organization_id=organization_id,
                    role_id=role_id,
                )
            else:
                membership = Membership(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    organization_id=organization_id,
                    role_id=role_id,
                    status=status,
                )
            return repo.add(membership)

    # -- 内部幂等助手（复用同一 session，保证原子性） -----------------------

    @staticmethod
    def _ensure_tenant(session: Session, slug: str, name: str) -> Tenant:
        repo = SqlTenantRepository(session)
        existing = repo.get_by_slug(slug)
        if existing is not None:
            return existing
        return repo.add(Tenant(name=name, slug=slug))

    @staticmethod
    def _ensure_organization(
        session: Session, tenant_id: str, slug: str, name: str
    ) -> Organization:
        repo = SqlOrganizationRepository(session)
        existing = repo.get_by_slug(tenant_id, slug)
        if existing is not None:
            return existing
        return repo.add(Organization(tenant_id=tenant_id, name=name, slug=slug))

    @staticmethod
    def _ensure_role(session: Session, tenant_id: str, name: str) -> Role:
        repo = SqlRoleRepository(session)
        existing = repo.get_by_name(tenant_id, name)
        if existing is not None:
            return existing
        return repo.add(
            Role(
                tenant_id=tenant_id,
                name=name,
                description="系统管理员（默认全权限）",
                is_system=True,
            )
        )

    @staticmethod
    def _ensure_permission(session: Session, code: str) -> Permission:
        repo = SqlPermissionRepository(session)
        existing = repo.get_by_code(code)
        if existing is not None:
            return existing
        return repo.add(Permission(code=code, name="全部权限（通配）"))

    @staticmethod
    def _ensure_role_permission(
        session: Session, role_id: str, permission_id: str
    ) -> RolePermission:
        repo = SqlRolePermissionRepository(session)
        existing = repo.get_by_role_and_permission(role_id, permission_id)
        if existing is not None:
            return existing
        return repo.add(RolePermission(role_id=role_id, permission_id=permission_id))

    @staticmethod
    def _ensure_user(
        session: Session,
        *,
        tenant_id: str,
        username: str,
        email: str,
        password_hash: str,
        display_name: str | None,
    ) -> User:
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
                is_superuser=True,
            )
        )

    @staticmethod
    def _ensure_membership(
        session: Session,
        *,
        tenant_id: str,
        user_id: str,
        organization_id: str,
        role_id: str,
    ) -> Membership:
        repo = SqlMembershipRepository(session)
        existing = repo.get_by_user_and_org(user_id, organization_id)
        if existing is not None:
            return existing
        return repo.add(
            Membership(
                tenant_id=tenant_id,
                user_id=user_id,
                organization_id=organization_id,
                role_id=role_id,
            )
        )
