"""统一响应壳中间件（总纲 §11.1）。

对**成功的 JSON 响应**统一套用响应壳 ``{code, message, data, request_id}``：

- ``code``：成功恒为 ``0``；
- ``message``：成功恒为 ``"ok"``；
- ``data``：原始响应体（对象 / 数组 / 标量）；
- ``request_id``：取自响应头 ``X-Request-Id``（与 :class:`~astra_api.middleware.\
request_context.RequestContextMiddleware` 同源），保证「响应体 == 响应头」。

**不改动**（原样透传）：

- **失败响应**（``status_code >= 400``）：由异常处理器直接产出四字段壳（见
  :mod:`astra_api.errors`），本中间件**跳过**，避免二次包裹；
- **非 JSON 响应**（如 ``/metrics`` 的 ``text/plain``）；
- **SSE**（``text/event-stream``）：§11.1 例外——流式帧不套壳，``request_id`` /
  ``trace_id`` 仅经响应头下发；
- **框架端点** ``/openapi.json``（供 Swagger / Redoc 消费，不得套壳）；
- **已是响应壳**的响应（幂等，避免二次包裹）。

🔴 本模块**不判断 mode**（唯一分流点在 ``astra_config.providers``）。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from astra_logging import get_request_id
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

__all__ = ["ResponseShellMiddleware"]

#: 成功响应壳常量（总纲 §11.1）。
_SUCCESS_CODE: int = 0
_SUCCESS_MESSAGE: str = "ok"

#: 响应壳字段集合（用于「已是壳」的文档说明；判定见 :func:`_is_success_shell`）。
_SHELL_KEYS: frozenset[str] = frozenset({"code", "message", "data", "request_id"})

#: 请求 / 响应头名称。
_REQUEST_ID_HEADER: str = "X-Request-Id"

#: 不套壳的框架端点路径（OpenAPI 文档等，供工具消费）。
_SKIP_PATHS: frozenset[str] = frozenset({"/openapi.json"})

#: 构造新响应时需剔除的头（由新的响应对象重新计算）。
_STRIPPED_HEADERS: frozenset[str] = frozenset({"content-length", "content-type"})


def _is_success_shell(parsed: dict[str, object]) -> bool:
    """判断响应体是否**已是成功响应壳**（A27 · 值判定，非启发式）。

    仅当四顶层键**同时**满足成功语义时视为「已是壳」：

    - ``code == 0``（:data:`_SUCCESS_CODE`）；
    - ``message == "ok"``（:data:`_SUCCESS_MESSAGE`）；
    - 含 ``data`` 键；
    - 含 ``request_id`` 键。

    成功壳**唯一**由本中间件产出；失败壳（``status_code >= 400``）已在前置分支跳过。
    采用**值判定**消除「业务 DTO 恰含四顶层键」被误判为壳、从而缺失壳的缺陷
    （W1 遗留 ``OBS-QA-1``）。约定：业务 DTO 顶层键**不得**同时使用
    ``{code, message, data, request_id}``（语义相近字段改用 ``result`` / ``items`` / ``payload``）。
    """
    return (
        parsed.get("code") == _SUCCESS_CODE
        and parsed.get("message") == _SUCCESS_MESSAGE
        and "data" in parsed
        and "request_id" in parsed
    )


class ResponseShellMiddleware(BaseHTTPMiddleware):
    """为成功的 JSON 响应套用统一响应壳 ``{code, message, data, request_id}``。"""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """处理请求并为成功 JSON 响应套壳。

        Args:
            request: 入站请求。
            call_next: 下游 ASGI 调用。

        Returns:
            套壳后的成功响应；失败 / 非 JSON / SSE / 框架端点响应原样返回。
        """
        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        if (
            response.status_code >= 400
            or request.url.path in _SKIP_PATHS
            or "application/json" not in content_type
        ):
            return response

        return await self._wrap_success_json(request, response)

    async def _wrap_success_json(self, request: Request, response: Response) -> Response:
        """读取成功 JSON 响应体并套壳（读取后一律返回新响应）。"""
        # ``BaseHTTPMiddleware.call_next`` 返回的响应携带 ``body_iterator``
        # （starlette 基类类型未声明该属性）。
        body_iterator = response.body_iterator  # type: ignore[attr-defined]
        chunks = [chunk async for chunk in body_iterator]
        body = b"".join(
            chunk.encode("utf-8") if isinstance(chunk, str) else chunk for chunk in chunks
        )
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in _STRIPPED_HEADERS
        }

        if not body:
            return Response(status_code=response.status_code, headers=headers)

        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            # 非合法 JSON：原样重建（保持字节与状态码）。
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type="application/json",
            )

        if isinstance(parsed, dict) and _is_success_shell(parsed):
            # 已是响应壳：幂等，避免二次包裹。
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type="application/json",
            )

        shell = {
            "code": _SUCCESS_CODE,
            "message": _SUCCESS_MESSAGE,
            "data": parsed,
            "request_id": self._request_id(request, response),
        }
        return JSONResponse(content=shell, status_code=response.status_code, headers=headers)

    @staticmethod
    def _request_id(request: Request, response: Response) -> str | None:
        """取 ``request_id``：优先响应头（与头同源），回退请求状态 / 日志上下文。"""
        header_value = response.headers.get(_REQUEST_ID_HEADER)
        if header_value:
            return header_value
        state_value = getattr(request.state, "request_id", None)
        if state_value is not None:
            return state_value
        return get_request_id()
