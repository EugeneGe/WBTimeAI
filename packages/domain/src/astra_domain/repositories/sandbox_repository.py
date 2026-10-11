"""Sandbox 组仓储接口（**仅 Protocol**，零 ORM，C-03）。

对应 ORM 表：``sandbox_session``。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.sandbox import SandboxSession
from .base import Repository

__all__ = ["SandboxSessionRepository"]


@runtime_checkable
class SandboxSessionRepository(Repository[SandboxSession], Protocol):
    """沙箱会话仓储接口。"""

    def list_by_run(self, run_id: str) -> list[SandboxSession]:
        """列出某 Run 关联的全部沙箱会话。"""
        ...
