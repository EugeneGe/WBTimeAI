"""``Result`` / ``Ok`` / ``Err`` 单元测试。"""

from __future__ import annotations

import pytest
from astra_core import Err, Ok, Result
from astra_core.error import DomainError


def test_ok_behaviour() -> None:
    result = Ok(42)
    assert isinstance(result, Result)
    assert result.is_ok()
    assert not result.is_err()
    assert result.unwrap() == 42
    assert result.unwrap_or(0) == 42


def test_err_behaviour() -> None:
    error = DomainError("boom")
    result = Err(error)
    assert result.is_err()
    assert not result.is_ok()
    assert result.unwrap_err() is error
    assert result.unwrap_or(7) == 7


def test_unwrap_on_err_raises() -> None:
    with pytest.raises(ValueError):
        Err(DomainError("boom")).unwrap()


def test_unwrap_err_on_ok_raises() -> None:
    with pytest.raises(ValueError):
        Ok(1).unwrap_err()


def test_map_only_applies_on_ok() -> None:
    assert Ok(2).map(lambda value: value * 3).unwrap() == 6
    failed = Err(DomainError("x")).map(lambda value: value)
    assert failed.is_err()
