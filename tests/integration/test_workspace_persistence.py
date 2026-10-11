"""Workspace 持久化往返集成测试（T0-17，SQLite）。

覆盖：创建 / 列表 / 更新设置往返；**跨租户不可见**；JSON ``settings`` / ``config`` 往返。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_workspace import SqlWorkspaceRepository, WorkspaceService

TENANT_A = "tenant-aaaa"
TENANT_B = "tenant-bbbb"


@pytest.fixture()
def service(session_factory) -> WorkspaceService:
    return WorkspaceService(session_factory)


def test_create_and_list_by_tenant(service: WorkspaceService) -> None:
    created = service.create(tenant_id=TENANT_A, owner_id="u1", name="Alice WS")
    listed = service.list_for_tenant(TENANT_A)
    assert [w.id for w in listed] == [created.id]
    assert listed[0].name == "Alice WS"
    assert listed[0].workspace_type == "personal"


def test_tenant_isolation(service: WorkspaceService) -> None:
    a = service.create(tenant_id=TENANT_A, owner_id="u1", name="A")
    service.create(tenant_id=TENANT_B, owner_id="u2", name="B")
    assert [w.id for w in service.list_for_tenant(TENANT_A)] == [a.id]
    assert len(service.list_for_tenant(TENANT_B)) == 1
    # 跨租户 get 不可见 → WORKSPACE_NOT_FOUND
    with pytest.raises(DomainError) as excinfo:
        service.get(a.id, tenant_id=TENANT_B)
    assert excinfo.value.code is ErrorCode.WORKSPACE_NOT_FOUND


def test_json_settings_and_config_roundtrip(service: WorkspaceService) -> None:
    created = service.create(
        tenant_id=TENANT_A,
        owner_id="u1",
        name="JSON WS",
        settings={"theme": "dark", "features": ["a", "b"], "nested": {"x": 1}},
        config={"model": "stub", "temperature": 0.3},
    )
    fetched = service.get(created.id, tenant_id=TENANT_A)
    assert fetched.settings == {"theme": "dark", "features": ["a", "b"], "nested": {"x": 1}}
    assert fetched.config == {"model": "stub", "temperature": 0.3}

    updated = service.update_settings(
        created.id, tenant_id=TENANT_A, settings={"theme": "light", "limit": 10}
    )
    assert updated.settings == {"theme": "light", "limit": 10}
    assert service.get(created.id, tenant_id=TENANT_A).settings == {"theme": "light", "limit": 10}


def test_invalid_workspace_type_rejected(service: WorkspaceService) -> None:
    with pytest.raises(DomainError) as excinfo:
        service.create(tenant_id=TENANT_A, owner_id="u1", name="bad", workspace_type="shared")
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_update_config_roundtrip(service: WorkspaceService) -> None:
    created = service.create(tenant_id=TENANT_A, owner_id="u1", name="cfg")
    updated = service.update_config(created.id, tenant_id=TENANT_A, config={"a": 1})
    assert updated.config == {"a": 1}


def test_repository_list_by_owner(service: WorkspaceService, session_factory) -> None:
    service.create(tenant_id=TENANT_A, owner_id="owner-1", name="one")
    service.create(tenant_id=TENANT_A, owner_id="owner-2", name="two")
    from astra_database import session_scope

    with session_scope(session_factory) as session:
        owned = SqlWorkspaceRepository(session).get_by_owner(TENANT_A, "owner-1")
    assert len(owned) == 1
    assert owned[0].owner_id == "owner-1"
