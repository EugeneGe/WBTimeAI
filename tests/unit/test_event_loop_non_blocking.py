"""事件循环**非阻塞**回归护栏（W8-3 / A38 裁定 §10.2-①②）。

两处确定性护栏（防回归）：

1. **路由护栏**：``run_agent`` **必须**为同步 ``def``（``async def`` = 同步 DB I/O 阻塞事件
   循环的反模式；本护栏固化 W8-3 修复，防止有人改回 ``async def``）；
2. **生成器护栏**：``stream_run`` 内 ``list_events`` 等同步点经 ``asyncio.to_thread`` 下沉
   线程池——注入含 ``time.sleep`` 的 fake，断言**其期间事件循环仍推进其他协程**（若同步直调
   则阻塞循环，其他协程无法推进）。

> 与 ``stream.py`` 的既有 ``asyncio.to_thread(deps.execute, ...)``（W6）一脉相承（裁定 §9-3）。
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any

from astra_api.routers.v1.agents import run_agent
from astra_api.sse.stream import StreamDeps, stream_run


def test_run_agent_route_is_synchronous() -> None:
    """``run_agent`` 为同步 ``def``（去 ``async``）——固定 W8-3 修复，防回归（裁定 §10.2-①）。"""
    assert not inspect.iscoroutinefunction(
        run_agent
    ), "run_agent 必须为同步 def：async def + 同步 DB I/O 会阻塞事件循环（W8-3 / A38）"
    assert inspect.isfunction(run_agent), type(run_agent)


class _FakeEventBus:
    """最小事件总线替身（记录订阅；无实时事件）。"""

    def __init__(self) -> None:
        self.subscriptions: dict[str, list[Any]] = {}

    def subscribe(self, domain_type: str, handler: Any) -> None:
        self.subscriptions.setdefault(domain_type, []).append(handler)

    def unsubscribe(self, domain_type: str, handler: Any) -> None:
        handlers = self.subscriptions.get(domain_type, [])
        if handler in handlers:
            handlers.remove(handler)


async def _drain_stream(deps: StreamDeps) -> list[str]:
    """驱动 ``stream_run`` 至结束，收集帧。"""
    frames: list[str] = []
    async for frame in stream_run(deps=deps, run_id="r1", start_execution=False):
        frames.append(frame)
    return frames


def test_stream_run_sinks_blocking_list_events_to_thread() -> None:
    """``stream_run`` 回放读经 ``to_thread``：``list_events`` 阻塞期间事件循环仍推进其他协程。"""
    block_seconds = 0.3
    started = threading.Event()
    released = threading.Event()

    def slow_list_events(run_id: str, last_event_id: int | None) -> list[Any]:
        # 模拟**阻塞式同步 DB 读**（若在事件循环上直调 → 阻塞整个循环）。
        started.set()
        time.sleep(block_seconds)
        released.set()
        return []

    deps = StreamDeps(
        event_bus=_FakeEventBus(),
        execute=lambda run_id: None,
        list_events=slow_list_events,
        cancel=lambda run_id: None,
        run_status=lambda run_id: "SUCCESS",  # 非执行模式 + 终态 → 纯回放后结束
    )

    async def scenario() -> int:
        consumer = asyncio.create_task(_drain_stream(deps))

        # 等待 ``list_events`` 进入阻塞窗口。
        while not started.is_set():
            await asyncio.sleep(0)

        # 阻塞窗口内计数：to_thread 下沉时循环空闲 → 计数持续推进；同步直调则计数≈0。
        ticks = 0
        while not released.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

        frames = await consumer
        assert frames == [], frames
        return ticks

    ticks = asyncio.run(scenario())
    # 证明事件循环在 ``list_events`` 阻塞期间仍被调度（非阻塞）。
    assert ticks >= 5, f"事件循环疑似被 list_events 阻塞（阻塞窗口内仅推进 {ticks} 次）"
