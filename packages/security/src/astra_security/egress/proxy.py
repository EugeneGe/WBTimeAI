"""受控 Egress Proxy（T2-56；设计 §2.18 / §2.8.1）。

**定位**：沙箱在 ``network=none`` 或**内部**（无外部路由）网络下，出网**只能**经本代理；代理对
**每次连接 / 每个请求**调用**既有** :class:`~astra_security.egress.policy.SecurityEgressPolicy`
（**唯一判定源**）——**不**另建白名单，**不**以应用层 URL 校验替代网络隔离。

- HTTPS：``CONNECT host:port`` → 代理按 ``https://host:port`` 判定 → 通过则经**钉定 IP** 建隧道；
- HTTP：绝对 URI 请求 → 代理按完整 URL 判定 → 通过则转发（``Connection: close``）。

🔴 判定**复用**同一 :class:`SecurityEgressPolicy` 实例（拒绝即 403；命中私网 / 元数据 / DNS
   rebinding 由策略自身拒段保证）。

🔴 本模块**零** ORM / Web 框架（仅标准库 + ``astra_domain.ports.egress`` 原语 + 本包策略）。
   运行时以 ``python -m astra_security.egress.proxy`` 启动（``main`` 内**函数级**读配置）。
"""

from __future__ import annotations

import argparse
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from astra_domain.ports.egress import EgressDecision

from .policy import SecurityEgressPolicy

__all__ = [
    "ControlledEgressProxy",
    "PROXY_DEFAULT_PORT",
    "main",
]

#: 代理默认监听端口（与 ``astra_sandbox.network.DEFAULT_EGRESS_PROXY_PORT`` 一致）。
PROXY_DEFAULT_PORT = 8888

#: 隧道 / 转发超时（秒）。
_SOCKET_TIMEOUT_SECONDS = 30.0

#: 单次中继缓冲大小。
_RELAY_BUFFER = 65536


def _split_host_port(authority: str, default_port: int) -> tuple[str, int]:
    """把 ``host[:port]`` 解析为 ``(host, port)``（缺端口用 ``default_port``）。"""
    host, _, port_text = authority.strip().partition(":")
    if not host:
        return "", default_port
    try:
        port = int(port_text) if port_text else default_port
    except ValueError:
        port = default_port
    return host, port


def _relay(left: socket.socket, right: socket.socket) -> None:
    """双向中继两 socket 数据（任一端关闭即结束）。"""
    sockets = [left, right]
    try:
        while True:
            readable, _, errored = select.select(sockets, [], sockets, _SOCKET_TIMEOUT_SECONDS)
            if errored or not readable:
                break
            for source in readable:
                data = source.recv(_RELAY_BUFFER)
                if not data:
                    return
                target = right if source is left else left
                target.sendall(data)
    except OSError:
        return


class ControlledEgressProxy:
    """受控转发代理：对每次连接 / 请求调用既有 :class:`SecurityEgressPolicy`。

    Attributes:
        policy: **注入的**出网策略（唯一判定源；本代理不复制 / 不替换其判定）。
    """

    def __init__(
        self,
        policy: SecurityEgressPolicy,
        *,
        host: str = "0.0.0.0",
        port: int = PROXY_DEFAULT_PORT,
        upstream_timeout_seconds: float = _SOCKET_TIMEOUT_SECONDS,
    ) -> None:
        """构造。

        Args:
            policy: 出网策略（**复用** 既有唯一判定源）。
            host: 监听地址。
            port: 监听端口。
            upstream_timeout_seconds: 上游建连超时（秒）。
        """
        self._policy = policy
        self._host = host
        self._port = port
        self._upstream_timeout = upstream_timeout_seconds
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def policy(self) -> SecurityEgressPolicy:
        """返回注入的出网策略（供测试检视同一性）。"""
        return self._policy

    @property
    def host(self) -> str:
        """监听地址。"""
        return self._host

    @property
    def port(self) -> int:
        """监听端口。"""
        return self._port

    # -- 判定（复用唯一源；不抛） ------------------------------------------

    def authorize_url(self, url: str) -> EgressDecision:
        """按完整 URL 判定（委托 :meth:`SecurityEgressPolicy.authorize`）。"""
        return self._policy.authorize(url)

    def authorize_connect(self, host: str, port: int = 443) -> EgressDecision:
        """按 ``CONNECT host:port`` 判定（归一为 ``https://host:port`` 委托策略）。"""
        return self._policy.authorize(f"https://{host}:{port}")

    def enforce_connect(self, host: str, port: int = 443) -> str:
        """强制判定（拒绝即抛）；放行返回**钉定 IP**。"""
        return self._policy.enforce(f"https://{host}:{port}")

    # -- 上游建连 -----------------------------------------------------------

    def open_upstream(self, host: str, port: int, pinned_ip: str | None) -> socket.socket | None:
        """经**钉定 IP** 建上游连接（失败返回 ``None``，不抛）。"""
        target = pinned_ip or host
        try:
            return socket.create_connection((target, port), timeout=self._upstream_timeout)
        except OSError:
            return None

    # -- 服务生命周期 -------------------------------------------------------

    def make_server(self) -> HTTPServer:
        """构造底层 HTTP 服务器（供测试 / 显式驱动）。"""
        proxy = self

        class _Server(HTTPServer):
            daemon_threads = True

            def __init__(self, address: tuple[str, int]) -> None:
                super().__init__(address, _ProxyRequestHandler)
                self.proxy = proxy  # type: ignore[attr-defined]

        return _Server((self._host, self._port))

    def serve_forever(self) -> None:
        """**阻塞**运行代理服务。"""
        self._server = self.make_server()
        self._server.serve_forever()

    def start_background(self) -> None:
        """在后台线程启动代理（幂等：重复调用不重启）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._server = self.make_server()
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="astra-egress-proxy", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """停止代理（幂等）。"""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None


class _ProxyRequestHandler(BaseHTTPRequestHandler):
    """代理请求处理器（``CONNECT`` 隧道 + 绝对 URI HTTP 转发）。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 覆盖基类签名
        """**不落日志**：避免主机名 / 潜在凭证进入日志（脱敏纪律）。"""
        return

    @property
    def _proxy(self) -> ControlledEgressProxy:
        return self.server.proxy  # type: ignore[attr-defined]

    def do_CONNECT(self) -> None:  # noqa: N802 - 基类约定
        """HTTPS 隧道：判定 → 建隧道。"""
        host, port = _split_host_port(self.path, 443)
        if not host:
            self.send_error(400, "bad CONNECT target")
            return
        decision = self._proxy.authorize_connect(host, port)
        if not decision.allowed:
            self.send_error(403, "egress denied")
            return
        upstream = self._proxy.open_upstream(host, port, decision.resolved_ip)
        if upstream is None:
            self.send_error(502, "upstream unavailable")
            return
        try:
            self.send_response(200, "Connection Established")
            self.end_headers()
            _relay(self.connection, upstream)
        finally:
            upstream.close()

    def do_GET(self) -> None:  # noqa: N802
        """HTTP 转发（绝对 URI）。"""
        self._forward_http()

    def do_POST(self) -> None:  # noqa: N802
        """HTTP 转发（绝对 URI）。"""
        self._forward_http()

    def _forward_http(self) -> None:
        """判定 + 转发单个 HTTP 请求（``Connection: close``）。"""
        url = self.path
        parsed = urlsplit(url)
        host = parsed.hostname
        if not host:
            self.send_error(400, "bad request target")
            return
        decision = self._proxy.authorize_url(url)
        if not decision.allowed:
            self.send_error(403, "egress denied")
            return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        upstream = self._proxy.open_upstream(host, port, decision.resolved_ip)
        if upstream is None:
            self.send_error(502, "upstream unavailable")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b""
            path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            header_lines = [f"{self.command} {path} HTTP/1.1"]
            for key, value in self.headers.items():
                if key.lower() in {"proxy-connection", "connection"}:
                    continue
                header_lines.append(f"{key}: {value}")
            header_lines.append("Connection: close")
            request = ("\r\n".join(header_lines) + "\r\n\r\n").encode("latin-1") + body
            upstream.sendall(request)
            self.send_response_only(200)
            _relay(upstream, self.connection)
        finally:
            upstream.close()


def main(argv: list[str] | None = None) -> int:
    """``python -m astra_security.egress.proxy`` 入口：按配置启动受控代理。

    配置在**函数级**读取（``ASTRA_EGRESS__*`` → :meth:`SecurityEgressPolicy.from_settings`），
    默认**拒绝全部**出网（空白名单）；部署方显式配置 allow 后生效。

    Returns:
        进程退出码（``serve_forever`` 阻塞，故正常不返回）。
    """
    parser = argparse.ArgumentParser(description="Astra AI 受控 Egress Proxy（T2-56）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=PROXY_DEFAULT_PORT, help="监听端口（默认 8888）")
    args = parser.parse_args(argv)

    from astra_config import get_settings

    policy = SecurityEgressPolicy.from_settings(get_settings())
    proxy = ControlledEgressProxy(policy, host=args.host, port=args.port)
    proxy.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 直执行
    raise SystemExit(main())
