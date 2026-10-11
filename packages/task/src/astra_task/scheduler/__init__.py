"""``Scheduler`` 抽象 + ``LocalScheduler``（APScheduler 支撑，懒启动）。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = ["Scheduler", "LocalScheduler"]


@runtime_checkable
class Scheduler(Protocol):
    """调度器接口。

    演进路径（**接口不变**）：``LocalScheduler → DistributedScheduler``。
    """

    def schedule_once(
        self, run_at: datetime, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> str:
        """调度一次性任务，返回任务 id。"""
        ...

    def start(self) -> None:
        """启动调度器。"""
        ...

    def shutdown(self, wait: bool = False) -> None:
        """关闭调度器。"""
        ...


class LocalScheduler:
    """本地调度器（APScheduler ``BackgroundScheduler``）。

    🔴 **构造时不得启动线程 / 调度器**（懒启动）：仅在首次 :meth:`start`
    或 :meth:`schedule_once` 时按需创建底层调度器，避免测试出现残留线程。
    """

    def __init__(self) -> None:
        self._scheduler: Any | None = None
        self._lock = threading.Lock()

    def _ensure_scheduler(self) -> Any:
        with self._lock:
            if self._scheduler is None:
                from apscheduler.schedulers.background import BackgroundScheduler

                self._scheduler = BackgroundScheduler()
            return self._scheduler

    @property
    def started(self) -> bool:
        """底层调度器是否已启动。"""
        return self._scheduler is not None and bool(getattr(self._scheduler, "running", False))

    def start(self) -> None:
        """启动调度器（幂等）。"""
        scheduler = self._ensure_scheduler()
        if not scheduler.running:
            scheduler.start()

    def schedule_once(
        self, run_at: datetime, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> str:
        """调度一次性任务。

        Args:
            run_at: 运行时间（建议 tz-aware UTC）。
            func: 目标可调用。
            *args: 位置参数。
            **kwargs: 关键字参数。

        Returns:
            任务 id。
        """
        scheduler = self._ensure_scheduler()
        job = scheduler.add_job(func, "date", run_date=run_at, args=args, kwargs=kwargs)
        return str(job.id)

    def schedule_interval(
        self,
        seconds: float,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        """调度周期性任务，返回任务 id。"""
        scheduler = self._ensure_scheduler()
        job = scheduler.add_job(func, "interval", seconds=seconds, args=args, kwargs=kwargs)
        return str(job.id)

    def shutdown(self, wait: bool = False) -> None:
        """关闭调度器（幂等）。"""
        if self._scheduler is not None and getattr(self._scheduler, "running", False):
            self._scheduler.shutdown(wait=wait)
