"""``PriceItem.is_effective_at`` tz 归一化单测（W7 / 台账 A21）。

覆盖：① 全 naive 正常区间；② naive 边界 + aware ``moment``；③ aware 边界 + naive
``moment``；④ ``moment=None`` 恒真；⑤ 区间外 / 边界开闭（``from`` 含、``to`` 不含）
与非 UTC 偏移换算。

无框架依赖（纯标准库 + 领域值对象），故置于 ``tests/unit/``。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from astra_domain import PriceItem


def _item(
    *,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> PriceItem:
    """构造一个最小 ``PriceItem``（仅关注生效区间字段）。"""
    return PriceItem(
        provider="openai",
        model="gpt-4o",
        currency="USD",
        input_price_per_1k=Decimal("0.005"),
        output_price_per_1k=Decimal("0.015"),
        price_version="v1",
        effective_from=effective_from,
        effective_to=effective_to,
    )


def test_all_naive_interval() -> None:
    """① 全 naive：正常区间内 / 外判定正确（半开区间 ``[from, to)``）。"""
    item = _item(
        effective_from=datetime(2026, 1, 1, 0, 0, 0),
        effective_to=datetime(2026, 2, 1, 0, 0, 0),
    )
    assert item.is_effective_at(datetime(2026, 1, 15)) is True
    assert item.is_effective_at(datetime(2025, 12, 31, 23, 59)) is False


def test_naive_bounds_aware_moment_no_typeerror() -> None:
    """② naive 边界 + aware ``moment``：不抛 ``TypeError``，语义正确（naive 视为 UTC）。"""
    item = _item(
        effective_from=datetime(2026, 1, 1),
        effective_to=datetime(2026, 2, 1),
    )
    assert item.is_effective_at(datetime(2026, 1, 15, tzinfo=UTC)) is True
    assert item.is_effective_at(datetime(2026, 3, 1, tzinfo=UTC)) is False


def test_aware_bounds_naive_moment_no_typeerror() -> None:
    """③ aware 边界 + naive ``moment``：不抛 ``TypeError``，语义正确（naive 视为 UTC）。"""
    item = _item(
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert item.is_effective_at(datetime(2026, 1, 15)) is True
    assert item.is_effective_at(datetime(2026, 1, 1)) is True
    assert item.is_effective_at(datetime(2026, 2, 1)) is False


def test_none_moment_always_true() -> None:
    """④ ``moment=None`` 恒真（视为不限时刻），即便区间为空。"""
    bounded = _item(
        effective_from=datetime(2026, 1, 1),
        effective_to=datetime(2026, 2, 1),
    )
    assert bounded.is_effective_at(None) is True
    # 无任何生效边界（长期有效）亦为真。
    assert _item().is_effective_at(None) is True


def test_boundary_open_closed_semantics() -> None:
    """⑤ 边界语义：``from`` **含**、``to`` **不含**；无边界侧不限。"""
    item = _item(
        effective_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        effective_to=datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC),
    )
    assert item.is_effective_at(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)) is True
    assert item.is_effective_at(datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC)) is True
    assert item.is_effective_at(datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)) is False


def test_open_ended_interval() -> None:
    """仅 ``from`` / 仅 ``to`` 的单边开区间。"""
    from_only = _item(effective_from=datetime(2026, 1, 1, tzinfo=UTC))
    assert from_only.is_effective_at(datetime(2030, 1, 1, tzinfo=UTC)) is True
    assert from_only.is_effective_at(datetime(2025, 1, 1, tzinfo=UTC)) is False

    to_only = _item(effective_to=datetime(2026, 1, 1, tzinfo=UTC))
    assert to_only.is_effective_at(datetime(2020, 1, 1, tzinfo=UTC)) is True
    assert to_only.is_effective_at(datetime(2026, 1, 1, tzinfo=UTC)) is False


def test_non_utc_offset_moment_equivalence() -> None:
    """非 UTC 偏移 ``moment`` 按等价 UTC 换算（边界含 / 不含不受偏移影响）。"""
    item = _item(
        effective_from=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        effective_to=datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC),
    )
    cst = timezone(timedelta(hours=8))  # UTC+08:00
    # 2026-01-01 08:00 (+08:00) == 2026-01-01 00:00 UTC → from 含 ⇒ True
    assert item.is_effective_at(datetime(2026, 1, 1, 8, 0, 0, tzinfo=cst)) is True
    # 2026-02-01 08:00 (+08:00) == 2026-02-01 00:00 UTC → to 不含 ⇒ False
    assert item.is_effective_at(datetime(2026, 2, 1, 8, 0, 0, tzinfo=cst)) is False
