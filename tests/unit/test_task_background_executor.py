"""后台执行体单测（W1 / T2-02；设计 §2.9 / R-23）。

覆盖：``InProcessBackgroundExecutor``（驱动 task 状态机 / 失败 / 未注册处理器）
与 ``WorkerProcessExecutor``（投递到队列 / 消息线格式）。
"""

from __future__ import annotations

from astra_task import (
    InProcessBackgroundExecutor,
    InProcessTaskQueue,
    Task,
    TaskStatus,
    WorkerProcessExecutor,
)


def test_inprocess_executor_drives_state_machine_success() -> None:
    """处理器正常返回 ⇒ 任务 ``SUCCESS`` 且写入 ``result``。"""
    executor = InProcessBackgroundExecutor(max_workers=2)
    executor.register_handler("demo", lambda task: {"done": True})
    task = Task(type="demo")
    try:
        executor.submit(task, "demo")
        executor.wait()
    finally:
        executor.shutdown()
    assert task.status is TaskStatus.SUCCESS
    assert task.result == {"done": True}


def test_inprocess_executor_marks_failed_on_exception() -> None:
    """处理器抛异常 ⇒ 任务 ``FAILED`` 且写入 ``error``。"""
    executor = InProcessBackgroundExecutor()
    executor.register_handler("boom", lambda task: (_ for _ in ()).throw(ValueError("nope")))
    task = Task(type="boom")
    try:
        executor.submit(task, "boom")
        executor.wait()
    finally:
        executor.shutdown()
    assert task.status is TaskStatus.FAILED
    assert "nope" in (task.error or "")


def test_inprocess_executor_unknown_handler_fails() -> None:
    """未注册处理器 ⇒ 任务 ``FAILED``（非静默）。"""
    executor = InProcessBackgroundExecutor()
    task = Task(type="missing")
    try:
        executor.submit(task, "missing")
        executor.wait()
    finally:
        executor.shutdown()
    assert task.status is TaskStatus.FAILED
    assert "未注册处理器" in (task.error or "")


def test_worker_process_executor_enqueues_message() -> None:
    """``WorkerProcessExecutor`` 把任务投递到队列（``CREATED → PENDING`` + 消息）。"""
    queue: InProcessTaskQueue[dict] = InProcessTaskQueue()
    executor = WorkerProcessExecutor(task_queue=queue)
    task = Task(type="agent.run", payload={"run_id": "r-1"})
    executor.submit(task, "agent.run")
    assert task.status is TaskStatus.PENDING
    message = queue.dequeue()
    assert message is not None
    assert message["handler"] == "agent.run"
    assert message["payload"] == {"run_id": "r-1"}
    assert message["task_id"] == task.task_id
