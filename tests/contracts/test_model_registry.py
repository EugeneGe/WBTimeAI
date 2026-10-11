"""``ModelRegistry`` 运行时注册契约测试（W1b 裁定 §6.2；``pytest.mark.contracts``）。

覆盖 ``register`` / ``unregister``（幂等）/ ``get``（存在返回同一实例）/ ``list()``
（排序、与 ``names()`` 一致）/ 未注册 ``get`` → ``DomainError(CONFIGURATION_ERROR)``
（**断言错误码**）/ ``override=False`` 重名 → ``DomainError(CONFLICT)`` /
向后兼容（``names()`` / ``__contains__`` / ``__len__``）。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_model import ModelRegistry, StubModelProvider

pytestmark = pytest.mark.contracts


def test_register_and_get_returns_same_instance() -> None:
    registry = ModelRegistry()
    provider = StubModelProvider()
    registry.register("stub", provider)
    assert registry.get("stub") is provider


def test_unregister_is_idempotent() -> None:
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider())
    registry.unregister("stub")
    assert "stub" not in registry
    # 再次注销（不存在）静默返回，不抛错。
    registry.unregister("stub")
    assert len(registry) == 0


def test_list_is_sorted_and_matches_names() -> None:
    registry = ModelRegistry()
    registry.register("zeta", StubModelProvider())
    registry.register("alpha", StubModelProvider())
    assert registry.list() == ["alpha", "zeta"]
    assert registry.list() == registry.names()


def test_get_missing_raises_configuration_error() -> None:
    with pytest.raises(DomainError) as excinfo:
        ModelRegistry().get("missing")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_duplicate_without_override_raises_conflict() -> None:
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider())
    with pytest.raises(DomainError) as excinfo:
        registry.register("stub", StubModelProvider(), override=False)
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_backward_compatible_members_still_work() -> None:
    registry = ModelRegistry()
    provider = StubModelProvider()
    registry.register("stub", provider)
    assert registry.names() == ["stub"]
    assert "stub" in registry
    assert len(registry) == 1
