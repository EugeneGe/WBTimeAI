"""Worker 启动与消费单测（W1 / T2-02；设计 §2.9 / ``I-P2-13``）。

覆盖：处理器注册表（四类任务）/ dispatch 未知处理器不崩 / 消费循环
（``dequeue → dispatch → ack``，注入桩处理器）/ ``--help`` 干跑。
"""

from __future__ import annotations

from typing import Any

import pytest
from astra_task import InProcessTaskQueue
from astra_worker import main as worker_main
from astra_worker.tasks import (
    AGENT_RUN_KEY,
    HANDLERS,
    KNOWLEDGE_INDEX_KEY,
    MAINTENANCE_CLEANUP_KEY,
    WORKFLOW_RUN_KEY,
    make_message,
)


def test_handlers_registry_has_four_task_types() -> None:
    """处理器注册表登记四类任务。

    🔴 W9 / T2-48 新增 ``maintenance.cleanup``（保留清理）处理器后为**四类**
    （原断言硬编三类；此处随实现补全——实现正确、旧断言过时，按 QA 路由自修）。
    """
    assert set(HANDLERS) == {
        "agent.run",
        "workflow.run",
        "knowledge.index",
        "maintenance.cleanup",
    }
    assert AGENT_RUN_KEY == "agent.run"
    assert WORKFLOW_RUN_KEY == "workflow.run"
    assert KNOWLEDGE_INDEX_KEY == "knowledge.index"
    assert MAINTENANCE_CLEANUP_KEY == "maintenance.cleanup"


class _FakeProviders:
    """最小 Providers 桩（仅消费 ``task_queue``）。"""

    def __init__(self, queue: Any) -> None:
        self.task_queue = queue


def test_run_worker_consumes_three_task_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker 消费三类任务（``dequeue → dispatch → ack``）。"""
    queue: InProcessTaskQueue[dict[str, Any]] = InProcessTaskQueue()
    recorded: list[str] = []

    def stub(message: dict[str, Any], ctx: Any) -> dict[str, Any]:
        recorded.append(str(message["handler"]))
        return {"ok": True}

    handlers = {AGENT_RUN_KEY: stub, WORKFLOW_RUN_KEY: stub, KNOWLEDGE_INDEX_KEY: stub}
    monkeypatch.setattr(worker_main, "build_providers", lambda settings: _FakeProviders(queue))

    for key in (AGENT_RUN_KEY, WORKFLOW_RUN_KEY, KNOWLEDGE_INDEX_KEY):
        queue.enqueue(make_message(key, {"x": 1}))

    processed = worker_main.run_worker(object(), stop_when_empty=True, handlers=handlers)
    assert processed == 3
    assert set(recorded) == {AGENT_RUN_KEY, WORKFLOW_RUN_KEY, KNOWLEDGE_INDEX_KEY}
    assert queue.size() == 0


def test_run_worker_unknown_handler_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """未知处理器：记失败但仍 ack（Worker 不崩）。"""
    queue: InProcessTaskQueue[dict[str, Any]] = InProcessTaskQueue()
    monkeypatch.setattr(worker_main, "build_providers", lambda settings: _FakeProviders(queue))
    queue.enqueue(make_message("unknown.task", {}))
    processed = worker_main.run_worker(object(), stop_when_empty=True, handlers={})
    assert processed == 1
    assert queue.size() == 0


def test_main_help_does_not_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``astra-worker --help`` 干跑（不装配 Providers）。"""
    monkeypatch.setattr("sys.argv", ["astra-worker", "--help"])
    worker_main.main()
    out = capsys.readouterr().out
    assert "Astra AI Worker" in out
