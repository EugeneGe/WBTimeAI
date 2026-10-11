"""默认身份引导幂等单测（设计 §3-#5 Tenant-ready）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from astra_database import Base, create_session_factory
from astra_identity import IdentityBootstrap
from astra_identity.repositories import (
    SqlMembershipRepository,
    SqlOrganizationRepository,
    SqlPermissionRepository,
    SqlRolePermissionRepository,
    SqlRoleRepository,
    SqlTenantRepository,
)


@pytest.fixture()
def session_factory(tmp_path: Path):
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    db_file = tmp_path / "identity_bootstrap.db"
    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _counts(session_factory) -> dict[str, int]:
    with session_factory() as session:
        return {
            "tenant": len(SqlTenantRepository(session).list()),
            "org": len(SqlOrganizationRepository(session).list()),
            "role": len(SqlRoleRepository(session).list()),
            "permission": len(SqlPermissionRepository(session).list()),
            "role_permission": len(SqlRolePermissionRepository(session).list()),
            "membership": len(SqlMembershipRepository(session).list()),
        }


def test_bootstrap_creates_default_identity(session_factory) -> None:
    result = IdentityBootstrap(session_factory).ensure_default_identity()
    assert result.tenant.slug == "default"
    assert result.organization.slug == "default"
    assert result.admin_role.name == "admin"
    assert result.admin_permission.code == "*"


def test_bootstrap_is_idempotent(session_factory) -> None:
    bootstrap = IdentityBootstrap(session_factory)
    bootstrap.ensure_default_identity()
    first = _counts(session_factory)
    bootstrap.ensure_default_identity()
    second = _counts(session_factory)
    assert first == second
    assert first["tenant"] == 1
    assert first["org"] == 1
    assert first["role"] == 1
    assert first["permission"] == 1
    assert first["role_permission"] == 1


def test_bootstrap_with_admin_is_idempotent(session_factory) -> None:
    bootstrap = IdentityBootstrap(session_factory)
    first = bootstrap.ensure_default_identity(
        admin_username="admin",
        admin_email="admin@example.com",
        admin_password_hash="HASHED",
    )
    second = bootstrap.ensure_default_identity(
        admin_username="admin",
        admin_email="admin@example.com",
        admin_password_hash="HASHED",
    )
    assert first.admin_user is not None
    assert second.admin_user is not None
    assert first.admin_user.id == second.admin_user.id
    assert _counts(session_factory)["membership"] == 1
