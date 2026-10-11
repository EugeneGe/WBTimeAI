"""``PriceProvider`` 契约（设计 §2.3.4）。

核心拥有成本金额的唯一计算与写入权；``PriceProvider`` 由核心发布静态价目目录，
扩展可实现新增 Provider 的价目来源（独立命名空间与版本，不得静默覆盖核心价目）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import PriceItem

__all__ = ["PriceProvider"]


@runtime_checkable
class PriceProvider(Protocol):
    """价目查询契约。"""

    def price(
        self,
        provider: str,
        model: str,
        *,
        price_version: str | None = None,
        currency: str | None = None,
    ) -> PriceItem | None:
        """查询某 ``provider`` / ``model`` 的有效价目项；无匹配返回 ``None``。

        Args:
            provider: 提供方标识。
            model: 模型名。
            price_version: 指定价目版本（``None`` 取当前有效版本）。
            currency: 指定币种（``None`` 不限币种）。

        Returns:
            匹配的 :class:`~astra_domain.value_objects.model.PriceItem` 或 ``None``。
        """
        ...
