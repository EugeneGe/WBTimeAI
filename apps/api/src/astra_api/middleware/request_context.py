"""请求上下文中间件（设计 §2.7.3 / 总纲 §11.1）。

职责：
- 每次请求生成 ``request_id``（**UUIDv7**；若请求已带 ``X-Request-Id`` 则沿用）与
  ``trace_id``（若已带 ``X-Trace-Id`` 则沿用，否则新建）；
- 写入日志上下文（contextvars），使后续结构化日志自动携带；
- 注入 ``request.state.request_id`` / ``request.state.trace_id``，供响应壳（成功/失败）
  与异常处理器复用 **同一** ``request_id``（保证「响应体 ``request_id`` == 响应头
  ``X-Request-Id``」）；
- 响应（含 SSE 建连响应）统一下发 ``X-Request-Id`` / ``X-Trace-Id`` 响应头。

🔴 本模块**不判断 mode**（唯一分流点在 ``astra_config.providers``）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from astra_core import generate_id
from astra_logging import bind_context, new_trace_id
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

__all__ = ["RequestContextMiddleware"]

#: 请求 / 响应头名称。
REQUEST_ID_HEADER = "X-Request-Id"
TRACE_ID_HEADER = "X-Trace-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每次请求建立 ``request_id`` / ``trace_id`` 上下文并下发响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """建立上下文 → 处理请求 → 下发响应头。

        Args:
            request: 入站请求。
            call_next: 下游 ASGI 调用。

        Returns:
            下游响应（附加 ``X-Request-Id`` / ``X-Trace-Id`` 头）。
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or generate_id()
        trace_id = request.headers.get(TRACE_ID_HEADER) or new_trace_id()

        # 暴露给后续处理（异常处理器 / 响应壳中间件）复用同一 request_id。
        request.state.request_id = request_id
        request.state.trace_id = trace_id

        with bind_context(request_id=request_id, trace_id=trace_id):
            response = await call_next(request)

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        return response
