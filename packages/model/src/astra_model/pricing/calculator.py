"""``CostCalculator``——成本计算（设计 §2.3.4 / A-4）。

按 ``provider`` / ``model`` / ``price_version`` / ``currency`` + 用量计算成本，
产出可直接写入 ``agent_run.cost*`` 的结果：

- 金额一律 **Decimal**（十进制定点数，非浮点）；
- 缺少用量 → ``estimated=True``；
- 缺少价目 → ``status=UNPRICED`` 且 ``cost`` 为 ``None``（**不得记零金额冒充免费**）；
- 分项之和 == 总额（同币种）；相同输入重复结算**幂等**（纯函数）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from astra_domain import (
    TOKENS_PER_PRICE_UNIT,
    CostBreakdown,
    CostStatus,
    PriceItem,
    quantize_amount,
)

from .provider import PriceProvider

__all__ = ["CostCalculator", "CostResult"]


@dataclass
class CostResult:
    """一次成本结算结果（映射 ``agent_run.cost*`` 列）。

    Attributes:
        status: 成本状态（``PRICED`` / ``UNPRICED``）。
        cost: 总金额（``UNPRICED`` 时为 ``None``）。
        currency: 币种（``UNPRICED`` 时为 ``None``）。
        price_version: 所用价目版本（``UNPRICED`` 时为请求值，可空）。
        estimated: 是否含估算用量。
        breakdown: 分项列表（同币种）。
    """

    status: CostStatus
    cost: Decimal | None
    currency: str | None
    price_version: str | None
    estimated: bool
    breakdown: list[CostBreakdown] = field(default_factory=list)

    @property
    def priced(self) -> bool:
        """是否已计价。"""
        return self.status is CostStatus.PRICED

    def breakdown_dict(self) -> dict[str, Any]:
        """转换为可落 ``agent_run.cost_breakdown`` 的 JSON 结构。"""
        return {
            "currency": self.currency,
            "price_version": self.price_version,
            "estimated": self.estimated,
            "items": [item.to_dict() for item in self.breakdown],
            "total": str(self.cost) if self.cost is not None else None,
        }


class CostCalculator:
    """成本计算器（依赖 :class:`~astra_model.pricing.provider.PriceProvider`）。"""

    def __init__(self, price_provider: PriceProvider) -> None:
        self._prices = price_provider

    def calculate(
        self,
        *,
        provider: str,
        model: str,
        usage: dict[str, Any] | None,
        price_version: str | None = None,
        currency: str | None = None,
    ) -> CostResult:
        """按用量 + 价目计算成本。

        Args:
            provider: 提供方标识。
            model: 模型名。
            usage: 用量（``prompt_tokens`` / ``completion_tokens``，兼容
                ``input_tokens`` / ``output_tokens``；``None`` 视为估算）。
            price_version: 指定价目版本（复算时使用**已记录**版本）。
            currency: 指定币种（``None`` 不限）。

        Returns:
            :class:`CostResult`。
        """
        input_tokens, output_tokens, estimated = _extract_usage(usage)
        price = self._prices.price(provider, model, price_version=price_version, currency=currency)
        if price is None:
            return CostResult(
                status=CostStatus.UNPRICED,
                cost=None,
                currency=None,
                price_version=price_version,
                estimated=estimated,
                breakdown=[],
            )
        item = _compute_item(price, input_tokens, output_tokens, estimated)
        return CostResult(
            status=CostStatus.PRICED,
            cost=quantize_amount(item.total),
            currency=price.currency,
            price_version=price.price_version,
            estimated=estimated,
            breakdown=[item],
        )


def _extract_usage(usage: dict[str, Any] | None) -> tuple[int, int, bool]:
    """从用量字典提取 ``(输入, 输出, 是否估算)``（缺失即估算）。"""
    if not usage:
        return 0, 0, True
    input_raw = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_raw = usage.get("completion_tokens", usage.get("output_tokens"))
    estimated = input_raw is None or output_raw is None
    input_tokens = int(input_raw) if input_raw is not None else 0
    output_tokens = int(output_raw) if output_raw is not None else 0
    return input_tokens, output_tokens, estimated


def _compute_item(
    price: PriceItem, input_tokens: int, output_tokens: int, estimated: bool
) -> CostBreakdown:
    """按价目与用量计算单个成本分项。"""
    input_cost = quantize_amount(
        Decimal(input_tokens) / TOKENS_PER_PRICE_UNIT * price.input_price_per_1k
    )
    output_cost = quantize_amount(
        Decimal(output_tokens) / TOKENS_PER_PRICE_UNIT * price.output_price_per_1k
    )
    return CostBreakdown(
        provider=price.provider,
        model=price.model,
        currency=price.currency,
        price_version=price.price_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost=input_cost,
        output_cost=output_cost,
        estimated=estimated,
    )
