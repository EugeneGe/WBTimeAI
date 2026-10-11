"""``astra_core.id.generate_id`` 单元测试（UUIDv7 版本位 / 时序 / 唯一性）。"""

from __future__ import annotations

import time
import uuid

from astra_core import generate_id


def test_generate_id_returns_uuid7_string() -> None:
    value = generate_id()
    assert isinstance(value, str)
    parsed = uuid.UUID(value)
    assert parsed.version == 7


def test_generate_id_is_unique() -> None:
    ids = {generate_id() for _ in range(2000)}
    assert len(ids) == 2000


def test_generate_id_is_time_ordered() -> None:
    first = generate_id()
    time.sleep(0.005)
    second = generate_id()
    # UUIDv7 字符串的字典序等价于时间序。
    assert second > first
