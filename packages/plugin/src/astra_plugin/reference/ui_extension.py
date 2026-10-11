"""``ui_extension`` 参考实现：:class:`EmptyUIExtension`（无插槽、无资源）。"""

from __future__ import annotations

from astra_domain import UISlot

__all__ = ["EmptyUIExtension"]


class EmptyUIExtension:
    """空 UI 扩展（无插槽 / 无外部资源）。"""

    def slots(self) -> list[UISlot]:
        """无插槽。"""
        return []

    def assets_base_url(self) -> str:
        """无外部资源基址。"""
        return ""
