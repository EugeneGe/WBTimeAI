"""Conversation / Tool 组值对象单测（设计 §2.6 / §2.5.3）。"""

from __future__ import annotations

import pytest
from astra_core import ValidationError
from astra_domain import (
    MessageRole,
    PermissionScope,
    RunMode,
    RunStatus,
    SandboxProviderKind,
    SandboxSessionStatus,
    ToolAction,
    ToolCallStatus,
    ToolEffect,
)


def test_run_status_terminal_judgement() -> None:
    assert RunStatus.SUCCESS.is_terminal() is True
    assert RunStatus.FAILED.is_terminal() is True
    assert RunStatus.CANCELLED.is_terminal() is True
    assert RunStatus.PENDING.is_terminal() is False
    assert RunStatus.RUNNING.is_terminal() is False


def test_run_status_terminal_value_helper() -> None:
    assert RunStatus.is_terminal_value("SUCCESS") is True
    assert RunStatus.is_terminal_value("RUNNING") is False
    with pytest.raises(ValidationError):
        RunStatus.is_terminal_value("NOPE")
    assert set(RunStatus.terminal_values()) == {"SUCCESS", "FAILED", "CANCELLED"}
    assert set(RunStatus.non_terminal_values()) == {"PENDING", "RUNNING"}


def test_message_role_values() -> None:
    assert set(MessageRole.values()) == {"system", "user", "assistant", "tool"}
    assert MessageRole.ensure("assistant") is MessageRole.ASSISTANT
    with pytest.raises(ValidationError):
        MessageRole.ensure("human")


def test_tool_call_status_values() -> None:
    assert set(ToolCallStatus.values()) == {
        "PENDING",
        "RUNNING",
        "SUCCESS",
        "FAILED",
        "DENIED",
    }


def test_run_mode_values() -> None:
    assert set(RunMode.values()) == {"INLINE", "QUEUED"}


def test_tool_action_and_effect_reserved_approval() -> None:
    assert set(ToolAction.values()) == {"EXECUTE", "READ", "WRITE"}
    # ToolEffect 预留 APPROVAL（Phase 3），本期生效值为 ALLOW / DENY。
    assert "APPROVAL" in ToolEffect.values()
    assert set(ToolEffect.active_values()) == {"ALLOW", "DENY"}


def test_permission_scope_roundtrip() -> None:
    scope = PermissionScope(paths=["/ws/a"], commands=["git commit"], allow=["read"], deny=["rm"])
    restored = PermissionScope.from_dict(scope.to_dict())
    assert restored.paths == ["/ws/a"]
    assert restored.deny == ["rm"]


def test_sandbox_values() -> None:
    assert set(SandboxProviderKind.values()) == {"docker", "local_process"}
    assert set(SandboxSessionStatus.values()) == {"CREATED", "RUNNING", "STOPPED", "FAILED"}
