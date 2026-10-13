"""``DockerSandboxProvider``（Phase 1 标准沙箱，设计 §2.10 / §5 #3）。

默认强度：network=none + 非 root + 只读 rootfs + 资源限额 + Workspace bind mount + 超时。

🔴 ``import docker`` **仅在函数内**（延迟导入）；``DockerSandboxProvider`` 的**装配**只在
   ``build_sandbox_provider``（C-01）；Runtime / Tool 永不探测 Docker。
🔴 ``destroy()`` **幂等**（§2.7.2 超时/取消传播依赖）。
"""

from __future__ import annotations

import io
import tarfile
import threading
import time
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
from .local_process_provider import TIMEOUT_EXIT_CODE
from .network import (
    DEFAULT_EGRESS_NETWORK,
    NETWORK_OFFLINE,
    NETWORK_PROFILE_ALLOWLISTED,
    NETWORK_PROFILE_OFFLINE,
)

__all__ = ["DockerSandboxProvider", "DEFAULT_SANDBOX_IMAGE"]

#: 默认沙箱镜像基线（§5 #3 定版）。
DEFAULT_SANDBOX_IMAGE = "python:3.12-slim"


class DockerSandboxProvider:
    """基于 Docker 的容器级隔离沙箱。

    T2-56：新增**网络档位**（``network_profile``）与**受控 Egress Proxy** 注入——默认
    ``offline``（``network=none``）；``allowlisted`` 时接入**内部**网络（无外部路由）+ 注入
    代理环境变量。**不改** Phase 1 ``SandboxProvider`` Protocol
    （``create_session``/``exec`` 签名零改）。
    """

    def __init__(
        self,
        *,
        image: str = DEFAULT_SANDBOX_IMAGE,
        network: str = NETWORK_OFFLINE,
        network_profile: str = NETWORK_PROFILE_OFFLINE,
        egress_network: str = DEFAULT_EGRESS_NETWORK,
        egress_proxy_url: str = "",
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
        self._network_profile = network_profile
        self._egress_network = egress_network
        self._egress_proxy_url = egress_proxy_url
        # 解析生效网络模式：allowlisted → 内部 Egress 网络；否则 → 显式/默认 ``none``。
        if network_profile == NETWORK_PROFILE_ALLOWLISTED:
            self._network = egress_network
        else:
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
    def network(self) -> str:
        """生效的 Docker ``network_mode``（``none`` 或内部 Egress 网络名）。"""
        return self._network

    @property
    def network_profile(self) -> str:
        """生效的网络档位（``offline`` / ``allowlisted``）。"""
        return self._network_profile

    @property
    def egress_proxy_url(self) -> str:
        """受控 Egress Proxy 地址（``allowlisted`` 时有意义）。"""
        return self._egress_proxy_url

    def container_environment(self) -> dict[str, str]:
        """返回需注入沙箱容器的代理环境变量（仅 ``allowlisted`` 且配 URL 时非空）。"""
        if self._network_profile != NETWORK_PROFILE_ALLOWLISTED or not self._egress_proxy_url:
            return {}
        return {
            "HTTP_PROXY": self._egress_proxy_url,
            "HTTPS_PROXY": self._egress_proxy_url,
            "http_proxy": self._egress_proxy_url,
            "https_proxy": self._egress_proxy_url,
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "no_proxy": "localhost,127.0.0.1,::1",
        }

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
            # T2-56：ALLOWLISTED 档注入受控 Egress Proxy 环境变量（offline 档为空）。
            environment=(self.container_environment() or None),
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
        """在容器内执行命令（``exec_run``）；退出码透传，**超时强制终止**（A-5 / I-P1-20）。

        Docker ``exec_run`` 为**阻塞**调用且无内建超时；此处以**工作线程 + 等待超时**实现：
        超 ``timeout_ms``（缺省 ``default_timeout_ms``）未完成 → ``container.kill()`` 强制终止
        （容器**专用于本会话**，终止即终止该 exec）→ 返回 ``exit_code=124`` / ``timed_out=True``
        （约定对齐 :class:`ExecResult` 与 ``LocalProcessSandboxProvider``）。
        """
        container = self._containers.get(session.id)
        if container is None:
            raise DomainError(
                "沙箱会话不存在",
                code=ErrorCode.NOT_FOUND,
                data={"session_id": session.id},
            )
        argv = command if isinstance(command, str) else [str(part) for part in command]
        environment = {str(k): str(v) for k, v in (env or {}).items()}
        timeout_s = max(
            (timeout_ms if timeout_ms is not None else self._default_timeout_ms) / 1000.0,
            0.0,
        )

        outcome: dict[str, Any] = {}

        def _run() -> None:
            try:
                outcome["result"] = container.exec_run(
                    cmd=argv,
                    workdir=cwd or session.workdir,
                    environment=environment or None,
                    demux=True,
                )
            except Exception as exc:  # noqa: BLE001 - 容器被终止等异常经 outcome 传回调用方
                outcome["error"] = exc

        start = time.monotonic()
        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout_s)
        duration_ms = int((time.monotonic() - start) * 1000)
        if worker.is_alive():
            try:
                container.kill()
            except Exception:  # noqa: BLE001 - 已停止 / 已移除视为已达终止目的（幂等）
                pass
            return ExecResult(
                exit_code=TIMEOUT_EXIT_CODE,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                timed_out=True,
            )
        # 非超时路径：``_run`` 捕获的异常**原样向上传播**（保持 ``exec_run`` 既有语义，
        # **不静默降级**为 ``exit_code=1``）；仅超时（kill）路径返回 ``timed_out`` 结果。
        if "error" in outcome:
            raise outcome["error"]
        result = outcome.get("result")
        exit_code = int(getattr(result, "exit_code", 1) or 0)
        stdout_bytes, stderr_bytes = self._split_output(getattr(result, "output", None))
        return ExecResult(
            exit_code=exit_code,
            stdout=self._truncate(stdout_bytes.decode("utf-8", errors="replace")),
            stderr=self._truncate(stderr_bytes.decode("utf-8", errors="replace")),
            duration_ms=duration_ms,
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
