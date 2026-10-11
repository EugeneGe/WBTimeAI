"""SSE 回放 / 续传 / 心跳 / 断连集成测试（W6 / T1-28；裁定 Q2/A26）。

以 **fake 依赖** 直接驱动 :func:`astra_api.sse.stream.stream_run`（``asyncio.run``，
无 pytest-asyncio 依赖），断言：

- **回放**：先读 ``seq > last_event_id`` 的持久化事件（无重复）；
- **去重**：``seq <= last_event_id`` 丢弃；
- **心跳**：空闲超时发注释帧（``: hb <ms>``，无 ``id:``）；
- **终态收尾**：收到 ``agent.completed`` → 循环结束；
- **断连取消**：生成器提前关闭且 ``start_execution=True`` → ``deps.cancel(run_id)``；
- **续传解析**：``Last-Event-ID`` 头**优先**于 ``?after_seq``。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from astra_api.routers.v1.runs import _history_id
from astra_api.sse.stream import StreamDeps, stream_run


class FakeBus:
    """最小事件总线（记录 handler；``publish`` 同步回调）。"""

    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}

    def subscribe(self, domain_type: str, handler: Any) -> None:
        self.handlers.setdefault(domain_type, []).append(handler)

    def unsubscribe(self, domain_type: str, handler: Any) -> None:
        try:
            self.handlers.get(domain_type, []).remove(handler)
        except ValueError:  # pragma: no cover - 未注册
            pass

    def publish(self, event: Any) -> None:
        for handler in list(self.handlers.get(getattr(event, "type", ""), [])):
            handler(event)


def _stored(seq: int, domain_type: str, payload: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(seq=seq, type=domain_type, payload=payload or {})


def _deps(
    bus: FakeBus,
    *,
    stored: list[Any] | None = None,
    run_status: str = "SUCCESS",
    cancel: Any = None,
) -> StreamDeps:
    return StreamDeps(
        event_bus=bus,
        execute=lambda run_id: None,
        list_events=lambda run_id, last: list(stored or []),
        cancel=cancel or (lambda run_id: None),
        run_status=lambda run_id: run_status,
    )


# -- 回放 / 去重 -------------------------------------------------------------


def test_stream_replays_only_after_last_event_id() -> None:
    """``last_event_id=1`` → 仅回放 ``seq`` 2 / 3（``seq`` 1 丢弃）。"""
    bus = FakeBus()
    stored = [
        _stored(1, "agent.started"),
        _stored(2, "agent.thinking", {"iteration": 1}),
        _stored(3, "agent.completed", {}),
    ]

    async def scenario() -> list[str]:
        deps = _deps(bus, stored=stored, run_status="SUCCESS")
        return [
            frame
            async for frame in stream_run(
                deps=deps, run_id="r1", last_event_id=1, start_execution=False
            )
        ]

    frames = asyncio.run(scenario())
    ids = [line for frame in frames for line in frame.splitlines() if line.startswith("id: ")]
    assert ids == ["id: 2", "id: 3"]


# -- 心跳 + 终态收尾 ---------------------------------------------------------


def test_stream_emits_heartbeat_then_stops_on_terminal() -> None:
    """空回放 + 活跃 Run：先发心跳注释帧，收到 ``agent.completed`` 后收尾。"""
    bus = FakeBus()

    async def scenario() -> list[str]:
        deps = _deps(bus, stored=[], run_status="RUNNING", cancel=lambda run_id: None)

        async def emit() -> None:
            await asyncio.sleep(0.05)
            bus.publish(SimpleNamespace(type="agent.completed", payload={"run_id": "r1"}))

        frames: list[str] = []

        async def collect() -> None:
            async for frame in stream_run(
                deps=deps, run_id="r1", heartbeat_seconds=0.01, start_execution=False
            ):
                frames.append(frame)

        await asyncio.wait_for(asyncio.gather(collect(), emit()), timeout=2.0)
        return frames

    frames = asyncio.run(scenario())
    assert any(frame.startswith(": hb ") for frame in frames)
    assert any("event: agent.completed" in frame for frame in frames)


# -- 断连取消 ----------------------------------------------------------------


def test_stream_cancels_run_on_early_disconnect() -> None:
    """生成器提前关闭且 ``start_execution=True`` → 触发 ``deps.cancel(run_id)``。"""
    bus = FakeBus()
    cancelled: list[str] = []

    async def scenario() -> str:
        deps = _deps(
            bus, stored=[_stored(1, "agent.started")], run_status="RUNNING", cancel=cancelled.append
        )
        agen: Any = stream_run(
            deps=deps, run_id="run-9", heartbeat_seconds=5.0, start_execution=True
        )
        first = await agen.__anext__()
        await agen.aclose()
        return first

    first = asyncio.run(scenario())
    assert "id: 1" in first
    assert cancelled == ["run-9"]


# -- 续传起点解析（``Last-Event-ID`` 优先） ----------------------------------


def test_history_id_prefers_last_event_id_header() -> None:
    """``Last-Event-ID`` 头优先；``?after_seq`` 回退；均缺省 → ``None``。"""
    assert _history_id("7", 3) == 7
    assert _history_id(None, 3) == 3
    assert _history_id(None, None) is None
    assert _history_id("not-an-int", 5) is None
