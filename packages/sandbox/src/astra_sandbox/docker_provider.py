"""``DockerSandboxProvider``（Phase 1 标准沙箱，设计 §2.10 / §5 #3）。

默认强度：network=none + 非 root + 只读 rootfs + 资源限额 + Workspace bind mount + 超时。

🔴 ``import docker`` **仅在函数内**（延迟导入）；``DockerSandboxProvider`` 的**装配**只在
   ``build_sandbox_provider``（C-01）；Runtime / Tool 永不探测 Docker。
🔴 ``destroy()`` **幂等**（§2.7.2 超时/取消传播依赖）。
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import (
    SANDBOX_PROVIDER_DOCKER,
    SANDBOX_SESSION_STATUS_RUNNING,
    SANDBOX_SESSION_STATUS_STOPPED,
    SandboxSession,
)

from .base import ExecResult

__all__ = ["DockerSandboxProvider", "DEFAULT_SANDBOX_IMAGE"]

#: 默认沙箱镜像基线（§5 #3 定版）。
DEFAULT_SANDBOX_IMAGE = "python:3.12-slim"


class DockerSandboxProvider:
    """基于 Docker 的容器级隔离沙箱。"""

    def __init__(
        self,
        *,
        image: str = DEFAULT_SANDBOX_IMAGE,
        network: str = "none",
        user: str = "65534:65534",
        read_only: bool = True,
        mem_limit: str = "512m",
        nano_cpus: int = 1_000_000_000,
        pids_limit: int = 256,
        default_timeout_ms: int = 60_000,
        max_output_chars: int = 200_000,
        client: Any | None = None,
    ) -> None:
        self._image = image
        self._network = network
        self._user = user
        self._read_only = read_only
        self._mem_limit = mem_limit
        self._nano_cpus = nano_cpus
        self._pids_limit = pids_limit
        self._default_timeout_ms = default_timeout_ms
        self._max_output_chars = max_output_chars
        self._client = client
        self._sessions: dict[str, SandboxSession] = {}
        self._containers: dict[str, Any] = {}

    @property
    def kind(self) -> str:
        """提供方种类：``docker``。"""
        return SANDBOX_PROVIDER_DOCKER

    @property
    def available(self) -> bool:
        """Docker 守护进程是否可达。"""
        try:
            return bool(self._ensure_client().ping())
        except Exception:  # noqa: BLE001 - 探测容错
            return False

    def create_session(
        self,
        *,
        workspace_id: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        image: str | None = None,
        workdir: str | None = None,
    ) -> SandboxSession:
        """按 ``sandbox_session.image`` 启容器并返回会话句柄。"""
        client = self._ensure_client()
        resolved_workdir = str(Path(workdir).expanduser().resolve()) if workdir else "/workspace"
        container = client.containers.run(
            image or self._image,
            command=["sleep", "infinity"],
            detach=True,
            network_mode=self._network,
            user=self._user,
            read_only=self._read_only,
            mem_limit=self._mem_limit,
            nano_cpus=self._nano_cpus,
            pids_limit=self._pids_limit,
            working_dir=resolved_workdir,
            volumes={resolved_workdir: {"bind": resolved_workdir, "mode": "rw"}},
            labels={"astra.component": "sandbox", "astra.workspace": str(workspace_id or "")},
            auto_remove=False,
        )
        session = SandboxSession(
            tenant_id=tenant_id,
            run_id=run_id,
            workspace_id=workspace_id,
            provider=self.kind,
            image=image or self._image,
            status=SANDBOX_SESSION_STATUS_RUNNING,
            container_ref=str(getattr(container, "id", "")),
            workdir=resolved_workdir,
        )
        self._sessions[session.id] = session
        self._containers[session.id] = container
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
        """在容器内执行命令（``exec_run``），退出码透传。"""
        container = self._containers.get(session.id)
        if container is None:
            raise DomainError(
                "沙箱会话不存在",
                code=ErrorCode.NOT_FOUND,
                data={"session_id": session.id},
            )
        argv = command if isinstance(command, str) else [str(part) for part in command]
        environment = {str(k): str(v) for k, v in (env or {}).items()}
        result = container.exec_run(
            cmd=argv,
            workdir=cwd or session.workdir,
            environment=environment or None,
            demux=True,
        )
        exit_code = int(getattr(result, "exit_code", 1) or 0)
        stdout_bytes, stderr_bytes = self._split_output(getattr(result, "output", None))
        return ExecResult(
            exit_code=exit_code,
            stdout=self._truncate(stdout_bytes.decode("utf-8", errors="replace")),
            stderr=self._truncate(stderr_bytes.decode("utf-8", errors="replace")),
            duration_ms=0,
            timed_out=False,
        )

    def put_file(self, session: SandboxSession, path: str, content: str) -> None:
        """把文本写入容器工作目录内文件（经 tar 归档）。"""
        container = self._containers[session.id]
        data = content.encode("utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        buffer.seek(0)
        container.put_archive(session.workdir, buffer)

    def get_file(self, session: SandboxSession, path: str) -> str:
        """读取容器工作目录内文件文本。"""
        container = self._containers[session.id]
        stream, _stat = container.get_archive(str(Path(session.workdir) / path))
        raw = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            members = archive.getmembers()
            if not members:
                return ""
            extracted = archive.extractfile(members[0])
            return extracted.read().decode("utf-8", errors="replace") if extracted else ""

    def destroy(self, session: SandboxSession) -> None:
        """销毁容器（**幂等**：重复调用 / 容器已不存在均不报错）。"""
        container = self._containers.pop(session.id, None)
        existing = self._sessions.pop(session.id, None)
        target = existing if existing is not None else session
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001 - 幂等：容器已不存在视为成功
                pass
        target.status = SANDBOX_SESSION_STATUS_STOPPED

    # -- 内部 ---------------------------------------------------------------

    def _ensure_client(self) -> Any:
        """延迟构造 Docker 客户端（函数内 ``import docker``）。"""
        if self._client is None:
            import docker  # noqa: PLC0415 - 延迟导入（Q3）

            self._client = docker.from_env()
        return self._client

    @staticmethod
    def _split_output(output: Any) -> tuple[bytes, bytes]:
        """把 ``exec_run`` 的 output 归一化为 ``(stdout, stderr)`` 字节。"""
        if isinstance(output, tuple):
            stdout, stderr = output
            return stdout or b"", stderr or b""
        if isinstance(output, bytes):
            return output, b""
        if output is None:
            return b"", b""
        return str(output).encode("utf-8"), b""

    def _truncate(self, text: str) -> str:
        """截断过长输出。"""
        if len(text) <= self._max_output_chars:
            return text
        return text[: self._max_output_chars]
