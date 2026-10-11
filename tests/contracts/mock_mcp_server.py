"""Mock MCP Server（**零第三方依赖**；W2 / T2-11 契约测试用）。

支持两种模式：

- **stdio**：``python mock_mcp_server.py --stdio`` —— 从 stdin 读 newline-delimited JSON-RPC，
  向 stdout 写响应（标准 MCP stdio 传输形状）；
- **sse**：:func:`start_sse_server` 在 ``127.0.0.1`` 上起一个 ``http.server``，``POST`` 收到
  JSON-RPC 后以 ``text/event-stream`` 响应（标准 MCP SSE 传输形状）。

仅用**标准库**（``json`` / ``sys`` / ``threading`` / ``time`` / ``http.server``）。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

__all__ = ["DEFAULT_TOOLS", "handle", "run_stdio", "start_sse_server"]

#: 默认发现的 Tools（``tools/list`` 返回）。
DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "回显文本",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "outputSchema": {},
    },
    {
        "name": "add",
        "description": "两数求和",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        "outputSchema": {},
    },
]


def handle(
    payload: dict[str, Any],
    *,
    delay_s: float = 0.0,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 消息（返回响应；通知返回 ``None``）。"""
    tool_list = tools if tools is not None else DEFAULT_TOOLS
    method = payload.get("method")
    request_id = payload.get("id")

    if method == "notifications/initialized":
        return None
    if delay_s:
        time.sleep(delay_s)

    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mock-mcp", "version": "0.0.1"},
        }
    elif method == "tools/list":
        result = {"tools": tool_list}
    elif method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        text = f"echo:{name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"
        result = {"content": [{"type": "text", "text": text}], "isError": False}
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def run_stdio(*, delay_s: float = 0.0, tools: list[dict[str, Any]] | None = None) -> None:
    """stdio 模式主循环（读 stdin 行 → 写 stdout 行）。"""
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        response = handle(payload, delay_s=delay_s, tools=tools)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


class _Handler(BaseHTTPRequestHandler):
    """SSE 模式请求处理器（``POST`` JSON-RPC → ``text/event-stream``）。"""

    def do_POST(self) -> None:  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        server: MockSSEServer = self.server  # type: ignore[assignment]
        response = handle(payload, delay_s=server.delay_s, tools=server.tools)
        if response is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = json.dumps(response, ensure_ascii=False)
        body = f"event: message\ndata: {data}\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """静默（不落日志）。"""
        return None


class MockSSEServer(ThreadingHTTPServer):
    """带 ``delay_s`` / ``tools`` 的 SSE 模式 HTTP Server。"""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        delay_s: float = 0.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(address, _Handler)
        self.delay_s = delay_s
        self.tools = tools if tools is not None else DEFAULT_TOOLS


def start_sse_server(
    *,
    delay_s: float = 0.0,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[MockSSEServer, str]:
    """在 ``127.0.0.1`` 起 SSE 模式 Server（返回 ``(server, url)``）。

    ``url`` 形如 ``http://127.0.0.1:<port>/mcp``；调用方负责 ``shutdown`` + ``server_close``。
    """
    server = MockSSEServer(("127.0.0.1", 0), delay_s=delay_s, tools=tools)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    return server, f"http://{host}:{port}/mcp"


if __name__ == "__main__":  # pragma: no cover - 子进程入口
    if "--stdio" in sys.argv:
        run_stdio()
    else:  # pragma: no cover - 误用
        raise SystemExit("usage: mock_mcp_server.py --stdio")
