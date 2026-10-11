"""Capability 词汇表与 scope 匹配单元测试（W3 / T2-14；验收 ``I-P2-14``）。

覆盖：

- 受控词汇表常量 / ``DEFAULT_DENY_CAPABILITIES`` / ``capability_family`` / ``is_known_capability``；
- ``PermissionScope.capabilities`` 字段（向后兼容：旧 JSON 无该键 → 空）；
- ``match_capability``（**deny 优先** / 默认 deny 须显式 allow / 族通配）；
- ``effective_capabilities`` 有效集计算；
- ``Principal.claims`` 预留 ``capabilities`` 键（Phase 3 留位）。
"""

from __future__ import annotations

from astra_domain import (
    CAPABILITY_DB_DROP,
    CAPABILITY_FAMILIES,
    CAPABILITY_FS_WRITE,
    CAPABILITY_FS_WRITE_OUTSIDE,
    CAPABILITY_GIT_COMMIT,
    CAPABILITY_GIT_FORCE_PUSH,
    CAPABILITY_GIT_PUSH,
    DEFAULT_DENY_CAPABILITIES,
    MCP_CAPABILITY_PREFIX,
    PermissionScope,
    Principal,
    all_capabilities,
    capability_family,
    is_known_capability,
    mcp_capability,
)
from astra_security import (
    WILDCARD,
    capability_is_escalation,
    capability_matches_any,
    effective_capabilities,
    match_capability,
    matches_capability_pattern,
)


def test_default_deny_capabilities_membership() -> None:
    """默认拒绝集含高危 capability。"""
    assert CAPABILITY_FS_WRITE_OUTSIDE in DEFAULT_DENY_CAPABILITIES
    assert CAPABILITY_DB_DROP in DEFAULT_DENY_CAPABILITIES
    assert CAPABILITY_GIT_FORCE_PUSH in DEFAULT_DENY_CAPABILITIES


def test_all_capabilities_union() -> None:
    """``all_capabilities`` 为各族的并集。"""
    union: set[str] = set()
    for members in CAPABILITY_FAMILIES.values():
        union.update(members)
    assert all_capabilities() == frozenset(union)
    assert CAPABILITY_GIT_COMMIT in all_capabilities()


def test_capability_family() -> None:
    """族解析：``git.commit`` → ``git``；``mcp:x.y`` → ``mcp``；未知 → ``None``。"""
    assert capability_family(CAPABILITY_GIT_COMMIT) == "git"
    assert capability_family("mcp:github.search") == "mcp"
    assert capability_family("unknown.thing") is None


def test_is_known_capability() -> None:
    """已知项判定（含动态 ``mcp:`` 命名空间）。"""
    assert is_known_capability(CAPABILITY_GIT_PUSH) is True
    assert is_known_capability(mcp_capability("github", "search")) is True
    assert is_known_capability("nope.nope") is False


def test_matches_capability_pattern() -> None:
    """模式匹配：精确 / 族通配 / 全通配。"""
    assert matches_capability_pattern("git.commit", "git.commit") is True
    assert matches_capability_pattern("git.commit", "git.*") is True
    assert matches_capability_pattern("git.commit", WILDCARD) is True
    assert matches_capability_pattern("github.x", "git.*") is False


def test_match_capability_deny_priority() -> None:
    """``match_capability``：deny 优先于 declared。"""
    assert match_capability("git.push", declared=["git.push"], denied=["git.*"]) is False


def test_match_capability_default_deny_requires_explicit_allow() -> None:
    """默认 deny capability 须显式 allow 才放行。"""
    assert match_capability(CAPABILITY_DB_DROP, declared=[], denied=[]) is False
    assert match_capability(CAPABILITY_DB_DROP, declared=[CAPABILITY_DB_DROP], denied=[]) is True


def test_match_capability_family_wildcard_and_default_deny() -> None:
    """族通配 ``git.*`` 授予普通项，但不放行默认 deny 的 ``git.force_push``（除非显式）。"""
    assert match_capability(CAPABILITY_GIT_COMMIT, declared=["git.*"], denied=[]) is True
    assert match_capability(CAPABILITY_GIT_FORCE_PUSH, declared=["git.*"], denied=[]) is False
    assert (
        match_capability(CAPABILITY_GIT_FORCE_PUSH, declared=["git.force_push"], denied=[]) is True
    )


def test_capability_is_escalation() -> None:
    """越权判定：声明超出主体级授予 → 越权。"""
    assert capability_is_escalation("git.push", granted=["git.commit"]) is True
    assert capability_is_escalation("git.commit", granted=["git.commit"]) is False


def test_effective_capabilities_excludes_denied_and_default_deny() -> None:
    """有效集 ＝ (declared ∪ subject) − deny − 未显式 allow 的 default-deny。"""
    effective = effective_capabilities(
        declared=["git.*", CAPABILITY_FS_WRITE],
        denied=["git.push"],
        subject_granted=[CAPABILITY_GIT_COMMIT],
    )
    assert CAPABILITY_GIT_COMMIT in effective
    assert CAPABILITY_FS_WRITE in effective
    assert CAPABILITY_GIT_PUSH not in effective  # 显式 deny
    assert CAPABILITY_DB_DROP not in effective  # 默认 deny（未显式 allow）


def test_capability_matches_any() -> None:
    """集合匹配。"""
    assert capability_matches_any("git.commit", ["fs.*", "git.commit"]) is True
    assert capability_matches_any("git.commit", ["fs.*"]) is False


def test_permission_scope_capabilities_roundtrip() -> None:
    """``PermissionScope`` 增 ``capabilities`` 字段；``to_dict`` / ``from_dict`` 往返一致。"""
    scope = PermissionScope(
        paths=["/workspace"],
        commands=["ls"],
        allow=["x"],
        deny=["git.push"],
        capabilities=["git.commit"],
    )
    payload = scope.to_dict()
    assert payload["capabilities"] == ["git.commit"]
    restored = PermissionScope.from_dict(payload)
    assert restored.capabilities == ["git.commit"]
    assert restored.deny == ["git.push"]


def test_permission_scope_backward_compatible_old_json() -> None:
    """旧 JSON（无 ``capabilities`` 键）→ 取默认空列表（向后兼容）。"""
    restored = PermissionScope.from_dict({"paths": ["/a"], "deny": ["db.drop"]})
    assert restored.capabilities == []
    assert restored.paths == ["/a"]


def test_principal_claims_reserves_capabilities() -> None:
    """``Principal.claims`` 预留 ``capabilities`` 键（Phase 3 留位，W3 裁定 §4.2）。"""
    principal = Principal(
        subject_id="u-1",
        tenant_id="t-1",
        kind="user",
        claims={"capabilities": ["git.commit"]},
    )
    assert principal.claims["capabilities"] == ["git.commit"]
    assert MCP_CAPABILITY_PREFIX == "mcp:"
