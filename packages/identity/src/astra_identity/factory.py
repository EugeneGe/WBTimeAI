"""identity 组合工厂（供组合根调用）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from .services import (
    AuthorizationService,
    IdentityBootstrap,
    RoleService,
    TenantService,
    UserService,
)

__all__ = ["IdentityServices", "build_identity_services"]


@dataclass
class IdentityServices:
    """身份子域服务集合（组合根产物）。"""

    tenants: TenantService
    users: UserService
    roles: RoleService
    authorization: AuthorizationService
    bootstrap: IdentityBootstrap


def build_identity_services(session_factory: sessionmaker[Session]) -> IdentityServices:
    """依会话工厂构建身份子域服务集合。

    Args:
        session_factory: SQLAlchemy 会话工厂。

    Returns:
        :class:`IdentityServices`。
    """
    return IdentityServices(
        tenants=TenantService(session_factory),
        users=UserService(session_factory),
        roles=RoleService(session_factory),
        authorization=AuthorizationService(session_factory),
        bootstrap=IdentityBootstrap(session_factory),
    )
