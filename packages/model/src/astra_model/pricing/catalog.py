"""版本化静态价目目录（随核心发布；设计 §2.3.4）。

- :class:`StaticPriceCatalog`：不可变叠加式的价目集合，校验「同一模型同一时段
  仅一个有效项」；
- :func:`build_default_price_catalog`：核心随版本发布的默认价目目录。

🔴 无匹配价目时 :meth:`StaticPriceCatalog.price` 返回 ``None``（由 ``CostCalculator``
   记为 ``cost_status=UNPRICED``，**不得记零金额冒充免费**）。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from decimal import Decimal

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode
from astra_domain import PriceItem

__all__ = [
    "CORE_PRICE_VERSION",
    "StaticPriceCatalog",
    "build_default_price_catalog",
]

#: 核心价目版本号（不可变；价目调整即发布新版本）。
CORE_PRICE_VERSION = "core-2026-10-08"

#: 时间哨兵统一为 **aware（UTC）**，与 ``utcnow()`` 一致，避免 naive/aware 混比较。
_NEG_INF = datetime.min.replace(tzinfo=UTC)
_POS_INF = datetime.max.replace(tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """归一化时间戳到 UTC aware（``None`` 原样返回；naive 视为 UTC）。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounds(item: PriceItem) -> tuple[datetime, datetime]:
    """返回价目项的 ``[起, 止)`` 生效区间（边界已 tz 归一化 + 哨兵回退）。"""
    start = _as_utc(item.effective_from) or _NEG_INF
    end = _as_utc(item.effective_to) or _POS_INF
    return start, end


def _is_effective(item: PriceItem, moment: datetime | None) -> bool:
    """某时刻是否落入价目项生效区间（``moment=None`` 视为不限时刻）。"""
    if moment is None:
        return True
    now = _as_utc(moment) or _NEG_INF
    start, end = _bounds(item)
    return start <= now < end


def _overlap(a: PriceItem, b: PriceItem) -> bool:
    a_start, a_end = _bounds(a)
    b_start, b_end = _bounds(b)
    return a_start < b_end and b_start < a_end


class StaticPriceCatalog:
    """静态价目目录（版本化，同一模型同一时段仅一个有效项）。"""

    def __init__(self, items: Iterable[PriceItem] = ()) -> None:
        self._items: list[PriceItem] = []
        self._index: dict[tuple[str, str, str, str], PriceItem] = {}
        for item in items:
            self.register(item)

    # -- 注册 / 校验 ---------------------------------------------------------

    def register(self, item: PriceItem) -> None:
        """登记一个价目项（校验版本唯一 + 时段不重叠）。

        Raises:
            DomainError: 同版本重复登记或同一模型同一币种时段重叠（``CONFLICT``）。
        """
        key = (item.provider, item.model, item.currency, item.price_version)
        if key in self._index:
            raise DomainError(
                "价目项重复登记（同 provider/model/currency/price_version）",
                code=ErrorCode.CONFLICT,
                data={"key": list(key)},
            )
        for existing in self._items:
            same_target = (
                existing.provider == item.provider
                and existing.model == item.model
                and existing.currency == item.currency
            )
            if same_target and _overlap(existing, item):
                raise DomainError(
                    "同一模型同一时段仅允许一个有效价目项",
                    code=ErrorCode.CONFLICT,
                    data={"provider": item.provider, "model": item.model},
                )
        self._items.append(item)
        self._index[key] = item

    def extend(self, items: Iterable[PriceItem]) -> None:
        """批量登记。"""
        for item in items:
            self.register(item)

    # -- 查询 ----------------------------------------------------------------

    def price(
        self,
        provider: str,
        model: str,
        *,
        price_version: str | None = None,
        currency: str | None = None,
    ) -> PriceItem | None:
        """查询有效价目项（无匹配返回 ``None``）。"""
        candidates = [
            item
            for item in self._items
            if item.provider == provider
            and item.model == model
            and (currency is None or item.currency == currency)
        ]
        if price_version is not None:
            candidates = [item for item in candidates if item.price_version == price_version]
            return candidates[0] if candidates else None
        now = utcnow()
        effective = [item for item in candidates if _is_effective(item, now)]
        if not effective:
            return None
        return max(effective, key=lambda item: _as_utc(item.effective_from) or _NEG_INF)

    def versions(self) -> list[str]:
        """返回已登记的全部价目版本（排序）。"""
        return sorted({item.price_version for item in self._items})

    def __iter__(self) -> Iterator[PriceItem]:  # noqa: D105
        return iter(self._items)

    def __len__(self) -> int:  # noqa: D105
        return len(self._items)


def _item(
    provider: str,
    model: str,
    input_price: str,
    output_price: str,
    *,
    currency: str = "USD",
    version: str = CORE_PRICE_VERSION,
) -> PriceItem:
    return PriceItem(
        provider=provider,
        model=model,
        currency=currency,
        input_price_per_1k=Decimal(input_price),
        output_price_per_1k=Decimal(output_price),
        price_version=version,
    )


#: 核心随版本发布的默认价目（USD / 每 1000 token）；示例性首批集合。
_DEFAULT_ITEMS: tuple[PriceItem, ...] = (
    _item("openai", "gpt-4o", "0.005", "0.015"),
    _item("openai", "gpt-4o-mini", "0.00015", "0.0006"),
    _item("anthropic", "claude-3-5-sonnet", "0.003", "0.015"),
    _item("gemini", "gemini-1.5-pro", "0.00125", "0.005"),
    _item("deepseek", "deepseek-chat", "0.00014", "0.00028"),
    _item("qwen", "qwen-plus", "0.0004", "0.0012"),
)


def build_default_price_catalog() -> StaticPriceCatalog:
    """构建核心默认价目目录（版本 :data:`CORE_PRICE_VERSION`）。"""
    return StaticPriceCatalog(_DEFAULT_ITEMS)
