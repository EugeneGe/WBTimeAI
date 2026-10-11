"""``Workspace`` 实体与 ``WorkspaceType`` 值对象单测（T0-17）。"""

from __future__ import annotations

from datetime import UTC

import pytest
from astra_core import ValidationError
from astra_domain import (
    WORKSPACE_TYPE_PERSONAL,
    WORKSPACE_TYPE_TEAM,
    Workspace,
    WorkspaceType,
)


def test_workspace_defaults_use_unique_id_and_utc_timestamps() -> None:
    workspace = Workspace(owner_id="user-1", name="个人工作区")
    assert workspace.id  # 默认经 generate_id（UUIDv7）
    assert len(workspace.id) == 36
    assert workspace.tenant_id is None
    assert workspace.workspace_type == WORKSPACE_TYPE_PERSONAL
    assert workspace.settings == {}
    assert workspace.config == {}
    assert workspace.created_at.tzinfo is not None
    assert workspace.updated_at.tzinfo is not None


def test_workspace_ids_are_unique() -> None:
    first = Workspace(name="a")
    second = Workspace(name="b")
    assert first.id != second.id


def test_workspace_touch_refreshes_updated_at() -> None:
    workspace = Workspace(name="a")
    original = workspace.updated_at
    workspace.touch()
    assert workspace.updated_at >= original
    assert workspace.updated_at.tzinfo is not None
    assert workspace.updated_at.astimezone(UTC) is not None


def test_workspace_type_values() -> None:
    assert WorkspaceType.PERSONAL == WORKSPACE_TYPE_PERSONAL
    assert WorkspaceType.TEAM == WORKSPACE_TYPE_TEAM
    assert WorkspaceType.values() == ("personal", "team")


def test_workspace_type_ensure_accepts_valid_and_rejects_invalid() -> None:
    assert WorkspaceType.ensure("personal") is WorkspaceType.PERSONAL
    assert WorkspaceType.ensure("team") is WorkspaceType.TEAM
    assert WorkspaceType.ensure(WorkspaceType.TEAM) is WorkspaceType.TEAM
    with pytest.raises(ValidationError):
        WorkspaceType.ensure("shared")
