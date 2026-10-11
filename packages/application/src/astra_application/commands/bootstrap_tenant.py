"""``BootstrapDefaultTenantCommand`` 及其处理器（调用 ``IdentityBootstrap``）。"""

from __future__ import annotations

from dataclasses import dataclass

from astra_identity import BootstrapResult, IdentityBootstrap

from ..dto.identity import (
    MembershipDTO,
    OrganizationDTO,
    PermissionDTO,
    RoleDTO,
    TenantDTO,
    UserDTO,
)
from .base import Command

__all__ = [
    "BootstrapDefaultTenantCommand",
    "BootstrapDefaultTenantHandler",
    "BootstrapResultDTO",
]


@dataclass
class BootstrapDefaultTenantCommand(Command):
    """建立默认 Tenant / 组织 / admin 角色 / ``*`` 权限 / 默认成员。

    Attributes:
        tenant_name: 默认租户显示名。
        tenant_slug: 默认租户 slug。
        org_name: 默认组织显示名。
        org_slug: 默认组织 slug。
        admin_username: 可选默认管理员用户名。
        admin_email: 管理员邮箱。
        admin_password_hash: 管理员密码哈希（**已是哈希**）。
        admin_display_name: 管理员显示名。
    """

    tenant_name: str | None = None
    tenant_slug: str = "default"
    org_name: str | None = None
    org_slug: str = "default"
    admin_username: str | None = None
    admin_email: str | None = None
    admin_password_hash: str | None = None
    admin_display_name: str | None = None


@dataclass
class BootstrapResultDTO:
    """默认身份引导结果 DTO。"""

    tenant: TenantDTO
    organization: OrganizationDTO
    admin_role: RoleDTO
    admin_permission: PermissionDTO
    admin_user: UserDTO | None = None
    membership: MembershipDTO | None = None

    @classmethod
    def from_result(cls, result: BootstrapResult) -> BootstrapResultDTO:
        """由领域引导结果构造 DTO。"""
        return cls(
            tenant=TenantDTO.from_entity(result.tenant),
            organization=OrganizationDTO.from_entity(result.organization),
            admin_role=RoleDTO.from_entity(result.admin_role),
            admin_permission=PermissionDTO.from_entity(result.admin_permission),
            admin_user=UserDTO.from_entity(result.admin_user) if result.admin_user else None,
            membership=MembershipDTO.from_entity(result.membership) if result.membership else None,
        )


class BootstrapDefaultTenantHandler:
    """默认身份引导命令处理器。"""

    def __init__(self, bootstrap: IdentityBootstrap) -> None:
        self._bootstrap = bootstrap

    def handle(self, command: BootstrapDefaultTenantCommand) -> BootstrapResultDTO:
        """执行默认身份引导并返回 DTO 结果。

        Args:
            command: 引导命令参数。

        Returns:
            :class:`BootstrapResultDTO`。
        """
        result = self._bootstrap.ensure_default_identity(
            tenant_name=command.tenant_name,
            tenant_slug=command.tenant_slug,
            org_name=command.org_name,
            org_slug=command.org_slug,
            admin_username=command.admin_username,
            admin_email=command.admin_email,
            admin_password_hash=command.admin_password_hash,
            admin_display_name=command.admin_display_name,
        )
        return BootstrapResultDTO.from_result(result)
