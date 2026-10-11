"""``ModelRegistry`` 单测（注册 / 获取 / 重名覆盖）。"""

from __future__ import annotations

import pytest
from astra_core import DomainError
from astra_model import ModelRegistry, StubModelProvider


def test_register_and_get() -> None:
    registry = ModelRegistry()
    provider = StubModelProvider()
    registry.register("stub", provider)
    assert registry.get("stub") is provider
    assert registry.names() == ["stub"]
    assert "stub" in registry
    assert len(registry) == 1


def test_override_on_duplicate() -> None:
    registry = ModelRegistry()
    first, second = StubModelProvider(), StubModelProvider()
    registry.register("stub", first)
    registry.register("stub", second)
    assert registry.get("stub") is second


def test_duplicate_without_override_raises() -> None:
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider())
    with pytest.raises(DomainError):
        registry.register("stub", StubModelProvider(), override=False)


def test_get_missing_raises() -> None:
    with pytest.raises(DomainError):
        ModelRegistry().get("missing")
