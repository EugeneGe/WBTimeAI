"""``PermissionChecker`` 纯逻辑单测（deny-by-default / PEP / PDP / 枚举位）。"""

from __future__ import annotations

from astra_domain import ToolEffect, ToolPermission
from astra_tool import (
    GitTool,
    NoopPolicyDecisionPoint,
    NoopPolicyEnforcementPoint,
    PermissionChecker,
    PermissionRequest,
    PolicyDecisionPoint,
    PolicyEnforcementPoint,
    ShellTool,
    ToolContext,
)


def _git_checker(effect: str) -> PermissionChecker:
    return PermissionChecker(
        permissions=[ToolPermission(tool_id="tool-git", action="EXECUTE", effect=effect)],
        tool_id_to_name={"tool-git": "git"},
    )


def test_deny_by_default() -> None:
    checker = PermissionChecker()
    assert checker.check(ToolContext(), GitTool(), "EXECUTE") is ToolEffect.DENY


def test_explicit_allow() -> None:
    checker = _git_checker("ALLOW")
    assert checker.check(ToolContext(), GitTool(), "EXECUTE") is ToolEffect.ALLOW
    assert checker.is_allowed(ToolContext(), GitTool(), "EXECUTE") is True


def test_other_tool_still_denied() -> None:
    checker = _git_checker("ALLOW")
    assert checker.check(ToolContext(), ShellTool(), "EXECUTE") is ToolEffect.DENY


def test_explicit_deny() -> None:
    checker = _git_checker("DENY")
    assert checker.check(ToolContext(), GitTool(), "EXECUTE") is ToolEffect.DENY


def test_action_mapping_to_write() -> None:
    checker = PermissionChecker(
        permissions=[ToolPermission(tool_id="tool-git", action="WRITE", effect="ALLOW")],
        tool_id_to_name={"tool-git": "git"},
    )
    assert checker.check(ToolContext(), GitTool(), "WRITE") is ToolEffect.ALLOW
    assert checker.check(ToolContext(), GitTool(), "EXECUTE") is ToolEffect.DENY


def test_pep_hook_overrides() -> None:
    class DenyPep:
        def enforce(self, *, request: PermissionRequest) -> str:
            return ToolEffect.DENY.value

    checker = PermissionChecker(
        permissions=[ToolPermission(tool_id="tool-git", action="EXECUTE", effect="ALLOW")],
        tool_id_to_name={"tool-git": "git"},
        pep=DenyPep(),
    )
    assert checker.check(ToolContext(), GitTool(), "EXECUTE") is ToolEffect.DENY


def test_pdp_hook_overrides() -> None:
    class AllowPdp:
        def decide(self, *, request: PermissionRequest) -> str:
            return ToolEffect.ALLOW.value

    checker = PermissionChecker(pdp=AllowPdp())
    assert checker.check(ToolContext(), GitTool(), "EXECUTE") is ToolEffect.ALLOW


def test_hooks_are_protocols_and_assertable() -> None:
    checker = PermissionChecker()
    assert isinstance(checker.policy_enforcement_point, NoopPolicyEnforcementPoint)
    assert isinstance(checker.policy_enforcement_point, PolicyEnforcementPoint)
    assert isinstance(checker.policy_decision_point, NoopPolicyDecisionPoint)
    assert isinstance(checker.policy_decision_point, PolicyDecisionPoint)

    request = PermissionRequest(tool_name="git", action="EXECUTE", effect="ALLOW")
    assert checker.policy_decision_point.decide(request=request) is None
    assert checker.policy_enforcement_point.enforce(request=request) == "ALLOW"


def test_approval_is_reserved() -> None:
    assert ToolEffect.APPROVAL.value == "APPROVAL"
    assert "APPROVAL" not in ToolEffect.active_values()
