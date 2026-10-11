"""``BackgroundExecutor``——后台执行体抽象（W1 / T2-02；设计 §2.9 / R-23）。

**执行体 / 队列正交**（硬点）：执行体决定「在**哪**跑」，队列决定「任务**如何传递**」；
二者组合自由，仅在 :func:`astra_config.providers.build_providers` 装配（C-01 / D4）。

- 社区（local）：:class:`~astra_task.executor.inprocess.InProcessBackgroundExecutor`；
- Team（server）：:class:`~astra_task.executor.worker_process.WorkerProcessExecutor`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import Task

__all__ = ["BackgroundExecutor"]


@runtime_checkable
class BackgroundExecutor(Protocol):
    """后台执行体接口（设计 §2.9）。

    演进路径（**接口不变**）：``InProcessBackgroundExecutor → WorkerProcessExecutor``。
    """

    def submit(self, task: Task, handler_key: str) -> None:
        """提交任务至执行体。

        Args:
            task: 待执行任务（:class:`~astra_task.models.Task`）。
            handler_key: 处理器键（如 ``agent.run`` / ``workflow.run`` / ``knowledge.index``）。
        """
        ...
