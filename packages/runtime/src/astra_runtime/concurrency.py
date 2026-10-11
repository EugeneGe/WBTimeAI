"""``ConcurrencyController``（并发约束；设计 §2.7.2；W5 架构裁定 Q5 #6）。

**纯逻辑（Runtime 零 SQL）**：

- ``max_parallel_tools``：进程内信号量（纯逻辑）；
- ``max_runs_per_conversation``：经**注入的 SQL 仓储原子方法**
  （``AgentRunRepository.add_guarded``，内部 ``SELECT ... FOR UPDATE`` / SQLite 串行化）
  检查活跃 Run 数并建 Run；超限 → ``DomainError(CONFLICT)``（→ HTTP 409，**非静默排队**）。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from astra_domain import AgentRun, AgentRunRepository, ConcurrencyConfig

from .errors import run_conflict_error

__all__ = ["ConcurrencyController"]


class ConcurrencyController:
    """并发约束控制器（信号量 + 仓储原子方法编排）。"""

    def __init__(self, config: ConcurrencyConfig | None = None) -> None:
        self._config = config or ConcurrencyConfig()
        self._tool_semaphore = threading.Semaphore(self._config.max_parallel_tools)

    @property
    def max_parallel_tools(self) -> int:
        """最大并行工具数。"""
        return self._config.max_parallel_tools

    @property
    def max_runs_per_conversation(self) -> int:
        """同一会话最大活跃 Run 数。"""
        return self._config.max_runs_per_conversation

    @contextmanager
    def tool_slot(self) -> Iterator[None]:
        """获取一个并行工具槽位（``with`` 用法；纯逻辑信号量）。"""
        self._tool_semaphore.acquire()
        try:
            yield
        finally:
            self._tool_semaphore.release()

    def guard_run_creation(
        self,
        run_repository: AgentRunRepository,
        run: AgentRun,
        *,
        max_active: int | None = None,
    ) -> AgentRun:
        """原子地「检查活跃 Run 数 + 建 Run」。

        Args:
            run_repository: 注入的 ``AgentRunRepository``（含原子方法 ``add_guarded``）。
            run: 待创建的 Run。
            max_active: 覆盖默认阈值（缺省取 ``max_runs_per_conversation``）。

        Returns:
            落库后的 Run。

        Raises:
            DomainError: 创建后将超出阈值（``CONFLICT`` → 409）。
        """
        limit = self._config.max_runs_per_conversation if max_active is None else int(max_active)
        created = run_repository.add_guarded(run, max_active=limit)
        if created is None:
            raise run_conflict_error(
                "同一会话活跃 Run 数超限，拒绝新 Run",
                conversation_id=run.conversation_id,
                max_active=limit,
            )
        return created
