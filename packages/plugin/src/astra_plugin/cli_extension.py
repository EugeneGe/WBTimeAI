"""CLI 扩展命令冲突检测（设计 §2.14；W1b 裁定 §3.4）。

- :data:`RESERVED_CORE_COMMANDS`：核心命令**保留键**（``("", "init")`` /
  ``("", "run")`` / ``("", "doctor")``）——插件**不得**占用；
- :class:`PluginCLICommand`：插件上报的 CLI 命令（装载期登记项）；
- :class:`CLICommandIndex`：``(group, command)`` → 所属插件 的所有权索引，
  冲突 → ``DomainError(CONFLICT)``（含冲突插件名，**不静默覆盖**）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from astra_core import DomainError, ErrorCode

__all__ = [
    "RESERVED_CORE_COMMANDS",
    "CORE_PLUGIN_LABEL",
    "PluginCLICommand",
    "CLICommandIndex",
]

#: 核心命令保留键（分组为空 = 顶级核心命令）。
RESERVED_CORE_COMMANDS: Final[frozenset[tuple[str, str]]] = frozenset(
    {("", "init"), ("", "run"), ("", "doctor")}
)

#: 保留键的既有占用者标签。
CORE_PLUGIN_LABEL: Final[str] = "<core>"


@dataclass(frozen=True)
class PluginCLICommand:
    """插件上报的一条 CLI 命令（装载期登记项）。

    Attributes:
        group: 命令分组（``astra <group> <command>``）。
        command: 命令名。
        plugin_name: 上报插件名（冲突诊断用）。
        spec: CLI 命令声明（``astra_cli.registry.CLICommandSpec``；此处以 ``object`` 承载）。
        handler: 处理函数端点。
    """

    group: str
    command: str
    plugin_name: str
    spec: object
    handler: Callable[..., Any]


class CLICommandIndex:
    """``(group, command)`` 所有权索引 + 冲突检测。

    Args:
        reserved: 保留键集合（默认 :data:`RESERVED_CORE_COMMANDS`）。
    """

    def __init__(self, reserved: frozenset[tuple[str, str]] = RESERVED_CORE_COMMANDS) -> None:
        self._reserved = reserved
        self._owners: dict[tuple[str, str], str] = {key: CORE_PLUGIN_LABEL for key in reserved}

    def conflict(self, group: str, command: str) -> bool:
        """键是否已被占用（含核心保留键）。"""
        return (group, command) in self._owners

    def owner(self, group: str, command: str) -> str:
        """返回键的既有占用者（核心保留键为 ``"<core>"``；未占用为空串）。"""
        return self._owners.get((group, command), "")

    def set_owner(self, group: str, command: str, plugin_name: str) -> None:
        """登记所有权（**不**做冲突检测，由调用方先行检测）。"""
        self._owners[(group, command)] = plugin_name

    def release(self, group: str, command: str) -> None:
        """释放所有权（保留键不可释放）。"""
        if (group, command) in self._reserved:
            return
        self._owners.pop((group, command), None)

    def raise_conflict(self, group: str, command: str, incoming_plugin: str) -> None:
        """抛出命令冲突错误（键 + 既有 / 新入插件名，**不静默覆盖**）。"""
        existing = self.owner(group, command) or "<unknown>"
        raise DomainError(
            f"CLI 命令冲突：{group} {command}（已由 {existing} 注册，"
            f"插件 {incoming_plugin} 不得占用）",
            code=ErrorCode.CONFLICT,
            data={
                "group": group,
                "command": command,
                "existing_plugin": existing,
                "incoming_plugin": incoming_plugin,
            },
        )
