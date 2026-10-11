"""核心成本计价单测（T1-13）：精确计算 / 估算标记 / ``UNPRICED`` 不记零 / 分项求和 / 幂等。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import CostStatus, PriceItem
from astra_model import (
    CORE_PRICE_VERSION,
    CostCalculator,
    PriceProvider,
    StaticPriceCatalog,
    build_default_price_catalog,
)


def _catalog() -> StaticPriceCatalog:
    return StaticPriceCatalog(
        [
            PriceItem(
                provider="openai",
                model="gpt-4o",
                currency="USD",
                input_price_per_1k=Decimal("0.005"),
                output_price_per_1k=Decimal("0.015"),
                price_version="test-1",
            )
        ]
    )


def test_calculator_satisfies_price_provider_protocol() -> None:
    assert isinstance(_catalog(), PriceProvider)


def test_exact_cost_and_breakdown_sum() -> None:
    result = CostCalculator(_catalog()).calculate(
        provider="openai",
        model="gpt-4o",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
    )
    assert result.status is CostStatus.PRICED
    assert isinstance(result.cost, Decimal)
    assert result.cost == Decimal("0.012500")
    assert result.currency == "USD"
    assert result.price_version == "test-1"
    assert result.estimated is False
    # 分项之和 == 总额（同币种）。
    assert sum(item.total for item in result.breakdown) == result.cost
    assert result.breakdown[0].input_cost == Decimal("0.005000")
    assert result.breakdown[0].output_cost == Decimal("0.007500")


def test_amounts_are_decimal_not_float() -> None:
    result = CostCalculator(_catalog()).calculate(
        provider="openai",
        model="gpt-4o",
        usage={"prompt_tokens": 1, "completion_tokens": 0},
    )
    assert isinstance(result.cost, Decimal)
    assert result.cost == Decimal("0.000005")


def test_missing_usage_marks_estimated() -> None:
    result = CostCalculator(_catalog()).calculate(provider="openai", model="gpt-4o", usage=None)
    assert result.status is CostStatus.PRICED
    assert result.estimated is True


def test_partial_usage_marks_estimated() -> None:
    result = CostCalculator(_catalog()).calculate(
        provider="openai", model="gpt-4o", usage={"prompt_tokens": 1000}
    )
    assert result.estimated is True
    assert result.breakdown[0].output_tokens == 0


def test_missing_price_is_unpriced_and_never_zero() -> None:
    result = CostCalculator(_catalog()).calculate(
        provider="openai",
        model="unknown-model",
        usage={"prompt_tokens": 1000, "completion_tokens": 500},
    )
    assert result.status is CostStatus.UNPRICED
    assert result.cost is None
    assert result.currency is None
    assert result.breakdown == []
    assert result.breakdown_dict()["total"] is None


def test_calculation_is_idempotent() -> None:
    calculator = CostCalculator(_catalog())
    usage = {"prompt_tokens": 123, "completion_tokens": 456}
    first = calculator.calculate(provider="openai", model="gpt-4o", usage=usage)
    second = calculator.calculate(provider="openai", model="gpt-4o", usage=usage)
    assert first.cost == second.cost
    assert first.breakdown_dict() == second.breakdown_dict()


def test_price_lookup_by_explicit_version() -> None:
    catalog = _catalog()
    assert catalog.price("openai", "gpt-4o", price_version="test-1") is not None
    assert catalog.price("openai", "gpt-4o", price_version="missing") is None
    assert catalog.price("openai", "gpt-4o", currency="EUR") is None


def test_catalog_rejects_overlapping_price_items() -> None:
    catalog = _catalog()
    with pytest.raises(DomainError) as excinfo:
        catalog.register(
            PriceItem(
                provider="openai",
                model="gpt-4o",
                currency="USD",
                input_price_per_1k=Decimal("0.009"),
                output_price_per_1k=Decimal("0.02"),
                price_version="test-2",
            )
        )
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_default_catalog_is_versioned_and_complete() -> None:
    catalog = build_default_price_catalog()
    assert len(catalog) >= 6
    assert CORE_PRICE_VERSION in catalog.versions()
    assert catalog.price("openai", "gpt-4o") is not None


# -- D2 回归：多版本价目 + aware 生效窗口（不 naive/aware 混比较） ----------------


def _aware(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def _versioned(
    version: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    input_price: str = "0.001",
    output_price: str = "0.002",
) -> PriceItem:
    return PriceItem(
        provider="openai",
        model="gpt-4o",
        currency="USD",
        input_price_per_1k=Decimal(input_price),
        output_price_per_1k=Decimal(output_price),
        price_version=version,
        effective_from=start,
        effective_to=end,
    )


def test_aware_windows_with_open_interval_register_and_price() -> None:
    catalog = StaticPriceCatalog(
        [
            _versioned("v1", start=_aware(2019, 1, 1), end=_aware(2020, 1, 1)),
            _versioned("v2", start=_aware(2020, 1, 1)),  # 开放区间 end=None
        ]
    )
    assert catalog.price("openai", "gpt-4o") is not None


def test_version_switch_point(monkeypatch: pytest.MonkeyPatch) -> None:
    import astra_model.pricing.catalog as catalog_module

    catalog = StaticPriceCatalog(
        [
            _versioned("v1", start=_aware(2019, 1, 1), end=_aware(2020, 1, 1)),
            _versioned("v2", start=_aware(2020, 1, 1)),
        ]
    )
    monkeypatch.setattr(catalog_module, "utcnow", lambda: _aware(2019, 6, 1))
    assert catalog.price("openai", "gpt-4o").price_version == "v1"  # type: ignore[union-attr]
    monkeypatch.setattr(catalog_module, "utcnow", lambda: _aware(2020, 6, 1))
    assert catalog.price("openai", "gpt-4o").price_version == "v2"  # type: ignore[union-attr]


def test_overlapping_aware_windows_conflict() -> None:
    with pytest.raises(DomainError) as excinfo:
        StaticPriceCatalog(
            [
                _versioned("v1", start=_aware(2019, 1, 1), end=_aware(2021, 1, 1)),
                _versioned("v2", start=_aware(2020, 1, 1)),
            ]
        )
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_naive_bounds_are_normalized() -> None:
    catalog = StaticPriceCatalog(
        [
            _versioned(
                "v-naive",
                start=datetime(2019, 1, 1),
                end=datetime(2020, 1, 1),
            )
        ]
    )
    assert catalog.price("openai", "gpt-4o", price_version="v-naive") is not None
    # naive 与 aware 同时登记也不混比较（不抛 TypeError）。
    catalog.register(_versioned("v2", start=_aware(2025, 1, 1)))
    assert catalog.price("openai", "gpt-4o") is not None
