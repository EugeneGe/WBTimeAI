"""Capability 评估器（设计 §2.10.2；W3 裁定 §4；T2-13 建立，T2-14 扩充）。

本模块承载 **scope 语法与匹配算法**（W3 裁定 §4.2）中**与语义无关的匹配原语**：

- :func:`matches_capability_pattern`：单 pattern 匹配（精确 / 族通配 ``git.*`` / ``*``）；
- :func:`capability_matches_any`：集合匹配；
- :func:`granted_capabilities` / :func:`denied_capabilities`：从 ``PermissionScope``（对象）
  或其 JSON 字典承载中抽取 ``capabilities`` / ``deny``；
- :func:`capability_is_escalation`：判定「实例级声明的 capability 是否为主体级未授予」
  （越权声明 → 无效）。

🔴 T2-14 在本模块**追加**「有效 capability 集计算」与 ``DEFAULT_DENY_CAPABILITIES`` 接入
   （词汇表落 ``astra_domain/capability.py``）；本文件零 Web / ORM。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from astra_domain import DEFAULT_DENY_CAPABILITIES, all_capabilities

__all__ = [
    "WILDCARD",
    "matches_capability_pattern",
    "capability_matches_any",
    "granted_capabilities",
    "denied_capabilities",
    "capability_is_escalation",
    "match_capability",
    "effective_capabilities",
]

#: 全量通配符（仅核心 ``ALLOW`` 可授予；实例级不得放开）。
WILDCARD = "*"

#: 族通配后缀（``git.*``）。
_FAMILY_SUFFIX = ".*"


def matches_capability_pattern(capability: str, pattern: str) -> bool:
    """判断 ``capability`` 是否命中单 pattern。

    Args:
        capability: 具体 capability（如 ``git.commit``）。
        pattern: 模式（精确 ``git.commit`` / 族通配 ``git.*`` / 全通配 ``*``）。

    Returns:
        是否命中。
    """
    if pattern == WILDCARD:
        return True
    if pattern == capability:
        return True
    if pattern.endswith(_FAMILY_SUFFIX):
        # ``git.*`` → 前缀 ``git.``（仅匹配同族，不误伤 ``github.*``）。
        return capability.startswith(pattern[: -len(WILDCARD)])
    return False


def capability_matches_any(capability: str, patterns: Iterable[str]) -> bool:
    """判断 ``capability`` 是否命中 patterns 中任意一项。"""
    return any(matches_capability_pattern(capability, pattern) for pattern in patterns)


def _scope_values(scope: Any, key: str) -> list[str]:
    """从 ``PermissionScope`` 对象或 JSON 字典抽取字符串列表（缺省空）。"""
    if scope is None:
        return []
    if isinstance(scope, dict):
        raw = scope.get(key) or []
    else:
        raw = getattr(scope, key, None) or []
    return [str(value) for value in raw]


def granted_capabilities(scope: Any) -> list[str]:
    """抽取 scope 的 ``capabilities``（授予集）。"""
    return _scope_values(scope, "capabilities")


def denied_capabilities(scope: Any) -> list[str]:
    """抽取 scope 的 ``deny``（拒绝集）。"""
    return _scope_values(scope, "deny")


def capability_is_escalation(capability: str, *, granted: Iterable[str]) -> bool:
    """判定「实例级声明的 capability 是否为主体级未授予」（越权声明 → 无效）。

    Args:
        capability: 实例级声明的 capability。
        granted: 主体级已授予的 capability patterns。

    Returns:
        为真表示该声明**超出**主体级授权范围（应无效化 + 记审计）。
    """
    return not capability_matches_any(capability, granted)


def match_capability(
    capability: str,
    *,
    declared: Iterable[str],
    denied: Iterable[str],
    default_deny: Iterable[str] = DEFAULT_DENY_CAPABILITIES,
) -> bool:
    """按 W3 裁定 §4.2 **冻结算法**判定单 capability 是否放行（**deny 优先**）。

    1. ``capability`` 命中 ``denied``（支持族通配）→ **拒绝**（deny 优先）；
    2. ``capability ∈ default_deny`` 且**未被显式字面授予**（``capability not in declared``）→
       **拒绝**（默认 deny，须**显式 allow**；族通配 ``git.*`` / ``*`` **不**隐式放行高危项）；
    3. ``capability`` 命中 ``declared``（含族通配 ``git.*`` / ``*``）→ **放行**；
    4. 否则 **拒绝**（deny-by-default）。
    """
    denied_patterns = list(denied)
    declared_patterns = list(declared)
    if capability_matches_any(capability, denied_patterns):
        return False
    if capability in set(default_deny) and capability not in set(declared_patterns):
        return False
    return capability_matches_any(capability, declared_patterns)


def _expand(patterns: Iterable[str]) -> set[str]:
    """展开 capability patterns 为具体 capability 集（族通配 / ``*``）。"""
    known = all_capabilities()
    result: set[str] = set()
    for pattern in patterns:
        if pattern == WILDCARD:
            result |= set(known)
        elif pattern.endswith(_FAMILY_SUFFIX):
            result |= {cap for cap in known if matches_capability_pattern(cap, pattern)}
        else:
            result.add(pattern)
    return result


def effective_capabilities(
    *,
    declared: Iterable[str],
    denied: Iterable[str],
    subject_granted: Iterable[str] = (),
    default_deny: Iterable[str] = DEFAULT_DENY_CAPABILITIES,
) -> frozenset[str]:
    """计算**有效 capability 集**（后端下发；W3 裁定 §4.2）。

    ``effective = (scope.capabilities 展开 ∪ 主体级 ALLOW) − scope.deny − 未显式 allow 的
    default-deny 项``。
    """
    declared_patterns = list(declared)
    effective = _expand(declared_patterns)
    effective |= {str(cap) for cap in subject_granted}
    effective -= _expand(denied)
    effective -= {cap for cap in set(default_deny) if cap not in set(declared_patterns)}
    return frozenset(effective)
