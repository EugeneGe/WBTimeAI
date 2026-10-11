"""后台执行体子包（W1 / T2-02；设计 §2.9 / R-23）。

**执行体 / 队列正交**：

- :class:`~astra_task.executor.base.BackgroundExecutor`：执行体 Protocol（``submit``）；
- :class:`~astra_task.executor.inprocess.InProcessBackgroundExecutor`：社区默认（线程 / 子进程池）；
- :class:`~astra_task.executor.worker_process.WorkerProcessExecutor`：Team（队列 + 独立进程）。
"""

from __future__ import annotations

from .base import BackgroundExecutor
from .inprocess import InProcessBackgroundExecutor
from .worker_process import WorkerProcessExecutor

__all__ = [
    "BackgroundExecutor",
    "InProcessBackgroundExecutor",
    "WorkerProcessExecutor",
]
