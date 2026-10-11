"""``InProcessBackgroundExecutor``——社区默认后台执行体（W1 / T2-02；设计 §2.9）。

以 **线程 / 子进程池** 承载处理器，并驱动 :class:`~astra_task.models.Task` **状态机**：

- 受理时 ``CREATED → RUNNING``（``start_inline``，设计 §2.11 内联路径）或
  ``PENDING → RUNNING``（``start``）；
- 处理器正常返回 → ``RUNNING → SUCCESS``（dict 结果写入 ``task.result``）；
- 处理器抛异常 / 未注册 → ``RUNNING → FAILED``（写入 ``task.error``）。

🔴 **构造时不得启动线程池**（懒启动）：仅在首次 :meth:`submit` 时按需创建，避免测试
   残留线程 / 子进程（对齐 ``LocalScheduler`` 的懒启动纪律）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from ..models import Task
from ..states import TaskStatus

__all__ = ["InProcessBackgroundExecutor"]


class InProcessBackgroundExecutor:
    """进程内后台执行体（社区默认）。

    Attributes:
        max_workers: 池容量（默认 4）。
        use_subprocess: ``True`` 用子进程池（CPU 密集 / 强隔离），否则线程池。
    """

    def __init__(self, *, max_workers: int = 4, use_subprocess: bool = False) -> None:
        """构造执行体（**不启动池**，懒启动）。

        Args:
            max_workers: 池容量。
            use_subprocess: 是否使用子进程池。
        """
        self._max_workers = max_workers
        self._use_subprocess = use_subprocess
        self._handlers: dict[str, Callable[[Task], Any]] = {}
        self._futures: list[Any] = []
        self._lock = threading.Lock()
        self._pool: Any | None = None

    @property
    def max_workers(self) -> int:
        """池容量（只读）。"""
        return self._max_workers

    @property
    def use_subprocess(self) -> bool:
        """是否使用子进程池（只读）。"""
        return self._use_subprocess

    def register_handler(self, handler_key: str, handler: Callable[[Task], Any]) -> None:
        """注册处理器（键 → 可调用；可调用接收 :class:`Task` 并可选返回 ``dict``）。"""
        with self._lock:
            self._handlers[handler_key] = handler

    def _ensure_pool(self) -> Any:
        """按需创建线程 / 子进程池（懒启动）。"""
        with self._lock:
            if self._pool is None:
                if self._use_subprocess:
                    from concurrent.futures import ProcessPoolExecutor

                    self._pool = ProcessPoolExecutor(max_workers=self._max_workers)
                else:
                    from concurrent.futures import ThreadPoolExecutor

                    self._pool = ThreadPoolExecutor(max_workers=self._max_workers)
            return self._pool

    def submit(self, task: Task, handler_key: str) -> None:
        """提交任务：异步驱动状态机执行处理器。

        Args:
            task: 待执行任务。
            handler_key: 处理器键。
        """
        with self._lock:
            handler: Callable[[Task], Any] | None = self._handlers.get(handler_key)
        future = self._ensure_pool().submit(self._run, task, handler_key, handler)
        with self._lock:
            self._futures.append(future)

    def _run(
        self,
        task: Task,
        handler_key: str,
        handler: Callable[[Task], Any] | None,
    ) -> None:
        """驱动单个任务：状态机推进 → 调用处理器 → 终态。"""
        if task.is_terminal:
            return
        if task.status is TaskStatus.CREATED:
            task.start_inline()
        elif task.status is TaskStatus.PENDING:
            task.start()
        if handler is None:
            task.fail(f"未注册处理器：{handler_key}")
            return
        try:
            result = handler(task)
            task.succeed(dict(result) if isinstance(result, dict) else None)
        except Exception as exc:  # noqa: BLE001 - 统一落 FAILED（非静默）
            task.fail(f"{type(exc).__name__}: {exc}")

    def wait(self) -> None:
        """等待已提交任务的**已入池** Future 全部完成（测试用）。"""
        with self._lock:
            futures = list(self._futures)
            self._futures = []
        for future in futures:
            future.result()

    def shutdown(self, wait: bool = True) -> None:
        """关闭执行体（幂等）。"""
        with self._lock:
            pool = self._pool
            self._pool = None
        if pool is not None:
            pool.shutdown(wait=wait)
