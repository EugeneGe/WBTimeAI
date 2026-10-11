"""命令（Command）基座。

命令表示「改变系统状态」的意图；由 :class:`CommandHandler` 处理。
Phase 0 采用同步处理（无内建异步分发），保持简洁可测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

__all__ = ["Command", "CommandHandler", "CommandResultT"]

CommandResultT = TypeVar("CommandResultT", covariant=True)


@dataclass
class Command:
    """命令基类（不可变语义由使用方约定）。"""


@runtime_checkable
class CommandHandler(Protocol[CommandResultT]):
    """命令处理器 Protocol。"""

    def handle(self, command: Any) -> CommandResultT:
        """处理命令并返回结果。"""
        ...
