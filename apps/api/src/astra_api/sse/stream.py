"""SSE 流生成器（W6 / T1-28；设计 §2.9；裁定 §2.2 / §2.4 / §2.6）。

职责：把「已持久化回放 + 实时订阅」编码为 SSE 帧序列，含心跳、续传（``Last-Event-ID`` /
``?after_seq``）、断连取消（INLINE 断连即取消）。

落 **``astra_api/sse/``**（**不在** ``routers/``）：本模块可 import
``astra_runtime`` / ``astra_conversation``（经 ``StreamDeps`` 回调注入，避免直连）。

- **回放**：先读 ``seq > last_event_id`` 的持久化事件；
- **实时**：订阅 ``EventBus``（handler 经 ``loop.call_soon_threadsafe`` 推入 ``asyncio.Queue``）；
- **心跳**：空闲超时 → 心跳注释帧（默认 15s，仅空闲时发，不带 ``id:``）；
- **去重**：实时事件**自带真实 ``seq``**（``EventDispatcher`` 投递前分配）——``seq <= last_yielded``
  丢弃；对未经 ``EventDispatcher``（无 ``seq``）发布的事件按 ``(type, payload)`` 指纹兜底去重；
- **收尾**：收到终态事件，或执行任务已结束且无待处理事件 → 结束循环；
- **断连**：生成器被提前关闭 / 取消 → ``deps.cancel(run_id)``（INLINE 断连即取消）。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from .encoder import SSE_CHANNEL_BY_DOMAIN_TYPE, encode_data_frame, encode_heartbeat

__all__ = ["StreamDeps", "stream_run"]

#: 订阅的领域事件类型（= 通道映射表的键）。
_DOMAIN_TYPES: tuple[str, ...] = tuple(SSE_CHANNEL_BY_DOMAIN_TYPE)

#: 进行中的 Run 状态（决定是否接续实时通道）。
_ACTIVE_STATUSES: frozenset[str] = frozenset({"PENDING", "RUNNING"})

#: Run 终态事件类型。
_TERMINAL_TYPES: frozenset[str] = frozenset({"agent.completed", "agent.failed"})


def _now_ms() -> int:
    """当前 Unix 毫秒。"""
    return int(time.time() * 1000)


def _frame_signature(domain_type: str, payload: dict[str, Any]) -> str:
    """计算实时事件的 ``(type, payload)`` 指纹（供**无 ``seq``** 事件兜底去重）。

    仅当事件未经 ``EventDispatcher``（无 ``seq``）时用于抑制回放/实时重叠窗口的重复投递；
    正常路径（事件自带 ``seq``）完全按 ``seq`` 去重，不依赖指纹。
    """
    try:
        return json.dumps([domain_type, payload], ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover - 载荷不可序列化时的退化路径
        return f"{domain_type}:{id(payload)}"


@dataclass
class StreamDeps:
    """SSE 流依赖（由组合根从 ``AppServices`` 抽取；测试可注入 fake）。

    Attributes:
        event_bus: 事件总线（``publish`` / ``subscribe`` / ``unsubscribe``）。
        execute: 执行一次 Run（``services.agent_run.execute``，阻塞）。
        list_events: 读 ``seq > last`` 的持久化事件（返回带 ``seq`` / ``type`` /
            ``payload`` 的 DTO）。
        cancel: 取消一次 Run（``services.agent_run.cancel``）。
        run_status: 读 Run 当前状态（供 GET 事件端点判断是否接续实时）。
        subscribe_types: 订阅的领域事件类型（缺省取通道映射表键集）。
    """

    event_bus: Any
    execute: Callable[[str], Any]
    list_events: Callable[[str, int | None], list[Any]]
    cancel: Callable[[str], Any]
    run_status: Callable[[str], str | None]
    subscribe_types: tuple[str, ...] = field(default_factory=lambda: _DOMAIN_TYPES)


async def stream_run(
    *,
    deps: StreamDeps,
    run_id: str,
    last_event_id: int | None = None,
    heartbeat_seconds: float = 15.0,
    start_execution: bool = False,
    completion_event: Any = None,
) -> AsyncIterator[str]:
    """产出某 Run 的 SSE 帧序列（回放 + 实时 + 心跳）。

    Args:
        deps: 流依赖（见 :class:`StreamDeps`）。
        run_id: 目标 Run 标识。
        last_event_id: 续传起点（``seq > last_event_id``；``None`` = 从头）。
        heartbeat_seconds: 心跳间隔（秒；仅空闲时发）。
        start_execution: 是否后台启动执行（``POST /agents/{id}/run`` 为真；
            ``GET /runs/{id}/events`` 为假——仅订阅既有执行）。
        completion_event: 可选的线程事件（测试 / 观测用；执行线程在终态置位）。

    Yields:
        编码后的 SSE 帧字符串（数据帧 / 心跳注释帧）。
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    yielded_seq = int(last_event_id) if last_event_id is not None else 0
    #: 已产出帧的 ``(type, payload)`` 指纹——供**无 ``seq``** 实时事件兜底去重。
    seen_signatures: set[str] = set()

    def _handler(event: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    for domain_type in deps.subscribe_types:
        deps.event_bus.subscribe(domain_type, _handler)

    task: asyncio.Task[Any] | None = None
    terminal = False
    try:
        # 1) 先回放持久化事件（seq > last）。
        #    W8-3 / A38：``list_events`` 为同步 DB 读——经 ``asyncio.to_thread`` 下沉线程池，
        #    避免在事件循环上直接做 DB 往返（消除循环阻塞）。
        stored_events = await asyncio.to_thread(deps.list_events, run_id, last_event_id)
        for stored in stored_events:
            seq = int(getattr(stored, "seq", 0))
            if seq <= yielded_seq:
                continue
            stored_type = str(getattr(stored, "type", ""))
            stored_payload = dict(getattr(stored, "payload", {}) or {})
            frame = encode_data_frame(
                seq=seq,
                domain_type=stored_type,
                payload=stored_payload,
            )
            if frame is not None:
                yielded_seq = seq
                seen_signatures.add(_frame_signature(stored_type, stored_payload))
                yield frame

        # 2) 非执行模式且 Run 已终态 → 纯回放结束。
        #    W8-3 / A38：``run_status`` 为同步 DB 读——同样下沉线程池。
        if not start_execution:
            status = await asyncio.to_thread(deps.run_status, run_id)
            if status not in _ACTIVE_STATUSES:
                return

        # 3) 后台执行（INLINE）：Runtime 同步，于工作线程运行。
        if start_execution:
            task = asyncio.create_task(asyncio.to_thread(deps.execute, run_id))

        # 4) 实时帧循环（心跳 + 编码 + 去重 + 终态 / 执行结束检测）。
        while not terminal:
            event = await _next_event(queue, task, heartbeat_seconds)
            if event is _HEARTBEAT:
                yield encode_heartbeat(now_ms=_now_ms())
                continue
            if event is _EXECUTION_DONE:
                break
            domain_type = str(getattr(event, "type", ""))
            payload = dict(getattr(event, "payload", {}) or {})
            raw_seq = getattr(event, "seq", None)
            if raw_seq is not None:
                # 实时事件自带真实 ``agent_event.seq``（``EventDispatcher`` 分配）：
                # ``seq <= last_yielded`` 丢弃（裁定 §2.4.2）——回放/实时重叠不重复。
                seq = int(raw_seq)
                if seq <= yielded_seq:
                    continue
                yielded_seq = seq
            else:
                # 兜底：未经 ``EventDispatcher``（无 ``seq``）发布的事件按 ``(type, payload)``
                # 指纹去重，避免与回放窗口重叠时重复投递；编号回退本地自增。
                signature = _frame_signature(domain_type, payload)
                if signature in seen_signatures:
                    continue
                yielded_seq += 1
                seen_signatures.add(signature)
            frame = encode_data_frame(
                seq=yielded_seq,
                domain_type=domain_type,
                payload=payload,
            )
            if frame is not None:
                yield frame
            if domain_type in _TERMINAL_TYPES:
                terminal = True

        if task is not None:
            try:
                await task
            except Exception:  # noqa: BLE001 - 执行失败已在收尾处理，不阻断生成器
                pass
    finally:
        for domain_type in deps.subscribe_types:
            deps.event_bus.unsubscribe(domain_type, _handler)
        if completion_event is not None:
            try:
                completion_event.set()
            except Exception:  # noqa: BLE001
                pass
        if not terminal and start_execution:
            # INLINE 断连 / 取消 → 触发 CancelAgentRun（置取消信号）。
            # W8-3 / A38：``cancel`` 为同步 DB 写——下沉线程池，避免断连清理阻塞循环。
            try:
                await asyncio.to_thread(deps.cancel, run_id)
            except Exception:  # noqa: BLE001 - 断连清理不阻断
                pass


#: 心跳哨兵。
_HEARTBEAT = object()

#: 执行结束哨兵（任务已完成且无更多事件）。
_EXECUTION_DONE = object()


async def _next_event(
    queue: asyncio.Queue[Any],
    task: asyncio.Task[Any] | None,
    heartbeat_seconds: float,
) -> Any:
    """等待下一个实时事件；空闲超时返回心跳哨兵，执行结束且无事件返回结束哨兵。"""
    getter = asyncio.ensure_future(queue.get())
    waiters: set[asyncio.Future[Any]] = {getter}
    if task is not None:
        waiters.add(task)
    try:
        done, _pending = await asyncio.wait(
            waiters, timeout=heartbeat_seconds, return_when=asyncio.FIRST_COMPLETED
        )
    except asyncio.CancelledError:
        getter.cancel()
        raise

    if getter in done:
        return getter.result()

    getter.cancel()
    # 执行任务已结束且队列已空 → 收尾（无读者时不强求终态帧）。
    if task is not None and task in done:
        # 让同事件循环内待处理的 ``call_soon_threadsafe`` 回调落地后再判定。
        for _ in range(2):
            await asyncio.sleep(0)
            if not queue.empty():
                break
        if queue.empty():
            return _EXECUTION_DONE
        return queue.get_nowait()
    return _HEARTBEAT
