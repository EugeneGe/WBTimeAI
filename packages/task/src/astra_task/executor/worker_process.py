"""``WorkerProcessExecutor``——Team 后台执行体（W1 / T2-02；设计 §2.9）。

**薄执行体**：把「处理器键 + 载荷」投递到注入的 :class:`~astra_task.queue.TaskQueue`
（Team 为 :class:`~astra_task.queue.redis.RedisTaskQueue`），由独立进程
``apps/worker`` 消费（``dequeue → dispatch → ack``）。

🔴 **执行体 / 队列正交**：本执行体**只**负责「在哪跑」（独立 Worker 进程），不关心
   任务如何传递（由注入的 ``task_queue`` 决定）。
"""

from __future__ import annotations

from typing import Any

from ..models import Task
from ..states import TaskStatus

__all__ = ["WorkerProcessExecutor"]


class WorkerProcessExecutor:
    """把处理器投递到队列、交由 ``apps/worker`` 消费的执行体（Team）。

    Attributes:
        task_queue: 注入的任务队列（``enqueue`` 语义）。
    """

    def __init__(self, *, task_queue: Any) -> None:
        """构造执行体。

        Args:
            task_queue: 注入的任务队列（Team 为 RedisTaskQueue）。
        """
        self._task_queue = task_queue

    @property
    def task_queue(self) -> Any:
        """注入的任务队列（只读）。"""
        return self._task_queue

    def submit(self, task: Task, handler_key: str) -> None:
        """把任务投递到队列（``CREATED → PENDING`` 后入队）。

        Args:
            task: 待执行任务。
            handler_key: 处理器键。
        """
        if task.status is TaskStatus.CREATED:
            task.enqueue()
        message: dict[str, Any] = {
            "handler": handler_key,
            "task_id": task.task_id,
            "tenant_id": task.tenant_id,
            "workspace_id": task.workspace_id,
            "payload": dict(task.payload),
        }
        self._task_queue.enqueue(message)

    def shutdown(self, wait: bool = False) -> None:  # noqa: ARG002 - 队列由组合根管理
        """关闭执行体（无副作用；队列生命周期归组合根）。"""
