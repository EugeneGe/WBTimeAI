"""进程内任务队列单测（入队 / 出队 / ack / 尺寸）。"""

from __future__ import annotations

from astra_task import InProcessTaskQueue


def test_enqueue_dequeue_size() -> None:
    queue: InProcessTaskQueue[str] = InProcessTaskQueue()
    assert queue.size() == 0
    queue.enqueue("a")
    queue.enqueue("b")
    assert queue.size() == 2
    assert queue.dequeue() == "a"
    assert queue.size() == 1


def test_dequeue_empty_returns_none() -> None:
    assert InProcessTaskQueue().dequeue() is None


def test_ack_removes_from_in_flight() -> None:
    queue: InProcessTaskQueue[str] = InProcessTaskQueue()
    queue.enqueue("x")
    assert queue.dequeue() == "x"
    assert queue.in_flight() == 1
    queue.ack("x")
    assert queue.in_flight() == 0


def test_ack_unknown_item_is_noop() -> None:
    queue: InProcessTaskQueue[str] = InProcessTaskQueue()
    queue.ack("never-enqueued")
    assert queue.in_flight() == 0


def test_fifo_order() -> None:
    queue: InProcessTaskQueue[int] = InProcessTaskQueue()
    for i in range(3):
        queue.enqueue(i)
    assert [queue.dequeue() for _ in range(3)] == [0, 1, 2]
