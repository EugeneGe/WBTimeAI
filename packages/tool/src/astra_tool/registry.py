"""``ToolRegistry``（工具注册表，与 ``ModelRegistry`` 同构）。

以名称为键注册工具；重名注册默认覆盖（同名视为更新实现）。Phase 2 的 MCP Tool /
Connector 以**同一接口**注册（设计 §2.5.1 预留）。
"""

from __future__ import annotations

import builtins
from collections.abc import Iterator

from astra_core import DomainError, ErrorCode

from .base import Tool

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """工具注册表（按名注册 / 获取 / 列举）。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, tool: Tool, *, override: bool = True) -> None:
        """注册工具。

        Args:
            name: 工具名（唯一）。
            tool: 工具实例（满足 :class:`~astra_tool.base.Tool` Protocol）。
            override: 重名时是否覆盖（默认 ``True``）。

        Raises:
            DomainError: 重名且 ``override=False``（``CONFLICT``）。
        """
        if not override and name in self._tools:
            raise DomainError(f"工具已注册：{name}", code=ErrorCode.CONFLICT, data={"name": name})
        self._tools[name] = tool

    def unregister(self, name: str) -> None:
        """注销工具（幂等：名称不存在时静默返回）。"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        """按名获取工具。

        Raises:
            DomainError: 未注册（``NOT_FOUND``）。
        """
        try:
            return self._tools[name]
        except KeyError as exc:
            raise DomainError(
                f"工具未注册：{name}", code=ErrorCode.NOT_FOUND, data={"name": name}
            ) from exc

    def names(self) -> builtins.list[str]:
        """返回已注册工具名（排序）。"""
        return sorted(self._tools)

    def list(self) -> builtins.list[Tool]:
        """返回已注册工具（按名排序）。"""
        return [self._tools[name] for name in self.names()]

    def __contains__(self, name: object) -> bool:  # noqa: D105
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:  # noqa: D105
        return len(self._tools)

    def __iter__(self) -> Iterator[Tool]:  # noqa: D105
        return iter(self.list())
