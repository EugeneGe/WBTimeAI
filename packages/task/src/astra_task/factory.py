"""task 组合工厂（**模式无关**）。"""

from __future__ import annotations

from .queue import InProcessTaskQueue
from .scheduler import LocalScheduler

__all__ = ["create_inprocess_task_queue", "create_local_scheduler"]


def create_inprocess_task_queue() -> InProcessTaskQueue:
    """创建进程内任务队列（模式无关）。"""
    return InProcessTaskQueue()


def create_local_scheduler() -> LocalScheduler:
    """创建本地调度器（懒启动；模式无关）。"""
    return LocalScheduler()
