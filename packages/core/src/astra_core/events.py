"""领域事件基类。

所有领域事件继承 :class:`DomainEvent`，自动携带 ``event_id``（UUIDv7）与
``occurred_at``（UTC）。子类通过覆写类变量 ``type`` 声明事件类型，
例如 ``type = "user.registered"``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from astra_common.time import utcnow

from .id import generate_id

__all__ = ["DomainEvent"]


@dataclass
class DomainEvent:
    """领域事件基类。

    Attributes:
        event_id: 事件唯一标识（UUIDv7，来自 :func:`astra_core.id.generate_id`）。
        occurred_at: 事件发生时间（UTC）。
        payload: 事件载荷（须可 JSON 序列化）。
        type: 事件类型标识（类变量，子类覆写）。
        seq: **运行时**序列号（由 ``EventDispatcher`` 在**投递 / 落库前**统一分配；
            未绑定 Run 时保持 ``None``）——**加性字段**，不改变事件基类唯一性
            （W6 裁定 A26 §2.2 / §2.4.1）。
    """

    event_id: str = field(default_factory=generate_id)
    occurred_at: datetime = field(default_factory=utcnow)
    payload: dict[str, Any] = field(default_factory=dict)
    #: 运行时序列号（= ``agent_event.seq``；由 ``EventDispatcher`` 分配，缺省 ``None``）。
    seq: int | None = None

    #: 事件类型标识，子类覆写。
    type: ClassVar[str] = "domain.event"

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        return {
            "event_id": self.event_id,
            "type": self.type,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }
