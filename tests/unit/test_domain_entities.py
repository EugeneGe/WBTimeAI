"""领域实体默认值与约定单测（决策 D2：ID 来自 ``generate_id``）。"""

from __future__ import annotations

from datetime import UTC

from astra_domain import (
    DEFAULT_TENANT_SLUG,
    Membership,
    Organization,
    Permission,
    Role,
    Tenant,
    User,
)


def _is_uuid_v7(value: str) -> bool:
    # 形如 xxxxxxxx-xxxx-7xxx-xxxx-xxxxxxxxxxxx（第 3 组以 7 开头）。
    parts = value.split("-")
    return len(parts) == 5 and parts[2][0] == "7"


def test_entity_id_defaults_to_generate_id() -> None:
    tenant = Tenant()
    assert _is_uuid_v7(tenant.id)
    assert Tenant().id != Tenant().id


def test_entity_timestamps_are_utc_aware() -> None:
    tenant = Tenant()
    assert tenant.created_at.tzinfo is not None
    assert tenant.updated_at.tzinfo is not None
    assert tenant.created_at.utcoffset() == UTC.utcoffset(None)


def test_tenant_defaults() -> None:
    tenant = Tenant()
    assert tenant.slug == DEFAULT_TENANT_SLUG
    assert tenant.tenant_id is None
    assert tenant.is_active is True


def test_user_fields_and_tenant_scope() -> None:
    user = User(tenant_id="t-1", username="alice", email="a@example.com", password_hash="HASH")
    assert user.tenant_id == "t-1"
    assert user.username == "alice"
    assert user.password_hash == "HASH"
    assert user.is_active is True
    assert user.is_superuser is False


def test_other_entities_defaults() -> None:
    org = Organization(tenant_id="t-1")
    assert org.slug == "default"
    membership = Membership(tenant_id="t-1", user_id="u-1")
    assert membership.status == "active"
    role = Role(tenant_id="t-1", name="admin", is_system=True)
    assert role.is_system is True
    permission = Permission(code="*", name="all")
    assert permission.tenant_id is None
