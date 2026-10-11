"""Workflow 并发控制（W4 / T2-23；设计 §2.5 / N-P2-02 / W4 裁定 §4）。

- :class:`ConcurrencyGuardImpl`：``PARALLEL`` 分支并发守卫——**超限即抛**
  ``RESOURCE_LIMIT_EXCEEDED``，**不静默排队**（WR-2）；上限读
  ``ConcurrencyConfig.max_parallel``（W4 裁定 §6.1 R5-b，默认 4）；
- :class:`ActiveRunGuard`：活跃 Run 上限（沿用 ``ConcurrencyConfig.max_runs_per_conversation``
  语义；Workflow 无 conversation 维度，故按**组合根给定的键**（租户 / 工作区）计数）。

``sandbox_session`` **跨 Run 不共享**（同一 Run 内串行化，W4 裁定 §3.3）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from astra_core import DomainError, ErrorCode
from astra_domain import ConcurrencyConfig

from .ports import ConcurrencyGuard

__all__ = [
    "ConcurrencyGuardImpl",
    "ActiveRunGuard",
]


class ConcurrencyGuardImpl:
    """``PARALLEL`` 并发守卫（信号量；**超限即抛**，不排队）。

    Attributes:
        config: 并发配置（读 ``max_parallel``）。
    """

    def __init__(self, config: ConcurrencyConfig | None = None) -> None:
        """初始化守卫。

        Args:
            config: 并发配置；缺省 ``ConcurrencyConfig()``（``max_parallel=4``）。
        """
        self._config = config or ConcurrencyConfig()
        self._limit = max(1, int(self._config.max_parallel))
        self._semaphore = threading.Semaphore(self._limit)

    @property
    def max_parallel(self) -> int:
        """并发上限（``ConcurrencyConfig.max_parallel``）。"""
        return self._limit

    @property
    def available(self) -> int:
        """当前可用并发位（近似值，仅用于观测 / 诊断）。"""
        return self._semaphore._value  # noqa: SLF001 - 仅观测，不参与判定

    def acquire(self, slots: int = 1) -> None:
        """申请 ``slots`` 个并发位（**非阻塞**；不足即抛，**不排队**）。

        Args:
            slots: 申请位数（``<=0`` 视为 ``0``，直接返回）。

        Raises:
            DomainError: 并发位不足（``RESOURCE_LIMIT_EXCEEDED``）。
        """
        needed = max(0, int(slots))
        granted = 0
        for _ in range(needed):
            if not self._semaphore.acquire(blocking=False):
                self.release(granted)
                raise DomainError(
                    f"Workflow 并行分支数超过上限：需要 {needed}，可用 {self._limit}",
                    code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
                    data={
                        "reason": "parallel_limit_exceeded",
                        "slots": needed,
                        "max_parallel": self._limit,
                    },
                )
            granted += 1

    def release(self, slots: int = 1) -> None:
        """归还 ``slots`` 个并发位。"""
        for _ in range(max(0, int(slots))):
            self._semaphore.release()

    def as_guard(self) -> ConcurrencyGuard:
        """以 :class:`ConcurrencyGuard` Protocol 视图返回自身。"""
        return self


class ActiveRunGuard:
    """活跃 Run 上限守卫（沿用 ``max_runs_per_conversation`` 语义，**无超卖**）。

    ``WorkflowRun`` 无 ``conversation_id`` 维度，故计数键由**组合根**给定（租户 /
    工作区 / 业务键均可）；计数源为注入的 ``active_counter``。
    """

    def __init__(
        self,
        active_counter: Callable[[str], int],
        *,
        max_active: int | None = None,
        config: ConcurrencyConfig | None = None,
    ) -> None:
        """初始化上限守卫。

        Args:
            active_counter: ``(key) -> 当前活跃 Run 数``（由组合根提供，通常读仓储）。
            max_active: 上限覆盖值；缺省取 ``config.max_runs_per_conversation``。
            config: 并发配置（``max_active`` 为空时读取）。
        """
        self._counter = active_counter
        effective = config or ConcurrencyConfig()
        self._max_active = (
            int(max_active) if max_active is not None else int(effective.max_runs_per_conversation)
        )

    @property
    def max_active(self) -> int:
        """活跃 Run 上限。"""
        return self._max_active

    def check(self, key: str) -> None:
        """断言 ``key`` 下活跃 Run 数未达上限；超限 → ``RESOURCE_LIMIT_EXCEEDED``。

        Args:
            key: 计数键（租户 / 工作区等）。

        Raises:
            DomainError: 已达上限（``RESOURCE_LIMIT_EXCEEDED``）。
        """
        if self._max_active <= 0:
            return  # 0 / 负 = 不限
        active = int(self._counter(key) or 0)
        if active >= self._max_active:
            raise DomainError(
                f"活跃 Workflow Run 数已达上限：{active} >= {self._max_active}",
                code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
                data={
                    "reason": "active_run_limit_exceeded",
                    "active": active,
                    "max_active": self._max_active,
                    "key": key,
                },
            )
