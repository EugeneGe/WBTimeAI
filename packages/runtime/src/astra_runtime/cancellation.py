"""``CancellationManager``（取消传播 → ``SandboxProvider.destroy()`` 幂等；设计 §2.7.2）。

**硬约束（§5 #5）**：取消 / 超时 / 断连 → **必须**调用 ``SandboxProvider.destroy()``
（幂等，由 Provider 实现保证）；``≤30s`` 内生效（回收时限校验）。

🔴 Runtime 侧**零 SQL**：仅调用注入的 ``SandboxProvider`` 抽象接口（``astra_sandbox``）。
"""

from __future__ import annotations

from typing import Any

__all__ = ["CancellationManager", "DEFAULT_RECLAIM_TIMEOUT_S"]

#: 沙箱回收时限（秒）——超时未回收即视为泄漏。
DEFAULT_RECLAIM_TIMEOUT_S = 30


class CancellationManager:
    """取消传播与沙箱回收管理器。"""

    def __init__(
        self,
        *,
        sandbox_provider: Any = None,
        reclaim_timeout_s: int = DEFAULT_RECLAIM_TIMEOUT_S,
    ) -> None:
        self._sandbox = sandbox_provider
        self._reclaim_timeout_s = int(reclaim_timeout_s)

    @property
    def reclaim_timeout_s(self) -> int:
        """回收时限（秒）。"""
        return self._reclaim_timeout_s

    def destroy_session(self, session: Any) -> bool:
        """销毁单个沙箱会话（幂等：无 Provider / 无会话时静默返回 ``False``）。"""
        if session is None or self._sandbox is None:
            return False
        self._sandbox.destroy(session)
        return True

    def cancel(self, sessions: Any) -> int:
        """取消传播：销毁给定会话集合（幂等）。

        Args:
            sessions: 单个会话或会话可迭代对象（``None`` 亦允许）。

        Returns:
            实际销毁的会话数。
        """
        destroyed = 0
        for session in _iter_sessions(sessions):
            if self.destroy_session(session):
                destroyed += 1
        return destroyed

    def within_reclaim_window(self, *, elapsed_seconds: float) -> bool:
        """判断回收是否落在时限内（``≤ reclaim_timeout_s``）。"""
        return 0 <= float(elapsed_seconds) <= self._reclaim_timeout_s


def _iter_sessions(sessions: Any):
    """把入参归一化为会话可迭代对象。"""
    if sessions is None:
        return
    if isinstance(sessions, (list, tuple, set)):
        yield from (s for s in sessions if s is not None)
    else:
        yield sessions
