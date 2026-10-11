"""``EventDispatcher`` per-run 状态隔离断言（W7 / 台账 C7）。

固化「单实例被多 Run 共享时，一个 Run 的 ``bind`` / ``emit`` **不**覆盖另一个 Run 的
``seq`` / 缓冲 / 追踪字段」——组合根 ``AgentRuntime.build`` 只建**一个** dispatcher 挂
``app.state.services``，SSE 经 ``asyncio.to_thread`` 并发驱动多 Run，故须隔离。

纯单测（无需 DB）：以 ``LocalEventBus`` + 内存记录仓储驱动。
"""

from __future__ import annotations

import pytest
from astra_domain import AgentEvent
from astra_event import AgentCompleted, AgentStarted, AgentThinking, LocalEventBus
from astra_runtime import EventDispatcher


class _RecordingRepository:
    """记录 ``add_many`` 调用的内存事件仓储（实现 ``AgentEventRepository`` 子集）。"""

    def __init__(self) -> None:
        self.calls: list[list[AgentEvent]] = []

    def add_many(self, events: list[AgentEvent]) -> list[AgentEvent]:
        copied = list(events)
        self.calls.append(copied)
        return copied

    # 其余 Protocol 方法本用例不触达。
    def list_by_run(self, run_id: str) -> list[AgentEvent]:  # pragma: no cover
        raise NotImplementedError

    def list_after_seq(self, run_id: str, last_event_id: int | None = None) -> list[AgentEvent]:
        raise NotImplementedError  # pragma: no cover


def test_per_run_state_isolation_no_crosstalk() -> None:
    """run-A 未 flush 时 run-B ``bind``：run-A 的 seq/缓冲/追踪不被覆盖。"""
    repo = _RecordingRepository()
    dispatcher = EventDispatcher(event_bus=LocalEventBus(), event_repository=repo)

    dispatcher.bind("run-A", trace_id="trace-A")
    dispatcher.emit(AgentStarted.create(run_id="run-A", agent_id="a"), run_id="run-A")

    # run-B 在 run-A 尚未 flush 时绑定并发送事件。
    dispatcher.bind("run-B", trace_id="trace-B")
    dispatcher.emit(AgentStarted.create(run_id="run-B", agent_id="b"), run_id="run-B")
    dispatcher.emit(AgentThinking.create(run_id="run-B", iteration=1), run_id="run-B")

    # run-A 随后继续发送（``ExecutionManager`` 亦显式传 ``run_id``）：seq 应从 run-A 的
    # 游标递增（=2），而非被 run-B 重置。
    dispatcher.emit(
        AgentCompleted.create(run_id="run-A", duration_ms=1, iterations=1), run_id="run-A"
    )

    a_events = dispatcher.flush("run-A")
    b_events = dispatcher.flush("run-B")

    # 两 Run 各自独立从 seq=1 递增，互不串号。
    assert [event.seq for event in a_events] == [1, 2]
    assert [event.seq for event in b_events] == [1, 2]
    # 追踪字段按 Run 分区，不互相污染。
    assert all(e.run_id == "run-A" and e.trace_id == "trace-A" for e in a_events)
    assert all(e.run_id == "run-B" and e.trace_id == "trace-B" for e in b_events)


def test_bind_does_not_discard_other_run_buffer() -> None:
    """``bind`` 仅重置目标 Run 状态；``pending`` 反映当前绑定 Run 的待落库数。"""
    dispatcher = EventDispatcher(event_bus=LocalEventBus())

    dispatcher.bind("run-A")
    dispatcher.emit(AgentThinking.create(run_id="run-A", iteration=1), run_id="run-A")
    assert dispatcher.pending == 1

    dispatcher.bind("run-B")
    assert dispatcher.pending == 0  # run-B 自身为空
    # run-A 的缓冲未被 run-B 的 bind 清空。
    assert [item["seq"] for item in dispatcher.snapshot_payloads("run-A")] == [1]


def test_emit_without_bind_requires_run_id() -> None:
    """未绑定且未显式传 ``run_id`` → 抛 ``ValueError``（既有语义不变）。"""
    dispatcher = EventDispatcher(event_bus=LocalEventBus())
    with pytest.raises(ValueError):
        dispatcher.emit(AgentThinking.create(run_id="run-x", iteration=1))


def test_flush_clears_scope_after_persist() -> None:
    """落库后移除该 Run 状态（常驻内存不随历史 Run 数无界增长）。"""
    repo = _RecordingRepository()
    dispatcher = EventDispatcher(event_bus=LocalEventBus(), event_repository=repo)
    dispatcher.bind("run-A")
    dispatcher.emit(AgentThinking.create(run_id="run-A", iteration=1), run_id="run-A")
    persisted = dispatcher.flush("run-A")

    assert len(persisted) == 1
    assert dispatcher.snapshot_payloads("run-A") == []
    # 再次 flush（无缓冲）为空，且不重复落库。
    assert dispatcher.flush("run-A") == []
    assert len(repo.calls) == 1
