"""确定性 :class:`~astra_sandbox.SandboxProvider` 替身（W8 / T1-36）。

实现 ``SandboxProvider`` Protocol（``kind`` / ``available`` / ``create_session`` /
``exec`` / ``put_file`` / ``get_file`` / ``destroy``），**零真实进程 / 零 Docker**：

- ``create_session`` 返回真实 :class:`~astra_domain.SandboxSession` 句柄并编号；
- ``exec`` 返回**确定性** :class:`~astra_sandbox.ExecResult`（stdout 可配，支持 100KB 场景）；
- ``put_file`` / ``get_file`` 以内存字典模拟会话工作目录内文件；
- ``destroy`` **幂等**（重复调用不抛错、计数只在首次销毁递增），并置会话为 ``STOPPED``。

供 e2e 驱动「自主调 Tool → Sandbox 执行 → 返回结果」，且断言工具输出的**截断 / 落库**行为。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from astra_domain import (
    SANDBOX_PROVIDER_LOCAL_PROCESS,
    SANDBOX_SESSION_STATUS_RUNNING,
    SandboxSession,
)
from astra_sandbox import ExecResult

__all__ = ["FakeSandboxProvider"]


@dataclass
class _FakeSession:
    """会话内部状态：领域句柄 + 工作目录内文件。"""

    handle: SandboxSession
    files: dict[str, str] = field(default_factory=dict)


class FakeSandboxProvider:
    """确定性沙箱替身（记录创建 / 执行 / 销毁；``destroy`` 幂等）。

    Attributes:
        created: ``create_session`` 调用次数。
        destroyed: 实际销毁的会话数（幂等：同一会话只计一次）。
        exec_calls: ``exec`` 调用次数。
        commands: 每次 ``exec`` 收到的命令（归一化为字符串列表）。
    """

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        timed_out: bool = False,
        workdir: str = "/fake-sandbox",
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._exit_code = exit_code
        self._timed_out = timed_out
        self._workdir = workdir
        self._sessions: dict[str, _FakeSession] = {}
        self.created = 0
        self.destroyed = 0
        self.exec_calls = 0
        self.commands: list[list[str]] = []

    # -- SandboxProvider 契约 -----------------------------------------------

    @property
    def kind(self) -> str:
        """提供方种类：``local_process``（社区默认，不探测 Docker）。"""
        return SANDBOX_PROVIDER_LOCAL_PROCESS

    @property
    def available(self) -> bool:
        """恒可用（无外部依赖）。"""
        return True

    def create_session(
        self,
        *,
        workspace_id: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        image: str | None = None,
        workdir: str | None = None,
    ) -> SandboxSession:
        """创建一个沙箱会话并登记（返回真实领域句柄）。"""
        self.created += 1
        session = SandboxSession(
            tenant_id=tenant_id,
            run_id=run_id,
            workspace_id=workspace_id,
            provider=self.kind,
            image=image,
            status=SANDBOX_SESSION_STATUS_RUNNING,
            workdir=workdir or self._workdir,
        )
        self._sessions[session.id] = _FakeSession(handle=session)
        return session

    def exec(
        self,
        session: SandboxSession,
        command: str | Sequence[str],
        *,
        timeout_ms: int | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """返回**确定性**执行结果（stdout 可配；无真实子进程）。"""
        self.exec_calls += 1
        self.commands.append(self._to_argv(command))
        return ExecResult(
            exit_code=self._exit_code,
            stdout=self._stdout,
            stderr=self._stderr,
            duration_ms=1,
            timed_out=self._timed_out,
        )

    def put_file(self, session: SandboxSession, path: str, content: str) -> None:
        """把文本写入内存工作目录。"""
        self._state(session).files[path] = content

    def get_file(self, session: SandboxSession, path: str) -> str:
        """从内存工作目录读取文件文本（不存在返回空串）。"""
        return self._state(session).files.get(path, "")

    def destroy(self, session: SandboxSession) -> None:
        """销毁会话（**幂等**：重复调用不抛错、计数仅首次递增）。"""
        from astra_domain import SANDBOX_SESSION_STATUS_STOPPED

        state = self._sessions.pop(session.id, None)
        if state is None:
            session.status = SANDBOX_SESSION_STATUS_STOPPED
            return
        state.handle.status = SANDBOX_SESSION_STATUS_STOPPED
        session.status = SANDBOX_SESSION_STATUS_STOPPED
        self.destroyed += 1

    # -- 内部 ---------------------------------------------------------------

    def _state(self, session: SandboxSession) -> _FakeSession:
        """取得（必要时惰性登记）会话内部状态。"""
        state = self._sessions.get(session.id)
        if state is None:
            state = _FakeSession(handle=session)
            self._sessions[session.id] = state
        return state

    @staticmethod
    def _to_argv(command: str | Sequence[str]) -> list[str]:
        """把命令归一化为 argv 列表（不解析引号，保持确定性）。"""
        if isinstance(command, str):
            return command.split()
        return [str(part) for part in command]
