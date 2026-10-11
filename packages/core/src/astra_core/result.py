"""``Result`` 类型：以值而非异常表达可预期失败。

用于领域层 / 应用层中「可预期」的错误结果，避免用异常做控制流。
:class:`Ok` 表示成功，:class:`Err` 表示失败。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")
U = TypeVar("U")

__all__ = ["Result", "Ok", "Err"]


class Result(Generic[T]):
    """不可变结果容器。

    通常不直接实例化，而通过 :func:`Ok` / :func:`Err` 构造。
    """

    __slots__ = ("_error", "_is_ok", "_value")

    def __init__(self, *, is_ok: bool, value: T | None = None, error: Any | None = None) -> None:
        self._is_ok = is_ok
        self._value: T | None = value
        self._error: Any | None = error

    # -- 状态判定 -----------------------------------------------------------
    def is_ok(self) -> bool:
        """是否为成功结果。"""
        return self._is_ok

    def is_err(self) -> bool:
        """是否为失败结果。"""
        return not self._is_ok

    # -- 取值 ---------------------------------------------------------------
    def unwrap(self) -> T:
        """返回成功值。

        Raises:
            ValueError: 当结果失败时。
        """
        if not self._is_ok:
            raise ValueError(f"Called unwrap() on an Err result: {self._error!r}")
        return self._value  # type: ignore[return-value]

    def unwrap_err(self) -> Any:
        """返回错误值。

        Raises:
            ValueError: 当结果成功时。
        """
        if self._is_ok:
            raise ValueError("Called unwrap_err() on an Ok result")
        return self._error

    def unwrap_or(self, default: T) -> T:
        """返回成功值，否则返回 ``default``。"""
        return self._value if self._is_ok else default  # type: ignore[return-value]

    # -- 变换 ---------------------------------------------------------------
    def map(self, func: Callable[[T], U]) -> Result[U]:
        """映射成功值；失败结果原样透传。"""
        if self._is_ok:
            return Ok(func(self._value))  # type: ignore[arg-type]
        return Err(self._error)

    def map_err(self, func: Callable[[Any], Any]) -> Result[T]:
        """映射错误值；成功结果原样透传。"""
        if self._is_ok:
            return Ok(self._value)  # type: ignore[arg-type]
        return Err(func(self._error))

    # -- 其它 ---------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Result):
            return NotImplemented
        return (
            self._is_ok == other._is_ok
            and self._value == other._value
            and self._error == other._error
        )

    def __hash__(self) -> int:
        return hash((self._is_ok, self._value))

    def __repr__(self) -> str:
        if self._is_ok:
            return f"Ok({self._value!r})"
        return f"Err({self._error!r})"


def Ok(value: T) -> Result[T]:  # noqa: N802 - 对齐 Rust/Scala 命名习惯
    """构造成功结果。"""
    return Result(is_ok=True, value=value)


def Err(error: Any) -> Result[Any]:  # noqa: N802 - 对齐 Rust/Scala 命名习惯
    """构造失败结果。"""
    return Result(is_ok=False, error=error)
