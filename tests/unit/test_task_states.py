"""任务状态机单测（合法 / 非法转移）——设计 §3-#9。"""

from __future__ import annotations

import pytest
from astra_core import DomainError
from astra_task import ALLOWED_TRANSITIONS, Task, TaskStatus, can_transition


def test_legal_transitions() -> None:
    assert can_transition(TaskStatus.CREATED, TaskStatus.PENDING)
    assert can_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.SUCCESS)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.FAILED)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.CANCELLED)


def test_terminal_states_have_no_transitions() -> None:
    for terminal in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
        assert ALLOWED_TRANSITIONS[terminal] == frozenset()


def test_illegal_transition_is_defined_false() -> None:
    # INLINE 路径 CREATED → RUNNING 现为合法（T1-26 / §2.11）。
    assert can_transition(TaskStatus.CREATED, TaskStatus.RUNNING) is True
    assert can_transition(TaskStatus.SUCCESS, TaskStatus.RUNNING) is False
    assert can_transition(TaskStatus.CREATED, TaskStatus.SUCCESS) is False


def test_start_inline_skips_pending() -> None:
    """INLINE 路径：``CREATED → RUNNING → 终态``（跳过 PENDING）——``I-P1-12``。"""
    task = Task(type="agent.run", execution_mode="INLINE")
    assert task.status is TaskStatus.CREATED
    task.start_inline()
    assert task.status is TaskStatus.RUNNING
    task.succeed({"ok": True})
    assert task.status is TaskStatus.SUCCESS


def test_queued_path_sequence() -> None:
    """QUEUED 路径：``CREATED → PENDING → RUNNING → 终态``——``I-P1-12``。"""
    task = Task(type="agent.run", execution_mode="QUEUED")
    assert task.status is TaskStatus.CREATED
    task.enqueue()
    assert task.status is TaskStatus.PENDING
    task.start()
    assert task.status is TaskStatus.RUNNING
    task.succeed()
    assert task.status is TaskStatus.SUCCESS


def test_task_happy_path() -> None:
    task = Task(type="demo", tenant_id="t1")
    assert task.status is TaskStatus.CREATED
    task.enqueue()
    assert task.status is TaskStatus.PENDING
    task.start()
    assert task.status is TaskStatus.RUNNING
    task.succeed({"ok": True})
    assert task.status is TaskStatus.SUCCESS
    assert task.result == {"ok": True}


def test_task_fail_path() -> None:
    task = Task(type="demo")
    task.enqueue()
    task.start()
    task.fail("boom")
    assert task.status is TaskStatus.FAILED
    assert task.error == "boom"


def test_illegal_transition_raises_domain_error() -> None:
    task = Task(type="demo")
    with pytest.raises(DomainError):
        task.start()  # CREATED → RUNNING 非法


def test_cancel_from_created() -> None:
    task = Task(type="demo")
    task.cancel()
    assert task.status is TaskStatus.CANCELLED
