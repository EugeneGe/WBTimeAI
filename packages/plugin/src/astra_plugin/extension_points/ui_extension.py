"""ExtensionPoint ⑧ ``ui_extension``（前端扩展点）——签名冻结（W1b 裁定 §1.3⑧）。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import UISlot

__all__ = ["UIExtension", "EXTENSION_POINT_VERSION"]

#: 扩展点版本（格式 ``<point>/vN``）。
EXTENSION_POINT_VERSION: str = "ui_extension/v1"


@runtime_checkable
class UIExtension(Protocol):
    """前端扩展点（插槽声明 + 静态资源基址）。"""

    def slots(self) -> list[UISlot]:
        """声明 UI 插槽清单。"""
        ...

    def assets_base_url(self) -> str:
        """静态资源基址（空串表示无外部资源）。"""
        ...
