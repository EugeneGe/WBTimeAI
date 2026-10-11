"""Model 组值对象（设计 §2.3.4 核心成本计价 / A-4 已确认）。

纯标准库实现（零框架依赖，C-03）：

- :class:`CostStatus`：成本状态（``PRICED`` / ``UNPRICED``；无匹配价目不得记零）；
- :class:`PriceItem`：版本化价目项（输入 / 输出单价、币种、生效时间、不可变 ``price_version``）；
- :class:`CostBreakdown`：单次调用的成本分项（金额用 **十进制定点数**，非浮点）。

🔴 「输入输出类型落 ``domain``」（总纲 §12.1-2）：这些值对象是核心与 Runtime /
   Commercial 之间的**稳定契约**，不开源实现细节。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from ..constants import COST_STATUS_PRICED, COST_STATUS_UNPRICED

__all__ = [
    "CostStatus",
    "PriceItem",
    "CostBreakdown",
    "TOKENS_PER_PRICE_UNIT",
    "quantize_amount",
]

#: 单价计价单位（每 1000 token）。
TOKENS_PER_PRICE_UNIT = Decimal(1000)

#: 金额保留小数位（对齐 ``agent_run.cost`` ``Numeric(18, 6)``）。
_AMOUNT_QUANT = Decimal("0.000001")


def quantize_amount(value: Decimal) -> Decimal:
    """把金额量化为 6 位小数（``ROUND_HALF_UP``，对齐 ``Numeric(18, 6)``）。"""
    return Decimal(value).quantize(_AMOUNT_QUANT, rounding=ROUND_HALF_UP)


def _to_utc(value: datetime) -> datetime:
    """把时间戳归一化为 **UTC aware**（naive 视为 UTC）。

    纯标准库实现（``datetime.UTC``）；与生产路径
    ``astra_model.pricing.catalog._as_utc`` 口径一致——但**严守分层**：
    ``astra_domain`` 不 import ``astra_model``，故于域内自备极小工具（台账 A21）。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """归一化可空时间戳到 UTC aware（``None`` 原样返回；naive 视为 UTC）。"""
    return None if value is None else _to_utc(value)


class CostStatus(StrEnum):
    """成本状态（设计 §2.3.4）。"""

    PRICED = COST_STATUS_PRICED
    UNPRICED = COST_STATUS_UNPRICED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


@dataclass(frozen=True)
class PriceItem:
    """版本化价目项（同一模型同一时段仅一个有效项）。

    Attributes:
        provider: 提供方标识（如 ``openai``）。
        model: 模型名（如 ``gpt-4o``）。
        currency: 计价币种（如 ``USD``）。
        input_price_per_1k: 输入单价（每 1000 token）。
        output_price_per_1k: 输出单价（每 1000 token）。
        price_version: 不可变价目版本号。
        effective_from: 生效时间（含；可空 = 自始生效）。
        effective_to: 失效时间（不含；可空 = 长期有效）。
    """

    provider: str
    model: str
    currency: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal
    price_version: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    def is_effective_at(self, moment: datetime | None) -> bool:
        """判断某时刻是否落入生效区间（``moment=None`` 视为不限时刻）。

        **tz-safe（台账 A21）**：``effective_from`` / ``effective_to`` / ``moment``
        先经 :func:`_as_utc` / :func:`_to_utc` 归一化为 **UTC aware**（naive 视为 UTC）
        再比较，避免 naive 与 aware 混比较抛 ``TypeError``。

        半开区间语义：``effective_from`` **含**、``effective_to`` **不含**。
        """
        if moment is None:
            return True
        now = _to_utc(moment)
        start = _as_utc(self.effective_from)
        end = _as_utc(self.effective_to)
        if start is not None and now < start:
            return False
        return not (end is not None and now >= end)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可落 JSON 的结构（金额转字符串，避免浮点误差）。"""
        return {
            "provider": self.provider,
            "model": self.model,
            "currency": self.currency,
            "input_price_per_1k": str(self.input_price_per_1k),
            "output_price_per_1k": str(self.output_price_per_1k),
            "price_version": self.price_version,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
        }


@dataclass(frozen=True)
class CostBreakdown:
    """单次调用的成本分项（金额为十进制定点数）。

    Attributes:
        provider: 提供方标识。
        model: 模型名。
        currency: 计价币种。
        price_version: 所用价目版本。
        input_tokens: 输入 token 数。
        output_tokens: 输出 token 数。
        input_cost: 输入成本。
        output_cost: 输出成本。
        estimated: 该分项是否含估算用量。
    """

    provider: str
    model: str
    currency: str
    price_version: str
    input_tokens: int
    output_tokens: int
    input_cost: Decimal
    output_cost: Decimal
    estimated: bool = False

    @property
    def total(self) -> Decimal:
        """分项总成本（输入 + 输出，同币种）。"""
        return self.input_cost + self.output_cost

    def to_dict(self) -> dict[str, Any]:
        """序列化为可落 JSON 的结构（金额转字符串）。"""
        return {
            "provider": self.provider,
            "model": self.model,
            "currency": self.currency,
            "price_version": self.price_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "input_cost": str(self.input_cost),
            "output_cost": str(self.output_cost),
            "total": str(self.total),
            "estimated": self.estimated,
        }
