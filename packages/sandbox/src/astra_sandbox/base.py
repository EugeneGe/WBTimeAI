"""Sandbox 抽象接口（设计 §2.10）。

- :class:`SandboxSession`：沙箱会话句柄（复用 ``astra_domain`` 实体，供审计与重建）；
- :class:`ExecResult`：一次执行的退出码 / 输出 / 耗时；
- :class:`SandboxProvider`：``SandboxProvider`` Protocol——``create_session`` / ``exec`` /
  ``put_file`` / ``get_file`` / ``destroy``（**唯一执行出口**，核心原则 ⑪）。

🔴 ``astra_sandbox`` 属**抽象包**：零 ORM、零框架（不 import ``fastapi`` / ``sqlalchemy`` /
   ``alembic`` / ``astra_database``）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from astra_domain import SandboxSession

__all__ = ["SandboxSession", "ExecResult", "SandboxProvider"]


@dataclass
class ExecResult:
    """沙箱内一次命令执行的结果。

    Attributes:
        exit_code: 退出码（超时约定为 ``124``）。
        stdout: 标准输出（可截断）。
        stderr: 标准错误（可截断）。
        duration_ms: 执行耗时（毫秒）。
        timed_out: 是否超时被强制终止。
    """

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """是否成功（退出码 0 且未超时）。"""
        return self.exit_code == 0 and not self.timed_out


@runtime_checkable
class SandboxProvider(Protocol):
    """沙箱提供方接口（**唯一合法执行出口**，核心原则 ⑪）。"""

    @property
    def kind(self) -> str:
        """提供方种类（``docker`` / ``local_process``）。"""
        ...

    @property
    def available(self) -> bool:
        """提供方当前是否可用。"""
        ...

    def create_session(
        self,
        *,
        workspace_id: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        image: str | None = None,
        workdir: str | None = None,
    ) -> SandboxSession:
        """创建一个沙箱会话并返回句柄。"""
        ...

    def exec(
        self,
        session: SandboxSession,
        command: str | Sequence[str],
        *,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """在会话内执行命令。"""
        ...

    def put_file(self, session: SandboxSession, path: str, content: str) -> None:
        """把文本写入会话工作目录内文件。"""
        ...

    def get_file(self, session: SandboxSession, path: str) -> str:
        """读取会话工作目录内文件文本。"""
        ...

    def destroy(self, session: SandboxSession) -> None:
        """销毁会话（**幂等**：重复调用不报错、不泄漏）。"""
        ...
