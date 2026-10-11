"""Astra AI Worker（``astra_worker``）——后台任务消费者（W1 / T2-02；设计 §2.9 / §2.16）。

**工程范式切换**：单进程 → 多进程。独立进程经 :func:`astra_config.providers.build_providers`
取 ``Providers``（**唯一装配**），注册处理器并消费队列（``dequeue → dispatch → ack``）。

🔴 执行体 / 队列**正交**（R-23）：本进程**只**消费 :class:`Providers.task_queue` 的消息，
   不判断 ``ASTRA_MODE``（唯一分流点在 ``build_providers``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["HandlerContext", "__version__"]

__version__ = "0.4.0"

# 注：租约 / 恢复接线（``LeaseManager`` / ``ClaimOutcome`` / ``RecoveryReport``）落
# ``astra_worker.recovery`` 子模块（**不**在包门面再导出，避免包导入期拉入 ``sqlalchemy``
# 异常类型；需要时 ``from astra_worker.recovery import LeaseManager``）。


@dataclass
class HandlerContext:
    """处理器执行上下文（注入 Providers 与可选服务）。

    Attributes:
        providers: 组合根装配的 :class:`~astra_config.providers.Providers`。
        services: 可选的用例服务映射（键如 ``execute_agent``）；W1 默认空，
            重型逻辑（Runtime 装配）归后续波次经组合根注入。
    """

    providers: Any
    services: dict[str, Any] = field(default_factory=dict)
