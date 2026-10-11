"""``LocalProcessSandboxProvider``（社区 no-Docker 降级，设计 §2.10 / A-5）。

受限子进程 + 工作目录隔离 + 环境变量白名单；**能力与安全弱于 Docker**（进程级隔离，非容器级）。

🔴 本模块是**唯一合法的 ``subprocess`` 使用出口**（``SandboxProvider`` 唯一执行出口，核心原则 ⑪）；
   被 ``tests/integration/test_sandbox_scan.py`` **显式 allowlist** 排除。
🔴 **不注入** Host 真实密钥：环境变量经白名单过滤，且**剔除** ``ASTRA_*`` 前缀键（D-16 / D-17）。
"""

from __future__ import annotations

import os
import shlex
import subprocess  # noqa: S404 - 唯一合法执行出口（SandboxProvider）
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from astra_core import DomainError, ErrorCode
from astra_domain import (
    SANDBOX_PROVIDER_LOCAL_PROCESS,
    SANDBOX_SESSION_STATUS_RUNNING,
    SANDBOX_SESSION_STATUS_STOPPED,
    SandboxSession,
)

from .base import ExecResult

__all__ = ["LocalProcessSandboxProvider", "DEFAULT_ENV_ALLOWLIST", "TIMEOUT_EXIT_CODE"]

#: 超时退出码约定（对齐 ``coreutils`` timeout 的 124）。
TIMEOUT_EXIT_CODE = 124

#: 允许透传进子进程的环境变量白名单（跨平台最小集）。
DEFAULT_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "PYTHONPATH",
        "PYTHONIOENCODING",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
        "PATHEXT",
        "WINDIR",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "NUMBER_OF_PROCESSORS",
        "OS",
    }
)


class LocalProcessSandboxProvider:
    """受限子进程沙箱（进程级隔离）。"""

    def __init__(
        self,
        *,
        workspace_root: str | None = None,
        base_dir: str | None = None,
        env_allowlist: Sequence[str] | None = None,
        default_timeout_ms: int = 60_000,
        max_output_chars: int = 200_000,
    ) -> None:
        self._workspace_root = (
            Path(workspace_root).expanduser().resolve() if workspace_root else None
        )
        self._base_dir = Path(base_dir).expanduser().resolve() if base_dir else None
        self._env_allowlist = frozenset(env_allowlist) if env_allowlist else DEFAULT_ENV_ALLOWLIST
        self._default_timeout_ms = default_timeout_ms
        self._max_output_chars = max_output_chars
        self._sessions: dict[str, SandboxSession] = {}
        self._workdirs: dict[str, Path] = {}

    @property
    def kind(self) -> str:
        """提供方种类：``local_process``。"""
        return SANDBOX_PROVIDER_LOCAL_PROCESS

    @property
    def available(self) -> bool:
        """LocalProcess 恒可用（无外部依赖）。"""
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
        """创建会话（工作目录：显式 ``workdir`` > ``workspace_root`` > 临时目录）。"""
        resolved = self._resolve_workdir(workdir)
        resolved.mkdir(parents=True, exist_ok=True)
        session = SandboxSession(
            tenant_id=tenant_id,
            run_id=run_id,
            workspace_id=workspace_id,
            provider=self.kind,
            image=image,
            status=SANDBOX_SESSION_STATUS_RUNNING,
            workdir=str(resolved),
        )
        self._sessions[session.id] = session
        self._workdirs[session.id] = resolved
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
        """在受限子进程中执行命令（超时强制终止，输出截断）。"""
        argv = self._to_argv(command)
        workdir = Path(cwd).expanduser().resolve() if cwd else self._workdir(session)
        base_env = self._build_env(env)
        timeout_s = (timeout_ms if timeout_ms is not None else self._default_timeout_ms) / 1000.0

        start = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S603 - 唯一合法执行出口
                argv,
                cwd=str(workdir),
                env=base_env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecResult(
                exit_code=completed.returncode,
                stdout=self._truncate(completed.stdout),
                stderr=self._truncate(completed.stderr),
                duration_ms=duration_ms,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecResult(
                exit_code=TIMEOUT_EXIT_CODE,
                stdout=self._truncate(self._decode(exc.stdout)),
                stderr=self._truncate(self._decode(exc.stderr)),
                duration_ms=duration_ms,
                timed_out=True,
            )
        except FileNotFoundError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecResult(
                exit_code=127,
                stderr=f"命令不存在：{exc}",
                duration_ms=duration_ms,
                timed_out=False,
            )

    def put_file(self, session: SandboxSession, path: str, content: str) -> None:
        """写入会话工作目录内文件（越界拒绝）。"""
        target = self._safe_join(self._workdir(session), path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def get_file(self, session: SandboxSession, path: str) -> str:
        """读取会话工作目录内文件文本（越界拒绝）。"""
        target = self._safe_join(self._workdir(session), path)
        return target.read_text(encoding="utf-8")

    def destroy(self, session: SandboxSession) -> None:
        """销毁会话（**幂等**：重复调用不报错）。"""
        self._workdirs.pop(session.id, None)
        existing = self._sessions.pop(session.id, None)
        target = existing if existing is not None else session
        target.status = SANDBOX_SESSION_STATUS_STOPPED

    # -- 内部 ---------------------------------------------------------------

    def _resolve_workdir(self, workdir: str | None) -> Path:
        """解析会话工作目录。"""
        if workdir:
            return Path(workdir).expanduser().resolve()
        if self._workspace_root is not None:
            return self._workspace_root
        if self._base_dir is not None:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="sandbox-", dir=str(self._base_dir)))
        return Path(tempfile.mkdtemp(prefix="astra-sandbox-"))

    def _workdir(self, session: SandboxSession) -> Path:
        """返回会话工作目录。"""
        resolved = self._workdirs.get(session.id)
        if resolved is not None:
            return resolved
        return Path(session.workdir).expanduser().resolve()

    def _build_env(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        """构造子进程环境：白名单过滤 + 剔除 ``ASTRA_*`` 机密。"""
        env = {key: os.environ[key] for key in self._env_allowlist if key in os.environ}
        for key in list(env):
            if key.upper().startswith("ASTRA_"):
                del env[key]
        for key, value in (extra or {}).items():
            name = str(key)
            if name.upper().startswith("ASTRA_"):
                continue
            env[name] = str(value)
        return env

    def _safe_join(self, base: Path, path: str) -> Path:
        """把相对路径安全拼接进 ``base``，越界抛 ``PERMISSION_DENIED``。"""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = base / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(base.resolve()):
            raise DomainError(
                "沙箱内路径越界",
                code=ErrorCode.PERMISSION_DENIED,
                data={"path": path},
            )
        return resolved

    @staticmethod
    def _to_argv(command: str | Sequence[str]) -> list[str]:
        """把命令归一化为 argv。"""
        if isinstance(command, str):
            return shlex.split(command)
        return [str(part) for part in command]

    def _truncate(self, text: str) -> str:
        """截断过长输出。"""
        if len(text) <= self._max_output_chars:
            return text
        return text[: self._max_output_chars]

    @staticmethod
    def _decode(value: object) -> str:
        """把 ``TimeoutExpired`` 携带的 stdout/stderr 归一化为字符串。"""
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
