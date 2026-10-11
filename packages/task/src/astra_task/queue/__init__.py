"""``TaskQueue`` 抽象 + ``InProcessTaskQueue``（线程安全）。

演进路径（**接口不变**）：``InProcessTaskQueue → RedisTaskQueue（Arq）``。

W1 / T2-02 结构调整：原 ``astra_task/queue.py`` 模块**包化**为本 ``queue/`` 子包，
``from astra_task.queue import TaskQueue, InProcessTaskQueue`` **路径不变**；
``RedisTaskQueue``（Team / Arq）落本子包 :mod:`astra_task.queue.redis`。
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Generic, Protocol, TypeVar, runtime_checkable

__all__ = ["TaskQueue", "InProcessTaskQueue"]

T = TypeVar("T")


@runtime_checkable
class TaskQueue(Protocol, Generic[T]):
    """任务队列接口。

    演进路径（**接口不变**）：``InProcessTaskQueue → RedisTaskQueue（Arq）``。
    """

    def enqueue(self, item: T) -> None:
        """入队。"""
        ...

    def dequeue(self) -> T | None:
        """出队（无元素返回 ``None``）；被取出但未 ack 的元素计入 in-flight。"""
        ...

    def ack(self, item: T) -> None:
        """确认完成（从 in-flight 移除）。"""
        ...

    def size(self) -> int:
        """待处理元素数量。"""
        ...


class InProcessTaskQueue(Generic[T]):
    """进程内任务队列（线程安全）。

    使用 :class:`collections.deque` + :class:`threading.Lock`；取出但未 ack
    的元素进入 in-flight 集合，支持 at-least-once 语义。
    """

    def __init__(self) -> None:
        self._pending: deque[T] = deque()
        self._in_flight: set[int] = set()
        self._items: dict[int, T] = {}
        self._lock = threading.Lock()
        self._seq = 0

    def enqueue(self, item: T) -> None:
        """入队。"""
        with self._lock:
            self._pending.append(item)

    def dequeue(self) -> T | None:
        """出队；无元素返回 ``None``。"""
        with self._lock:
            if not self._pending:
                return None
            item = self._pending.popleft()
            key = self._seq
            self._seq += 1
            self._items[key] = item
            self._in_flight.add(key)
            return item

    def ack(self, item: T) -> None:
        """确认完成（幂等：未在 in-flight 时静默忽略）。"""
        with self._lock:
            key = next(
                (k for k, v in self._items.items() if v == item and k in self._in_flight),
                None,
            )
            if key is not None:
                self._in_flight.discard(key)
                self._items.pop(key, None)

    def size(self) -> int:
        """待处理元素数量。"""
        with self._lock:
            return len(self._pending)

    def in_flight(self) -> int:
        """在途（已取出未 ack）元素数量。"""
        with self._lock:
            return len(self._in_flight)

    def is_empty(self) -> bool:
        """队列是否为空。"""
        return self.size() == 0
