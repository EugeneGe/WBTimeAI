"""Tool 组值对象（设计 §2.5 / §2.5.3）。

纯标准库实现（零框架依赖，C-03）：

- :class:`ToolAction`：``EXECUTE`` / ``READ`` / ``WRITE``；
- :class:`ToolEffect`：``ALLOW`` / ``DENY``（``APPROVAL`` 为 Phase 3 预留位）；
- :class:`PermissionScope`：``agent_tool.permission_scope`` 的结构化承载。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from astra_core import ValidationError

from ..constants import (
    TOOL_ACTION_EXECUTE,
    TOOL_ACTION_READ,
    TOOL_ACTION_WRITE,
    TOOL_EFFECT_ALLOW,
    TOOL_EFFECT_APPROVAL,
    TOOL_EFFECT_DENY,
)

__all__ = ["ToolAction", "ToolEffect", "PermissionScope"]


def _ensure_value(enum_cls: type[StrEnum], value: Any, *, field_name: str) -> Any:
    """校验并归一化字符串枚举取值。"""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise ValidationError(
            f"{field_name} 取值非法",
            data={"field": field_name, "value": str(value)},
        ) from exc


class ToolAction(StrEnum):
    """工具动作（资源 ``TOOL`` × 动作，设计 §2.5.3）。"""

    EXECUTE = TOOL_ACTION_EXECUTE
    READ = TOOL_ACTION_READ
    WRITE = TOOL_ACTION_WRITE

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | ToolAction) -> ToolAction:
        """校验并归一化工具动作。"""
        return _ensure_value(cls, value, field_name="tool_action")


class ToolEffect(StrEnum):
    """权限效果（``APPROVAL`` 为 Phase 3 预留，本期恒 ``ALLOW`` / ``DENY``）。"""

    ALLOW = TOOL_EFFECT_ALLOW
    DENY = TOOL_EFFECT_DENY
    APPROVAL = TOOL_EFFECT_APPROVAL  # 预留位（Phase 3）

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值（含预留 ``APPROVAL``）。"""
        return tuple(member.value for member in cls)

    @classmethod
    def active_values(cls) -> tuple[str, ...]:
        """返回本期生效字面值（不含预留 ``APPROVAL``）。"""
        return (cls.ALLOW.value, cls.DENY.value)

    @classmethod
    def ensure(cls, value: str | ToolEffect) -> ToolEffect:
        """校验并归一化权限效果。"""
        return _ensure_value(cls, value, field_name="tool_effect")


@dataclass
class PermissionScope:
    """``agent_tool.permission_scope`` 的结构化承载（设计 §2.4 / §2.10.2）。

    Attributes:
        paths: 允许访问的路径白名单。
        commands: 允许执行的命令白名单。
        allow: 显式允许项。
        deny: 显式拒绝项。
        capabilities: 受控 capability 集（W3 裁定 §4.2；``{capabilities, deny, ...}``）。
            **向后兼容**：旧 JSON 无该键时取空列表。
    """

    paths: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可落 JSON 列的字典。

        最终 scope JSON ＝ ``{capabilities, deny, paths, commands, allow}``。
        """
        return {
            "capabilities": list(self.capabilities),
            "deny": list(self.deny),
            "paths": list(self.paths),
            "commands": list(self.commands),
            "allow": list(self.allow),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PermissionScope:
        """由字典构造（缺省字段为空列表；旧 JSON 无 ``capabilities`` → 空）。"""
        return cls(
            paths=list(data.get("paths") or []),
            commands=list(data.get("commands") or []),
            allow=list(data.get("allow") or []),
            deny=list(data.get("deny") or []),
            capabilities=list(data.get("capabilities") or []),
        )
