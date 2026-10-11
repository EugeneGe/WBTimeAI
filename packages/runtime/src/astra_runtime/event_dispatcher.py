"""``EventDispatcher``（9 类事件 → ``EventBus`` + 落 ``agent_event``；设计 §2.7 / §2.8）。

**双通道**（设计 §2.7.2 / §5 #13）：

- **实时**：``EventBus.publish(event)``（进程内分发；事件携带**已分配**的 ``seq``）；
- **落库**：聚合到缓冲，:meth:`flush` 时经 **DI 注入**的 ``AgentEventRepository``
  **批量**写入 ``agent_event``（``seq`` 按 Run 单调递增）——SQL 在 Conversation 组仓储。

``seq`` 由 :meth:`EventDispatcher.emit` 在**投递与入缓冲之前**统一分配并附着到事件
（``DomainEvent.seq``，加性字段），使实时订阅端可直接读出真实 ``agent_event.seq``
（W6 裁定 A26 §2.2 / §2.4.1）。

🔴 Runtime 侧**零 SQL**：仅经领域 Protocol 注入仓储（W5 架构裁定 Q1）。

**per-run 状态隔离（W7 / 台账 C7）**：本类**可被组合根按进程单例共享**——组合根
``AgentRuntime.build`` 只建**一个** ``EventDispatcher``，并挂到 ``app.state.services``，
由 SSE 经 ``asyncio.to_thread`` **并发**驱动多个 Run。故 ``seq`` / 缓冲 / 追踪字段按
``run_id`` **分区存储**（:class:`_RunScope`），一个 Run 的 :meth:`bind` / :meth:`emit`
**不再**覆盖另一个 Run 的状态，杜绝跨会话串扰。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainEvent
from astra_domain import AgentEvent, AgentEventRepository
from astra_event import EventBus

__all__ = ["EventDispatcher"]


@dataclass
class _RunScope:
    """单个 Run 的事件流状态（与其它 Run 完全隔离）。

    Attributes:
        trace_id: 该 Run 的追踪标识（附着到落库事件）。
        span_id: 该 Run 的 span 标识（附着到落库事件）。
        seq: 该 Run 的**下一个** ``seq`` 分配游标（已分配数）。
        buffer: 该 Run 尚未落库的事件缓冲。
    """

    trace_id: str | None = None
    span_id: str | None = None
    seq: int = 0
    buffer: list[AgentEvent] = field(default_factory=list)


class EventDispatcher:
    """Agent 生命周期事件分发器（实时 + 批量落库；per-run 状态隔离）。"""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        event_repository: AgentEventRepository | None = None,
    ) -> None:
        self._bus = event_bus
        self._repository = event_repository
        self._run_id: str | None = None
        # W7 / C7：按 ``run_id`` 分区的流状态——单实例多 Run 并发绑定互不覆盖。
        self._scopes: dict[str, _RunScope] = {}

    # -- 绑定 ---------------------------------------------------------------

    def bind(
        self,
        run_id: str,
        *,
        trace_id: str | None = None,
        span_id: str | None = None,
        start_seq: int = 0,
    ) -> None:
        """绑定当前 Run（**仅**重置该 ``run_id`` 的 ``seq`` 与缓冲；不影响其它 Run）。"""
        self._run_id = run_id
        self._scopes[run_id] = _RunScope(
            trace_id=trace_id,
            span_id=span_id,
            seq=int(start_seq),
        )

    def _scope_for(self, run_id: str) -> _RunScope:
        """取得（必要时惰性创建）某 Run 的流状态。"""
        scope = self._scopes.get(run_id)
        if scope is None:
            scope = _RunScope()
            self._scopes[run_id] = scope
        return scope

    @property
    def run_id(self) -> str | None:
        """当前绑定的 Run 标识。"""
        return self._run_id

    @property
    def pending(self) -> int:
        """**当前绑定 Run** 尚未落库的事件数（无绑定时为 ``0``）。"""
        if self._run_id is None:
            return 0
        scope = self._scopes.get(self._run_id)
        return 0 if scope is None else len(scope.buffer)

    # -- 发送 ---------------------------------------------------------------

    def emit(self, event: DomainEvent, *, run_id: str | None = None) -> AgentEvent:
        """发布事件到 ``EventBus`` 并暂存待落库实体（返回暂存实体）。

        **``seq`` 分配时机**（W6 / A26 §2.4.1）：先自增**该 Run** 的 ``seq`` 并**附着到事件**
        （``DomainEvent.seq``），再入该 Run 的缓冲、后 ``publish``——使**实时订阅端**
        （``EventBus`` 处理器）拿到的即是携带**真实 ``agent_event.seq``** 的事件，SSE 帧
        ``id:`` 与之逐帧一致（裁定 §2.2）。``EventBus.publish(event)`` 语义不变（仍投递
        ``DomainEvent``；``seq`` 为加性字段）。

        ``seq`` / 缓冲 / 追踪字段均按 ``run_id`` 分区（W7 / C7），跨 Run 互不影响。
        """
        target_run = run_id or self._run_id
        if not target_run:
            raise ValueError("EventDispatcher 未绑定 run_id")
        scope = self._scope_for(target_run)
        scope.seq += 1
        seq = scope.seq
        # 实时端（bus 订阅者）与落库端共用同一 ``seq``（投递前分配）。
        event.seq = seq
        stored = AgentEvent(
            run_id=target_run,
            seq=seq,
            type=event.type,
            payload=dict(event.payload),
            trace_id=scope.trace_id,
            span_id=scope.span_id,
        )
        scope.buffer.append(stored)
        self._bus.publish(event)
        return stored

    # -- 落库 ---------------------------------------------------------------

    def flush(self, run_id: str | None = None) -> list[AgentEvent]:
        """把**目标 Run** 的缓冲事件**批量**写入 ``agent_event`` 并清空该 Run 状态。

        落库后**移除**该 Run 的流状态（:attr:`_scopes`），使共享单例的常驻内存不随
        历史 Run 数无界增长；组合根于每个 Run 起始即 :meth:`bind`（``start_seq=0``），
        故移除不为任何实际调用点引入语义变化。

        Args:
            run_id: 目标 Run（缺省取当前绑定 Run；供并发场景显式指定）。
        """
        target = run_id or self._run_id
        if target is None or self._repository is None:
            return []
        scope = self._scopes.get(target)
        if scope is None or not scope.buffer:
            return []
        persisted = self._repository.add_many(list(scope.buffer))
        self._scopes.pop(target, None)
        return persisted

    def snapshot_payloads(self, run_id: str | None = None) -> list[dict[str, Any]]:
        """返回**目标 Run** 缓冲事件的 ``{seq, type, payload}`` 快照（供测试 / 观测）。

        Args:
            run_id: 目标 Run（缺省取当前绑定 Run）。
        """
        target = run_id or self._run_id
        if target is None:
            return []
        scope = self._scopes.get(target)
        if scope is None:
            return []
        return [
            {"seq": event.seq, "type": event.type, "payload": dict(event.payload)}
            for event in scope.buffer
        ]
