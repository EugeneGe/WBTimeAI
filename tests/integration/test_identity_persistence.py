"""Identity 持久化往返集成测试（SQLite）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from astra_database import Base, create_session_factory
from astra_domain import User
from astra_identity import (
    IdentityBootstrap,
    RoleService,
    SqlUserRepository,
    TenantService,
    UserService,
)


@pytest.fixture()
def session_factory(tmp_path: Path):
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    db_file = tmp_path / "identity_persistence.db"
    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def test_tenant_service_roundtrip(session_factory) -> None:
    service = TenantService(session_factory)
    created = service.ensure_tenant("acme", "Acme")
    fetched = service.get_by_slug("acme")
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Acme"


def test_user_service_roundtrip(session_factory) -> None:
    tenant = TenantService(session_factory).ensure_default()
    users = UserService(session_factory)
    user = users.ensure_user(
        tenant_id=tenant.id,
        username="alice",
        email="alice@example.com",
        password_hash="HASH",
    )
    fetched = users.get_by_username(tenant.id, "alice")
    assert fetched is not None
    assert fetched.id == user.id
    assert users.get_by_email(tenant.id, "alice@example.com").id == user.id


def test_repository_roundtrip_and_bootstrap(session_factory) -> None:
    result = IdentityBootstrap(session_factory).ensure_default_identity()
    with session_factory() as session:
        repo = SqlUserRepository(session)
        user = repo.add(
            User(
                tenant_id=result.tenant.id,
                username="root",
                email="root@example.com",
                password_hash="HASH",
            )
        )
        assert repo.get(user.id) is not None
        assert repo.get_by_username(result.tenant.id, "root").id == user.id


def test_role_service_links_admin_permission(session_factory) -> None:
    tenant = TenantService(session_factory).ensure_default()
    roles = RoleService(session_factory)
    role = roles.ensure_admin_role(tenant.id)
    permission = roles.ensure_admin_permission()
    roles.ensure_role_permission(role.id, permission.id)
    permissions = roles.list_permissions_for_role(role.id)
    assert [p.code for p in permissions] == ["*"]
