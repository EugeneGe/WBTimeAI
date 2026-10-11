"""事件总线发布 / 订阅冒烟测试（设计 §3-#8）。"""

from __future__ import annotations

from astra_event import (
    EventDispatcher,
    LocalEventBus,
    UserRegistered,
    create_local_event_bus,
    handler_for,
)


def test_publish_subscribe_smoke() -> None:
    bus = LocalEventBus()
    received: list[UserRegistered] = []

    @handler_for("user.registered")
    def on_registered(event: UserRegistered) -> None:
        received.append(event)

    bus.subscribe("user.registered", on_registered)
    bus.publish(UserRegistered.create(user_id="u-1", tenant_id="t-1"))

    assert len(received) == 1
    assert received[0].payload["user_id"] == "u-1"


def test_unsubscribe_stops_delivery() -> None:
    bus = create_local_event_bus()
    hits: list[str] = []

    def handler(event: UserRegistered) -> None:
        hits.append(event.type)

    bus.subscribe("user.registered", handler)
    bus.publish(UserRegistered.create(user_id="u-1"))
    bus.unsubscribe("user.registered", handler)
    bus.publish(UserRegistered.create(user_id="u-2"))
    assert hits == ["user.registered"]


def test_exception_isolation_between_handlers() -> None:
    dispatcher = EventDispatcher()
    seen: list[str] = []

    def boom(_event) -> None:
        raise RuntimeError("handler failure")

    def ok(event) -> None:
        seen.append(event.type)

    dispatcher.register("user.registered", boom)
    dispatcher.register("user.registered", ok)
    dispatcher.dispatch(UserRegistered.create(user_id="u-1"))
    assert seen == ["user.registered"]


def test_async_handler_via_publish_async() -> None:
    import asyncio

    bus = LocalEventBus()
    seen: list[str] = []

    async def handler(event) -> None:
        seen.append(event.type)

    bus.subscribe("user.registered", handler)
    asyncio.run(bus.publish_async(UserRegistered.create(user_id="u-1")))
    assert seen == ["user.registered"]
