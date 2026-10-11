"""server 模式占位：``UnsupportedTaskQueue`` / ``UnsupportedScheduler``。

非静默降级：接口齐备、应用可启动，但**首次调用**即抛 ``NotImplementedYetError``。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Generic, NoReturn, TypeVar

from astra_core import NotImplementedYetError

__all__ = [
    "UnsupportedTaskQueue",
    "UnsupportedScheduler",
    "UnsupportedBackgroundExecutor",
]

T = TypeVar("T")


class _UnsupportedBase:
    """占位基类：统一抛出未实现错误。"""

    def __init__(self, *, feature: str, available_in: str) -> None:
        self.feature = feature
        self.available_in = available_in

    def _raise(self, operation: str) -> NoReturn:
        raise NotImplementedYetError(
            f"能力「{self.feature}」尚未实现（目标阶段：{self.available_in}）；"
            f"当前调用：{operation}。请使用 ASTRA_MODE=local 以获得进程内实现。",
            data={"feature": self.feature, "available_in": self.available_in},
        )


class UnsupportedTaskQueue(_UnsupportedBase, Generic[T]):
    """server 模式任务队列占位（Redis 目标，Team 阶段）。"""

    def enqueue(self, item: T) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("enqueue")

    def dequeue(self) -> T | None:
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("dequeue")

    def ack(self, item: T) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("ack")

    def size(self) -> int:
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("size")


class UnsupportedScheduler(_UnsupportedBase):
    """server 模式调度器占位（分布式目标，Team 阶段）。"""

    def schedule_once(
        self, run_at: datetime, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> str:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("schedule_once")

    def start(self) -> None:
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("start")

    def shutdown(self, wait: bool = False) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("shutdown")


class UnsupportedBackgroundExecutor(_UnsupportedBase):
    """server 模式后台执行体占位（Redis / 独立 Worker 进程目标，Team 阶段）。

    非静默降级：接口齐备、应用可启动，但**首次调用**即抛 ``NotImplementedYetError``；
    当 ``Redis 已配置`` 且 ``astra-task[redis]`` 就位时由
    :class:`~astra_task.executor.worker_process.WorkerProcessExecutor` 取代。
    """

    def submit(self, task: object, handler_key: str) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("submit")

    def shutdown(self, wait: bool = False) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("shutdown")
