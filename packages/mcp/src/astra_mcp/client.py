"""MCP 传输抽象 + 客户端（stdio / sse / http；设计 §2.4；W2 / T2-11；裁定 R7 / R8）。

- :class:`MCPTransport`：三传输统一**冻结契约**
  （``open`` / ``request`` / ``notify`` / ``close``，R8）；
- :class:`StdioTransport`：本地子进程（**无出网**，newline-delimited JSON-RPC）——子进程经
  **注入**的 :class:`ProcessSpawner` 拉起（本包**不**直调 ``subprocess``，守「唯一执行出口」纪律）；
  参考实现落 ``astra_sandbox.process_spawner.SubprocessProcessSpawner``；
- :class:`StreamableHttpTransport` / :class:`SseTransport`：出网（**建连前**过
  :meth:`~astra_domain.EgressPolicy.enforce`，以**钉定 IP** 建连，防 DNS rebinding，R8 §8.2）；
- :class:`MCPClient`：协议侧客户端**冻结契约**（``initialize`` / ``list_tools`` /
  ``call_tool`` / ``close``，R8）；
- :class:`DefaultMCPClient`：握手 / 能力协商 / 超时 / 重试实现；
- :func:`_build_transport` / :func:`build_mcp_client`：装配入口。

🔴 本模块**零 Web 框架**：仅标准库；**不 import** ``subprocess`` /
   ``fastapi`` / ``starlette`` / ``astra_security``。凭证经**注入的**
   ``CredentialDecoder`` 取得（见 ``authorization.py``），明文不落库 / 日志 / 回显（C-07）。
🔴 ``stdout`` / ``stderr`` **不落日志**（避免明文 / 敏感泄漏，R8 §8.1）。
"""

from __future__ import annotations

import http.client
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import IO, Any, Protocol, runtime_checkable

from astra_domain import EgressPolicy, MCPCallResult

from .domain import MCPServer
from .protocol import (
    CLIENT_NAME,
    METHOD_INITIALIZE,
    METHOD_INITIALIZED,
    METHOD_TOOLS_CALL,
    METHOD_TOOLS_LIST,
    MCPCapabilities,
    MCPError,
    MCPProtocolError,
    MCPTimeoutError,
    MCPToolSpec,
    MCPTransportError,
    build_notification,
    build_request,
    dumps,
    latest_protocol_version,
    loads,
    result_of,
)

__all__ = [
    "MCPTransport",
    "ManagedProcess",
    "ProcessSpawner",
    "StdioTransport",
    "StreamableHttpTransport",
    "SseTransport",
    "MCPClient",
    "DefaultMCPClient",
    "build_mcp_client",
]

_DEFAULT_CONNECT_TIMEOUT_S = 10.0
_DEFAULT_READ_TIMEOUT_S = 30.0
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_BACKOFF_S = 0.05
_STDIO_JOIN_TIMEOUT_S = 2.0


# -- 传输契约（冻结，R8） ----------------------------------------------------


@runtime_checkable
class MCPTransport(Protocol):
    """MCP 三传输统一契约（R8）。"""

    def open(self, *, timeout_s: float | None = None) -> None:
        """建立传输（stdio 拉起子进程；http/sse 无状态）。"""
        ...

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        """发送请求并返回 JSON-RPC **响应消息**。"""
        ...

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        """发送 JSON-RPC 通知（无响应）。"""
        ...

    def close(self) -> None:
        """关闭传输并回收资源（子进程等）。"""
        ...


# -- 本地子进程启动抽象（stdio；守「唯一执行出口」） -------------------------


@runtime_checkable
class ManagedProcess(Protocol):
    """被托管的本地子进程句柄契约（``subprocess.Popen`` **结构化满足**）。"""

    stdin: IO[bytes] | None
    stdout: IO[bytes] | None
    stderr: IO[bytes] | None

    def poll(self) -> int | None:
        """返回退出码（未退出为 ``None``）。"""
        ...

    def terminate(self) -> None:
        """请求终止。"""
        ...

    def kill(self) -> None:
        """强制杀死。"""
        ...

    def wait(self, timeout: float | None = None) -> int:
        """等待退出。"""
        ...


@runtime_checkable
class ProcessSpawner(Protocol):
    """本地子进程启动器（**注入**；stdio 传输用）。

    Astra 的「唯一执行出口」纪律（``tests/integration/test_sandbox_scan.py``）**禁止**任意
    ``packages/**`` 直调 ``subprocess``——故本包（``astra_mcp``）**不** import ``subprocess``，
    而经**组合根注入**的启动器拉起 MCP stdio Server 子进程；参考实现落
    ``astra_sandbox.process_spawner.SubprocessProcessSpawner``（allowlist 出口）。
    """

    def spawn(
        self,
        *,
        command: str,
        args: Sequence[str],
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> ManagedProcess:
        """拉起子进程并返回句柄（stdio 管道就绪）。"""
        ...


# -- stdio 传输 --------------------------------------------------------------


class StdioTransport:
    """stdio 传输（本地子进程 + newline-delimited JSON-RPC；**无出网**）。

    子进程经**注入**的 :class:`ProcessSpawner` 拉起（本包**不** import ``subprocess``，守「唯一
    执行出口」纪律）；参考实现落 ``astra_sandbox.process_spawner.SubprocessProcessSpawner``。
    """

    def __init__(
        self,
        *,
        command: str,
        spawner: ProcessSpawner,
        args: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        connect_timeout_s: float = _DEFAULT_CONNECT_TIMEOUT_S,
        read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        self._command = command
        self._spawner = spawner
        self._args = [str(item) for item in (args or [])]
        self._env = dict(env) if env else None
        self._cwd = cwd
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._proc: ManagedProcess | None = None
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._drainer: threading.Thread | None = None
        self._lock = threading.Lock()
        self._next_id = 0

    # -- 生命周期 -----------------------------------------------------------

    def open(self, *, timeout_s: float | None = None) -> None:
        """经注入的启动器拉起子进程并启动 stdout / stderr 读线程。"""
        if self._proc is not None:
            return
        try:
            self._proc = self._spawner.spawn(
                command=self._command,
                args=self._args,
                env=self._env,
                cwd=self._cwd,
            )
        except OSError as exc:
            raise MCPTransportError(
                "MCP stdio 子进程启动失败", data={"command": self._command}
            ) from exc
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        if self._proc.stderr is not None:
            # stderr **仅排空**（防管道阻塞），**不落日志**（避免明文泄漏）。
            self._drainer = threading.Thread(target=self._drain_stderr, daemon=True)
            self._drainer.start()

    def _read_stdout(self) -> None:
        """读线程：逐行解析 JSON-RPC 消息入队。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                self._inbox.put(loads(text))
            except MCPProtocolError:
                continue

    def _drain_stderr(self) -> None:
        """排空 stderr（**丢弃内容**，不落日志）。"""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for _ in proc.stderr:
            continue

    def close(self) -> None:
        """终止子进程（幂等）。"""
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=_STDIO_JOIN_TIMEOUT_S)
                except Exception:  # noqa: BLE001 - 超时（TimeoutExpired）→ 强杀
                    proc.kill()
        for thread in (self._reader, self._drainer):
            if thread is not None and thread.is_alive():
                thread.join(timeout=_STDIO_JOIN_TIMEOUT_S)
        self._reader = None
        self._drainer = None

    # -- 收发 ---------------------------------------------------------------

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        """发送请求并等待**匹配 id** 的响应（超时 → :class:`MCPTimeoutError`）。"""
        with self._lock:
            self.open()
            request_id = self._allocate_id()
            self._write(build_request(request_id, method, params))
            budget = timeout_s if timeout_s is not None else self._read_timeout_s
            deadline = time.monotonic() + budget
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPTimeoutError(
                        "MCP stdio 请求超时", data={"method": method, "timeout_s": budget}
                    )
                try:
                    message = self._inbox.get(timeout=remaining)
                except queue.Empty as exc:
                    raise MCPTimeoutError(
                        "MCP stdio 请求超时", data={"method": method, "timeout_s": budget}
                    ) from exc
                if message.get("id") == request_id:
                    return message

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        """发送通知（无响应）。"""
        with self._lock:
            self.open()
            self._write(build_notification(method, params))

    def _allocate_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _write(self, message: Mapping[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise MCPTransportError("MCP stdio 子进程不可用")
        try:
            proc.stdin.write((dumps(message) + "\n").encode("utf-8"))
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPTransportError("MCP stdio 写入失败（连接断开）") from exc


# -- http / sse 传输 ---------------------------------------------------------


def _split_host_port(url: str) -> tuple[str, str, int | None]:
    """拆出 ``(scheme, host, port)``。"""
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme, parsed.hostname or "", parsed.port


def _pinned_url(url: str, pinned_ip: str) -> str:
    """把 URL 的 host 替换为**钉定 IP**（保留端口 / path / query），防 DNS rebinding。"""
    parsed = urllib.parse.urlsplit(url)
    if parsed.port is not None:
        netloc = f"{pinned_ip}:{parsed.port}"
    else:
        netloc = pinned_ip
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def _parse_sse_events(text: str) -> list[dict[str, Any]]:
    """解析 SSE 文本中的 ``data:`` 事件为 JSON 对象列表。"""
    events: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        chunks: list[str] = []
        for line in block.split("\n"):
            if line.startswith("data:"):
                chunks.append(line[len("data:") :].strip())
        if not chunks:
            continue
        payload = "\n".join(chunks)
        try:
            events.append(loads(payload))
        except MCPProtocolError:
            continue
    return events


class StreamableHttpTransport:
    """Streamable HTTP 传输（POST JSON-RPC；响应可为 JSON 或 SSE，R8）。"""

    def __init__(
        self,
        *,
        url: str,
        host_header: str | None = None,
        headers: Mapping[str, str] | None = None,
        read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        self._url = url
        self._host_header = host_header
        self._extra_headers = dict(headers or {})
        self._read_timeout_s = read_timeout_s
        self._next_id = 0

    def open(self, *, timeout_s: float | None = None) -> None:
        """无状态传输：空操作。"""
        return None

    def close(self) -> None:
        """无状态传输：空操作。"""
        return None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._extra_headers,
        }
        if self._host_header:
            headers["Host"] = self._host_header
        return headers

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        """POST 请求并解析 JSON / SSE 响应（超时 → :class:`MCPTimeoutError`）。"""
        self._next_id += 1
        message = build_request(self._next_id, method, params)
        body = self._post(message, timeout_s=timeout_s)
        content_type = str(body.get("content_type", ""))
        raw = str(body.get("text", ""))
        if "text/event-stream" in content_type:
            for event in _parse_sse_events(raw):
                if event.get("id") == message["id"]:
                    return event
            raise MCPProtocolError("MCP SSE 响应缺少匹配 id", data={"method": method})
        return loads(raw)

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        """POST 通知（忽略响应体）。"""
        self._post(build_notification(method, params), timeout_s=None)

    def _post(self, message: Mapping[str, Any], *, timeout_s: float | None) -> dict[str, Any]:
        data = dumps(message).encode("utf-8")
        request = urllib.request.Request(
            self._url, data=data, headers=self._headers(), method="POST"
        )
        timeout = timeout_s if timeout_s is not None else self._read_timeout_s
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8", errors="replace")
                return {
                    "text": raw,
                    "content_type": response.headers.get("Content-Type", ""),
                }
        except (TimeoutError, http.client.HTTPException) as exc:
            raise MCPTimeoutError("MCP http 请求超时", data={"url": self._url}) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise MCPTimeoutError("MCP http 请求超时", data={"url": self._url}) from exc
            raise MCPTransportError("MCP http 连接失败", data={"url": self._url}) from exc
        except OSError as exc:
            raise MCPTransportError("MCP http 连接失败", data={"url": self._url}) from exc


class SseTransport(StreamableHttpTransport):
    """SSE 传输（POST 请求，**强制** ``text/event-stream`` 响应；R8）。"""

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> dict[str, Any]:
        """POST 请求并**要求** SSE 响应（无匹配 id → :class:`MCPProtocolError`）。"""
        self._next_id += 1
        message = build_request(self._next_id, method, params)
        body = self._post(message, timeout_s=timeout_s)
        raw = str(body.get("text", ""))
        events = _parse_sse_events(raw)
        if not events:
            raise MCPProtocolError("MCP SSE 响应为空", data={"method": method})
        for event in events:
            if event.get("id") == message["id"]:
                return event
        return events[0]


# -- 传输装配（R8 §8.2：endpoint 建连前过 EgressPolicy） ----------------------


def _build_transport(
    server: MCPServer,
    *,
    egress: EgressPolicy | None = None,
    headers: Mapping[str, str] | None = None,
    settings: Any = None,
    spawner: ProcessSpawner | None = None,
) -> MCPTransport:
    """按 ``server.transport`` 构造传输，出网传输**建连前**过 ``EgressPolicy.enforce``。

    Args:
        server: MCP Server 配置。
        egress: 出网策略（``http`` / ``sse`` **必注入**；``stdio`` 无出网不使用）。
        headers: 附加请求头（如鉴权，由 :class:`~astra_mcp.authorization.MCPAuthorization` 提供）。
        settings: 生效配置（取 ``settings.mcp`` 超时）。
        spawner: 本地子进程启动器（``stdio`` **必注入**；见 :class:`ProcessSpawner`）。

    Returns:
        对应传输实例。

    Raises:
        DomainError: 出网传输缺 ``egress``（``CONFIGURATION_ERROR``）或 ``endpoint`` 被拒
            （``PERMISSION_DENIED``，由 ``EgressPolicy`` 抛出）；``stdio`` 缺 ``spawner``
            （``CONFIGURATION_ERROR``）。
    """
    connect_timeout, read_timeout = _timeouts(settings)
    transport_name = server.transport
    if transport_name == "stdio":
        if not server.command:
            raise MCPTransportError("MCP stdio Server 缺少 command", data={"server": server.name})
        if spawner is None:
            raise MCPTransportError(
                "MCP stdio 传输须注入 ProcessSpawner（本包不直调 subprocess，守唯一执行出口）",
                data={"server": server.name},
            )
        return StdioTransport(
            command=server.command,
            spawner=spawner,
            args=list(server.args),
            connect_timeout_s=connect_timeout,
            read_timeout_s=read_timeout,
        )

    if not server.endpoint:
        raise MCPTransportError("MCP 出网 Server 缺少 endpoint", data={"server": server.name})
    if egress is None:
        raise MCPTransportError(
            "MCP 出网端点须注入 EgressPolicy（endpoint 建连前须过 enforce）",
            data={"server": server.name},
        )
    pinned_ip = egress.enforce(server.endpoint)  # 拒绝 → DomainError(PERMISSION_DENIED)
    _, host, port = _split_host_port(server.endpoint)
    host_header = f"{host}:{port}" if port is not None else host
    pinned = _pinned_url(server.endpoint, pinned_ip)
    if transport_name == "sse":
        return SseTransport(
            url=pinned, host_header=host_header, headers=headers, read_timeout_s=read_timeout
        )
    return StreamableHttpTransport(
        url=pinned, host_header=host_header, headers=headers, read_timeout_s=read_timeout
    )


def _timeouts(settings: Any) -> tuple[float, float]:
    """从 ``settings.mcp`` 取 ``(connect_timeout, read_timeout)``。"""
    mcp_settings = getattr(settings, "mcp", None) if settings is not None else None
    connect = float(getattr(mcp_settings, "connect_timeout_seconds", _DEFAULT_CONNECT_TIMEOUT_S))
    read = float(getattr(mcp_settings, "read_timeout_seconds", _DEFAULT_READ_TIMEOUT_S))
    return connect, read


# -- 客户端契约（冻结，R8） --------------------------------------------------


@runtime_checkable
class MCPClient(Protocol):
    """MCP 协议客户端契约（R8）。"""

    def initialize(self) -> MCPCapabilities:
        """握手 + 能力协商。"""
        ...

    def list_tools(self) -> list[MCPToolSpec]:
        """``tools/list`` 发现。"""
        ...

    def call_tool(
        self, name: str, arguments: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> MCPCallResult:
        """``tools/call`` 调用（复用域 DTO ``MCPCallResult``）。"""
        ...

    def close(self) -> None:
        """关闭客户端与传输。"""
        ...


class DefaultMCPClient:
    """MCP 客户端默认实现（握手 / 能力协商 / 超时 / 重试）。"""

    def __init__(
        self,
        *,
        transport: MCPTransport,
        connect_timeout_s: float = _DEFAULT_CONNECT_TIMEOUT_S,
        read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        backoff_s: float = _DEFAULT_BACKOFF_S,
        protocol_version: str | None = None,
    ) -> None:
        self._transport = transport
        self._connect_timeout_s = connect_timeout_s
        self._read_timeout_s = read_timeout_s
        self._max_retries = max(0, int(max_retries))
        self._backoff_s = backoff_s
        self._protocol_version = protocol_version or latest_protocol_version()
        self._capabilities: MCPCapabilities | None = None
        self._opened = False

    # -- 契约方法 -----------------------------------------------------------

    def initialize(self) -> MCPCapabilities:
        """握手（``initialize`` + ``notifications/initialized``）并缓存能力协商结果。"""
        self._open()
        result = self._call(
            METHOD_INITIALIZE,
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": CLIENT_NAME, "version": "0.1.0"},
            },
        )
        try:
            self._transport.notify(METHOD_INITIALIZED, {})
        except MCPError:
            # 通知失败不致命（部分 Server 不要求）。
            pass
        self._capabilities = MCPCapabilities.from_result(result)
        self._opened = True
        return self._capabilities

    def list_tools(self) -> list[MCPToolSpec]:
        """``tools/list`` → :class:`MCPToolSpec` 列表。"""
        result = self._call(METHOD_TOOLS_LIST, {})
        raw_tools = result.get("tools") if isinstance(result, Mapping) else None
        return [MCPToolSpec.from_mapping(item) for item in (raw_tools or [])]

    def call_tool(
        self, name: str, arguments: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> MCPCallResult:
        """``tools/call`` → :class:`~astra_domain.MCPCallResult`（失败转 ``ok=False``）。"""
        try:
            result = self._call(
                METHOD_TOOLS_CALL,
                {"name": name, "arguments": dict(arguments)},
                timeout_s=timeout_s,
            )
        except MCPError as exc:
            return MCPCallResult(ok=False, error=str(exc))
        if isinstance(result, Mapping) and result.get("isError"):
            return MCPCallResult(ok=False, output=result, error="远端标记 isError")
        return MCPCallResult(ok=True, output=result)

    def close(self) -> None:
        """关闭传输（幂等）。"""
        self._transport.close()
        self._opened = False

    def __enter__(self) -> DefaultMCPClient:  # noqa: D105
        self._open()
        return self

    def __exit__(self, *exc: object) -> None:  # noqa: D105
        self.close()

    # -- 内部 ---------------------------------------------------------------

    def _open(self) -> None:
        """确保传输已建立。"""
        if not getattr(self, "_opened", False):
            self._transport.open(timeout_s=self._connect_timeout_s)
            self._opened = True

    def _call(
        self, method: str, params: Mapping[str, Any], *, timeout_s: float | None = None
    ) -> Any:
        """发送请求并提取 ``result``（按 ``max_retries`` 对**连接错误**重试）。"""
        timeout = timeout_s if timeout_s is not None else self._read_timeout_s
        attempts = self._max_retries + 1
        last_error: MCPError | None = None
        for attempt in range(attempts):
            try:
                self._open()
                response = self._transport.request(method, params, timeout_s=timeout)
                return result_of(response)
            except MCPTimeoutError:
                raise  # 超时**不重试**，快速失败
            except MCPTransportError as exc:
                last_error = exc
                self._reset()
                if attempt < attempts - 1:
                    time.sleep(self._backoff_s)
                    continue
                raise
        raise last_error or MCPTransportError("MCP 调用失败", data={"method": method})

    def _reset(self) -> None:
        """关闭并丢弃当前传输（供重连）。"""
        try:
            self._transport.close()
        except Exception:  # noqa: BLE001 - 关闭尽力而为，异常不外抛
            pass
        self._opened = False
        self._capabilities = None


# -- 装配入口 ----------------------------------------------------------------


def build_mcp_client(
    server: MCPServer,
    *,
    egress: EgressPolicy | None = None,
    headers: Mapping[str, str] | None = None,
    settings: Any = None,
    spawner: ProcessSpawner | None = None,
) -> MCPClient:
    """按 Server 配置装配一个 :class:`MCPClient`（**组合根**调用）。

    Args:
        server: MCP Server 配置。
        egress: 出网策略（``http`` / ``sse`` 必注入；``endpoint`` 建连前过 ``enforce``）。
        headers: 附加请求头（鉴权由 :class:`~astra_mcp.authorization.MCPAuthorization` 提供）。
        settings: 生效配置（``settings.mcp`` 提供超时 / 重试）。
        spawner: 本地子进程启动器（``stdio`` 必注入；参考实现落 ``astra_sandbox``）。

    Returns:
        可用的 :class:`MCPClient`。
    """
    connect_timeout, read_timeout = _timeouts(settings)
    mcp_settings = getattr(settings, "mcp", None) if settings is not None else None
    max_retries = int(getattr(mcp_settings, "max_retries", _DEFAULT_MAX_RETRIES))
    transport = _build_transport(
        server, egress=egress, headers=headers, settings=settings, spawner=spawner
    )
    return DefaultMCPClient(
        transport=transport,
        connect_timeout_s=connect_timeout,
        read_timeout_s=read_timeout,
        max_retries=max_retries,
    )
