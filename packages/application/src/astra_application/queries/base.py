"""查询（Query）基座。

查询表示「读取系统状态」的意图；由 :class:`QueryHandler` 处理，不产生副作用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

__all__ = ["Query", "QueryHandler", "QueryResultT"]

QueryResultT = TypeVar("QueryResultT", covariant=True)


@dataclass
class Query:
    """查询基类。"""


@runtime_checkable
class QueryHandler(Protocol[QueryResultT]):
    """查询处理器 Protocol。"""

    def handle(self, query: Any) -> QueryResultT:
        """处理查询并返回结果。"""
        ...
