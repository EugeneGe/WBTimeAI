"""SSE 实时帧 ``id:`` == ``agent_event.seq`` 契约测试（W6 修复回归；裁定 A26 §2.2 / §2.4）。

固化 QA 探针 ``_qa_w6_probe_sse.py`` 的三段实验为**正式用例**，以**真实组件**
（``astra_event.LocalEventBus`` + ``astra_runtime.EventDispatcher`` +
``astra_api.sse.stream.stream_run``）驱动：

- **exp1**：进行中 Run 被**新订阅**（无 ``Last-Event-ID``）→ 实时帧 ``id`` == 真实 ``seq``
  （此前实现用本地计数器会错位/遗漏）；
- **exp2**：续传窗口「回放 + 实时重叠」→ 按 ``seq`` 去重，无重复、终态不错位；
- **exp3**：POST 快乐路径基线不变（``id`` == 真实 ``seq``）。

并断言 ``EventDispatcher.emit`` 在**投递前**把 ``seq`` 附着到事件（实时端可读真实 ``seq``）。
"""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

from astra_api.sse.stream import StreamDeps, stream_run
from astra_event import (
    AgentCompleted,
    AgentMessage,
    AgentStarted,
    AgentThinking,
    LocalEventBus,
)
from astra_runtime.event_dispatcher import EventDispatcher

_ID_RE = re.compile(r"^id: (\d+)$", re.MULTILINE)


def _ids(frames: list[str]) -> list[int]:
    """从帧序列提取数据帧 ``id:``（跳过心跳注释帧）。"""
    out: list[int] = []
    for frame in frames:
        if frame.startswith(": hb "):
            continue
        match = _ID_RE.search(frame)
        assert match is not None, f"数据帧缺 id: {frame!r}"
        out.append(int(match.group(1)))
    return out


# -- emit 契约：seq 在投递前附着到事件 --------------------------------------


def test_emit_attaches_seq_before_publish() -> None:
    """``EventDispatcher.emit`` 先分配 ``seq`` 并附着到投递给 ``bus`` 的事件。"""
    bus = LocalEventBus()
    seen_seq: list[int | None] = []
    seen_types: list[str] = []
    bus.subscribe("agent.started", lambda event: seen_seq.append(getattr(event, "seq", None)))
    bus.subscribe("agent.thinking", lambda event: seen_types.append(event.type))

    dispatcher = EventDispatcher(event_bus=bus, event_repository=None)
    dispatcher.bind("run-emit")
    dispatcher.emit(AgentStarted.create(run_id="run-emit", agent_id="a"))
    dispatcher.emit(AgentThinking.create(run_id="run-emit", iteration=1))

    # 实时端在**投递时**即可读到真实 seq（= 落库 seq）。
    assert seen_seq == [1]
    assert seen_types == ["agent.thinking"]
    assert [item["seq"] for item in dispatcher.snapshot_payloads()] == [1, 2]


# -- exp1：进行中新订阅（无 Last-Event-ID） ----------------------------------


def test_midrun_fresh_subscription_ids_match_real_seq() -> None:
    """进行中 Run 被新订阅：实时帧 ``id`` == 真实 ``seq``（不遗漏不错位）。"""
    bus = LocalEventBus()
    dispatcher = EventDispatcher(event_bus=bus, event_repository=None)
    dispatcher.bind("run-1")
    # 订阅者到达**之前**已发 3 个事件（真实 seq=1,2,3；未 flush → list_events 为空）。
    dispatcher.emit(AgentStarted.create(run_id="run-1", agent_id="a"))
    dispatcher.emit(AgentThinking.create(run_id="run-1", iteration=1))
    dispatcher.emit(
        AgentMessage.create(run_id="run-1", message_id="m1", role="assistant", content="hi")
    )

    deps = StreamDeps(
        event_bus=bus,
        execute=lambda run_id: None,
        list_events=lambda run_id, last: [],
        cancel=lambda run_id: None,
        run_status=lambda run_id: "RUNNING",
    )
    frames: list[str] = []

    async def driver() -> None:
        await asyncio.sleep(0.15)  # 确保订阅已挂上
        dispatcher.emit(AgentThinking.create(run_id="run-1", iteration=2))  # 真实 seq=4
        dispatcher.emit(AgentCompleted.create(run_id="run-1", duration_ms=1, iterations=2))  # seq=5

    async def collect() -> None:
        async for frame in stream_run(
            deps=deps,
            run_id="run-1",
            last_event_id=None,
            heartbeat_seconds=0.05,
            start_execution=False,
        ):
            frames.append(frame)

    async def scenario() -> None:
        await asyncio.wait_for(asyncio.gather(collect(), driver()), timeout=3.0)

    asyncio.run(scenario())
    # 实时帧 id 必须等于真实 seq（4,5），而非本地计数器（1,2）。
    assert _ids(frames) == [4, 5]
    assert [item["seq"] for item in dispatcher.snapshot_payloads()] == [1, 2, 3, 4, 5]


# -- exp2：续传窗口「回放 + 实时重叠」 ---------------------------------------


def test_resume_overlap_deduped_by_seq() -> None:
    """回放 seq=2,3 后，同一批事件经真实 ``EventDispatcher`` 重叠投递 → 按 seq 去重。

    期望 ``[2,3,4]``：``seq<=last_yielded`` 的实时事件丢弃，终态 ``seq=4`` 不放大。
    """
    bus = LocalEventBus()
    dispatcher = EventDispatcher(event_bus=bus, event_repository=None)
    dispatcher.bind("run-2")

    stored = [
        SimpleNamespace(seq=2, type="agent.thinking", payload={"run_id": "run-2", "iteration": 1}),
        SimpleNamespace(
            seq=3,
            type="agent.message",
            payload={"run_id": "run-2", "message_id": "m9", "role": "assistant", "content": "dup"},
        ),
    ]
    deps = StreamDeps(
        event_bus=bus,
        execute=lambda run_id: None,
        list_events=lambda run_id, last: list(stored),
        cancel=lambda run_id: None,
        run_status=lambda run_id: "RUNNING",
    )
    frames: list[str] = []

    async def driver() -> None:
        await asyncio.sleep(0.15)  # 订阅已挂上后再实时投递（含与回放重叠者）
        dispatcher.emit(
            AgentStarted.create(run_id="run-2", agent_id="a")
        )  # 真实 seq=1（回放窗口外）
        dispatcher.emit(AgentThinking.create(run_id="run-2", iteration=1))  # seq=2（与回放重叠）
        dispatcher.emit(  # seq=3（与回放重叠）
            AgentMessage.create(run_id="run-2", message_id="m9", role="assistant", content="dup")
        )
        dispatcher.emit(AgentCompleted.create(run_id="run-2", duration_ms=1, iterations=1))  # seq=4

    async def collect() -> None:
        async for frame in stream_run(
            deps=deps,
            run_id="run-2",
            last_event_id=1,
            heartbeat_seconds=0.05,
            start_execution=False,
        ):
            frames.append(frame)

    async def scenario() -> None:
        await asyncio.wait_for(asyncio.gather(collect(), driver()), timeout=3.0)

    asyncio.run(scenario())
    assert _ids(frames) == [2, 3, 4]


def test_overlap_deduped_for_seqless_events() -> None:
    """兜底：未经 ``EventDispatcher``（无 ``seq``）的事件按 ``(type,payload)`` 指纹去重。"""
    bus = LocalEventBus()
    stored = [
        SimpleNamespace(seq=2, type="agent.thinking", payload={"run_id": "run-2", "iteration": 1}),
        SimpleNamespace(
            seq=3,
            type="agent.message",
            payload={"run_id": "run-2", "message_id": "m9", "role": "assistant", "content": "dup"},
        ),
    ]
    deps = StreamDeps(
        event_bus=bus,
        execute=lambda run_id: None,
        list_events=lambda run_id, last: list(stored),
        cancel=lambda run_id: None,
        run_status=lambda run_id: "RUNNING",
    )
    frames: list[str] = []

    async def driver() -> None:
        await asyncio.sleep(0.15)
        # 原始领域事件（无 seq，绕过 EventDispatcher）——与回放同体。
        bus.publish(AgentThinking.create(run_id="run-2", iteration=1))
        bus.publish(
            AgentMessage.create(run_id="run-2", message_id="m9", role="assistant", content="dup")
        )
        bus.publish(AgentCompleted.create(run_id="run-2", duration_ms=1, iterations=1))

    async def collect() -> None:
        async for frame in stream_run(
            deps=deps,
            run_id="run-2",
            last_event_id=1,
            heartbeat_seconds=0.05,
            start_execution=False,
        ):
            frames.append(frame)

    async def scenario() -> None:
        await asyncio.wait_for(asyncio.gather(collect(), driver()), timeout=3.0)

    asyncio.run(scenario())
    assert _ids(frames) == [2, 3, 4]


# -- exp3：POST 快乐路径基线 -------------------------------------------------


def test_post_happy_path_ids_match_real_seq() -> None:
    """``start_execution=True`` 快乐路径：实时帧 ``id`` 与真实 ``seq`` 逐帧一致。"""
    bus = LocalEventBus()
    dispatcher = EventDispatcher(event_bus=bus, event_repository=None)

    def execute(run_id: str) -> None:
        dispatcher.bind(run_id)
        dispatcher.emit(AgentStarted.create(run_id=run_id, agent_id="a"))
        dispatcher.emit(AgentThinking.create(run_id=run_id, iteration=1))
        dispatcher.emit(
            AgentMessage.create(run_id=run_id, message_id="m", role="assistant", content="ok")
        )
        dispatcher.emit(AgentCompleted.create(run_id=run_id, duration_ms=1, iterations=1))

    deps = StreamDeps(
        event_bus=bus,
        execute=execute,
        list_events=lambda run_id, last: [],
        cancel=lambda run_id: None,
        run_status=lambda run_id: "RUNNING",
    )
    frames: list[str] = []

    async def collect() -> None:
        async for frame in stream_run(
            deps=deps,
            run_id="run-3",
            last_event_id=None,
            heartbeat_seconds=0.2,
            start_execution=True,
        ):
            frames.append(frame)

    asyncio.run(collect())
    assert _ids(frames) == [1, 2, 3, 4]
