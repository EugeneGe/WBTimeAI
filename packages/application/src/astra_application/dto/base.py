"""DTO 基座：数据传输对象 + 分页。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

__all__ = ["DTO", "Pagination", "Page"]

T = TypeVar("T")


@dataclass
class DTO:
    """数据传输对象基类（纯 dataclass，无框架依赖）。"""


@dataclass
class Pagination:
    """分页参数。

    Attributes:
        page: 页码（从 1 开始）。
        page_size: 每页数量。
    """

    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        """计算偏移量。"""
        return max(self.page - 1, 0) * self.page_size

    @property
    def limit(self) -> int:
        """计算 limit。"""
        return self.page_size


@dataclass
class Page(DTO, Generic[T]):
    """分页结果。

    Attributes:
        items: 当前页条目。
        total: 总条目数。
        page: 当前页码。
        page_size: 每页数量。
    """

    items: list[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20

    @property
    def pages(self) -> int:
        """总页数（向上取整）。"""
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size
