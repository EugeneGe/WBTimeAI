"""Workflow 超时 / 重试 / 退避（W4 裁定 R3 §3.1；「超时/重试路径明确」）。

口径：

- **硬抢占**（单次工具 / 单次 Run 的墙钟超时）由 **Runtime 侧**负责（``ToolExecutor``
  的 ``tool_timeout_ms`` / ``AgentRuntime`` 的 ``run_timeout_ms``，F11）——引擎**不重复造**；
- 引擎负责 **Run 级预算**：:class:`TimeoutBudget` 在**每次节点执行前**做**协作式**
  截止检查，超预算 → ``DomainError(TOOL_TIMEOUT)``；
- :func:`run_with_retry` 提供**有界重试 + 指数退避**（``sleep`` 可注入 → fake clock 可测）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode

__all__ = [
    "DEFAULT_MAX_STEPS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_BACKOFF_BASE_MS",
    "DEFAULT_BACKOFF_MAX_MS",
    "RetryPolicy",
    "TimeoutBudget",
    "run_with_retry",
]


#: 引擎单次运行的最大节点步数（**有界**，防无界循环）。
DEFAULT_MAX_STEPS = 1000
#: 默认最大尝试次数（1 = 不重试）。
DEFAULT_MAX_ATTEMPTS = 1
#: 默认退避基数（毫秒）。
DEFAULT_BACKOFF_BASE_MS = 200
#: 默认退避上限（毫秒）。
DEFAULT_BACKOFF_MAX_MS = 5000


@dataclass(frozen=True)
class RetryPolicy:
    """节点级重试策略（有界 + 指数退避）。

    Attributes:
        max_attempts: 最大尝试次数（**含首次**；``<=1`` 表示不重试）。
        backoff_base_ms: 退避基数（毫秒）。
        backoff_max_ms: 退避上限（毫秒）。
        retry_on: 仅当错误码在此集合内才重试；**空集合 = 全部重试**。
    """

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_base_ms: int = DEFAULT_BACKOFF_BASE_MS
    backoff_max_ms: int = DEFAULT_BACKOFF_MAX_MS
    retry_on: tuple[str, ...] = ()

    def delay_ms(self, attempt: int) -> int:
        """返回第 ``attempt`` 次失败后的退避毫秒数（指数增长，受上限截断）。

        Args:
            attempt: 已完成的尝试次数（从 ``1`` 起）。

        Returns:
            退避毫秒数（``0`` 表示无需等待）。
        """
        if attempt < 1 or self.max_attempts <= 1:
            return 0
        exponent = max(0, attempt - 1)
        delay = self.backoff_base_ms * (2**exponent)
        return int(min(delay, self.backoff_max_ms))

    def should_retry(self, error: BaseException) -> bool:
        """判断是否应对 ``error`` 重试。

        ``retry_on`` 非空时，仅当 :class:`DomainError` 的 ``code`` 命中集合才重试；
        空集合表示**全部**错误均重试。
        """
        if not self.retry_on:
            return True
        if isinstance(error, DomainError):
            return str(error.code) in self.retry_on
        return False

    @classmethod
    def from_config(cls, data: dict[str, Any] | None) -> RetryPolicy:
        """由节点 ``config`` 构造（缺省回退默认值，向后兼容）。

        Args:
            data: 节点 ``config`` 字典（读 ``retry`` 段 / 兼容平铺键）。

        Returns:
            :class:`RetryPolicy`。
        """
        payload = dict(data or {})
        section = payload.get("retry")
        raw = dict(section) if isinstance(section, dict) else payload
        retry_on = raw.get("retry_on") or ()
        return cls(
            max_attempts=int(raw.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
            backoff_base_ms=int(raw.get("backoff_base_ms", DEFAULT_BACKOFF_BASE_MS)),
            backoff_max_ms=int(raw.get("backoff_max_ms", DEFAULT_BACKOFF_MAX_MS)),
            retry_on=tuple(str(item) for item in retry_on),
        )


@dataclass
class TimeoutBudget:
    """Run 级时间预算（**协作式**截止检查）。

    Attributes:
        total_ms: 预算总时长（毫秒）。``None`` = **不限**；``<=0`` = **零预算**
            （一经检查即视为耗尽）。
    """

    total_ms: int | None = None
    _started: float = field(default_factory=time.monotonic, repr=False)

    def elapsed_ms(self) -> int:
        """返回已消耗毫秒数。"""
        return int((time.monotonic() - self._started) * 1000)

    def remaining_ms(self) -> int | None:
        """返回剩余毫秒数；**不限**（``total_ms is None``）时返回 ``None``。"""
        if self.total_ms is None:
            return None
        return max(0, self.total_ms - self.elapsed_ms())

    def expired(self) -> bool:
        """预算是否已耗尽。"""
        remaining = self.remaining_ms()
        return remaining is not None and remaining <= 0

    def assert_not_expired(self) -> None:
        """断言预算未耗尽；耗尽 → ``DomainError(TOOL_TIMEOUT)``。

        Raises:
            DomainError: 预算耗尽（``TOOL_TIMEOUT``）。
        """
        if self.expired():
            raise DomainError(
                "Workflow 运行超出时间预算",
                code=ErrorCode.TOOL_TIMEOUT,
                data={"reason": "run_timeout", "total_ms": self.total_ms},
            )


def run_with_retry(
    operation: Callable[[], Any],
    *,
    policy: RetryPolicy | None = None,
    budget: TimeoutBudget | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> Any:
    """以**有界重试 + 指数退避**执行 ``operation``。

    Args:
        operation: 无参可调用对象（一次尝试）。
        policy: 重试策略；缺省 :class:`RetryPolicy`（不重试）。
        budget: 可选时间预算；每次尝试前做截止检查。
        sleep: 休眠函数（**可注入**，便于 fake clock 单测）。

    Returns:
        ``operation()`` 的返回值。

    Raises:
        DomainError: 预算耗尽（``TOOL_TIMEOUT``）或重试策略判定为**不重试**；
            末次尝试仍失败时**原样抛出**末次异常。
    """
    effective = policy if policy is not None else RetryPolicy()
    attempts = max(1, int(effective.max_attempts))
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        if budget is not None:
            budget.assert_not_expired()
        try:
            return operation()
        except BaseException as error:  # noqa: BLE001 - 交由策略判定是否重试
            last_error = error
            if attempt >= attempts or not effective.should_retry(error):
                raise
            delay_ms = effective.delay_ms(attempt)
            if delay_ms > 0:
                sleep(delay_ms / 1000.0)
    # 理论不可达（循环必 return 或 raise）；保留兜底以防 future 改动。
    if last_error is not None:  # pragma: no cover - 防御性
        raise last_error
    raise DomainError(  # pragma: no cover - 防御性
        "重试执行未产出结果", code=ErrorCode.INTERNAL_ERROR
    )
