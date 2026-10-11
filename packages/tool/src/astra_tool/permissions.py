"""首批 5 个 Tool 的默认权限定义（设计 §2.5.2 / §2.5.3）。

- 权限码粒度：``tool:<name>.<action>``（如 ``tool:git.commit``）；
- 默认动作映射：资源 ``TOOL`` × 动作（``EXECUTE`` / ``READ`` / ``WRITE``）；
- :func:`resolve_permission_scope` 把 ``agent_tool.permission_scope``（JSON）解析为
  :class:`~astra_domain.value_objects.tool.PermissionScope`。

🔴 纯逻辑（零 ORM、零框架）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from astra_domain import (
    TOOL_ACTION_EXECUTE,
    TOOL_ACTION_READ,
    TOOL_ACTION_WRITE,
    PermissionScope,
)

from .base import ToolPermissionRequirement

__all__ = [
    "TOOL_PERMISSION_MATRIX",
    "permission_code",
    "default_permission",
    "tool_actions",
    "resolve_permission_scope",
]


def _req(action: str) -> ToolPermissionRequirement:
    """构造默认权限要求（资源 TOOL × 指定动作）。"""
    return ToolPermissionRequirement(action=action)


#: 首批 5 Tool 的（工具名 → 动作 → 默认权限要求）矩阵。
TOOL_PERMISSION_MATRIX: dict[str, dict[str, ToolPermissionRequirement]] = {
    "filesystem": {
        "read": _req(TOOL_ACTION_READ),
        "list": _req(TOOL_ACTION_READ),
        "write": _req(TOOL_ACTION_WRITE),
        "delete": _req(TOOL_ACTION_WRITE),
    },
    "shell": {
        "execute": _req(TOOL_ACTION_EXECUTE),
    },
    "git": {
        "clone": _req(TOOL_ACTION_WRITE),
        "status": _req(TOOL_ACTION_READ),
        "diff": _req(TOOL_ACTION_READ),
        "commit": _req(TOOL_ACTION_WRITE),
        "branch": _req(TOOL_ACTION_WRITE),
    },
    "http": {
        "request": _req(TOOL_ACTION_EXECUTE),
    },
    "python": {
        "run": _req(TOOL_ACTION_EXECUTE),
    },
}


def permission_code(tool_name: str, action: str) -> str:
    """返回权限码 ``tool:<name>.<action>``（设计 §2.5.3）。"""
    return f"tool:{tool_name}.{str(action).lower()}"


def default_permission(tool_name: str, action: str) -> ToolPermissionRequirement:
    """返回某工具某动作的默认权限要求（未声明动作回退 ``EXECUTE``）。"""
    actions = TOOL_PERMISSION_MATRIX.get(tool_name, {})
    requirement = actions.get(str(action).lower())
    if requirement is not None:
        return requirement
    return _req(TOOL_ACTION_EXECUTE)


def tool_actions(tool_name: str) -> tuple[str, ...]:
    """返回某工具声明的全部动作（顺序稳定）。"""
    return tuple(TOOL_PERMISSION_MATRIX.get(tool_name, {}))


def resolve_permission_scope(raw: Mapping[str, Any] | None) -> PermissionScope:
    """把 ``agent_tool.permission_scope``（JSON 结构）解析为 :class:`PermissionScope`。"""
    if not raw:
        return PermissionScope()
    return PermissionScope.from_dict(dict(raw))
