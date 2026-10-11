"""领域事件重导出。

🔴 事件基类**唯一**为 :class:`astra_core.events.DomainEvent`；
本模块**仅重导出**，不新增基类，使领域层可引用事件基类而**不依赖** ``astra_event``
（保持内层纯净，对齐 §2R.0.1 硬约束）。
"""

from __future__ import annotations

from astra_core import DomainEvent

__all__ = ["DomainEvent"]
