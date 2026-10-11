"""首批内置工具汇总 + ``register_builtin_tools``。

首批 5 个 Tool（设计 §2.5.2）：``filesystem`` / ``shell`` / ``git`` / ``http`` / ``python``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .filesystem import FilesystemTool
from .git import GitTool
from .http import HttpTool
from .python import PythonTool
from .shell import ShellTool

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from ..registry import ToolRegistry

__all__ = [
    "FilesystemTool",
    "ShellTool",
    "GitTool",
    "HttpTool",
    "PythonTool",
    "BUILTIN_TOOL_CLASSES",
    "register_builtin_tools",
]

#: 首批内置工具类（顺序稳定，与设计 §2.5.2 一致）。
BUILTIN_TOOL_CLASSES: tuple[type, ...] = (
    FilesystemTool,
    ShellTool,
    GitTool,
    HttpTool,
    PythonTool,
)


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    """把首批内置工具注册进 ``registry``（同名覆盖）。"""
    for tool_class in BUILTIN_TOOL_CLASSES:
        tool = tool_class()
        registry.register(tool.spec.metadata.name, tool)
    return registry
