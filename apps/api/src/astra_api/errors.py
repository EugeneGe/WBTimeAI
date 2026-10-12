"""统一异常处理：将异常映射为 ``{code, message, data, request_id}`` 响应。

对齐总纲 §11.1（响应壳）/ §11.2（错误码 → HTTP 映射）：

- 失败响应恒为四字段壳 ``{code, message, data, request_id}``（``code`` 为
  :class:`~astra_core.ErrorCode` 枚举字面值；``data`` 为附加上下文）；
- ``request_id`` 取自 **API 层** 当前请求上下文（``request.state``，由
  :class:`~astra_api.middleware.request_context.RequestContextMiddleware` 注入），
  **不修改** ``astra_core``（``DomainError.to_dict()`` 恒为三字段）；
- ``request_id`` 与响应头 ``X-Request-Id`` 同源，保证「体 == 头」。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_logging import get_request_id
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

__all__ = ["register_exception_handlers"]

#: 错误码 → HTTP 状态码（按错误码族映射，供 ``DomainError`` 使用）。
#: 未列出的错误码回退到异常自身的 ``status_code``。
#:
#: ⚠️ 与总纲 §11.2 的偏差（已在施工记录 T1-04 备注）：
#: - ``VALIDATION_ERROR`` 保持 **422**（FastAPI 校验语义 + Phase 0 已验收契约），
#:   总纲 §11.2 列为 400；
#: - §11.2 的 ``UNAUTHENTICATED`` / ``NOT_IMPLEMENTED_YET`` 为设计近似命名，
#:   实现按 ``ErrorCode`` 实际枚举名 ``UNAUTHORIZED`` / ``NOT_IMPLEMENTED`` 映射。
_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.CONFLICT: 409,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.CONFIGURATION_ERROR: 422,
    # 身份 / 多租户
    ErrorCode.TENANT_NOT_FOUND: 404,
    ErrorCode.USER_NOT_FOUND: 404,
    ErrorCode.ORGANIZATION_NOT_FOUND: 404,
    ErrorCode.WORKSPACE_NOT_FOUND: 404,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.CREDENTIAL_NOT_FOUND: 404,
    ErrorCode.USER_ALREADY_EXISTS: 409,
    # 认证 / 鉴权
    ErrorCode.AUTH_INVALID_CREDENTIALS: 401,
    ErrorCode.AUTH_TOKEN_EXPIRED: 401,
    ErrorCode.AUTH_TOKEN_INVALID: 401,
    ErrorCode.AUTH_TOKEN_REVOKED: 401,
    ErrorCode.AUTH_ACCOUNT_LOCKED: 423,
    # Runtime 执行内核（W5 / T1-23）· 幂等 / 恢复（W6 / T1-29、T1-31）
    ErrorCode.MAX_ITERATIONS: 422,
    ErrorCode.CONTEXT_LENGTH_EXCEEDED: 422,
    ErrorCode.TOOL_TIMEOUT: 504,
    ErrorCode.IDEMPOTENCY_KEY_REUSE: 409,
    ErrorCode.HEARTBEAT_TIMEOUT: 500,
    # R3 / T2-60：事件续读游标过期（I-P2-39「过期游标返回稳定错误码」）→ 410 Gone。
    ErrorCode.EVENT_CURSOR_EXPIRED: 410,
    # R5 补全轮（F8a）· 执行期资源限额（pending / artifact 等）→ 429 Too Many Requests。
    # 原映射表未列该码（回退 ``DomainError.status_code``）；此处显式登记（最接近语义 = 429）。
    ErrorCode.RESOURCE_LIMIT_EXCEEDED: 429,
}

#: HTTP 状态码 → 统一错误码（用于框架层抛出的 ``HTTPException``）。
_CODE_BY_HTTP_STATUS: dict[int, ErrorCode] = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.PERMISSION_DENIED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
}


def _current_request_id(request: Request) -> str | None:
    """从当前请求上下文取 ``request_id``（体 == 头 同源）。

    优先读取 ``request.state.request_id``（由请求上下文中间件注入）；若因边界
    场景缺失，则回退到日志上下文的 ``get_request_id()``。
    """
    value = getattr(request.state, "request_id", None)
    if value is None:
        value = get_request_id()
    return value


def _payload(
    code: ErrorCode,
    message: str,
    data: Any | None = None,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """构造统一失败响应体 ``{code, message, data, request_id}``（总纲 §11.1）。"""
    return {
        "code": str(code),
        "message": message,
        "data": data if data is not None else {},
        "request_id": request_id,
    }


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。

    - :class:`~astra_core.error.DomainError`（含其子类 ``AstraError`` 及全部业务异常）
      → 按其 ``code`` 解析状态码 + 自身 ``{code, message, data}`` **并补 ``request_id``**；
    - 请求校验失败 → 422 ``{code, message, data, request_id}``；
    - 框架层 ``HTTPException`` → 依状态码映射为统一错误码（如 404→``NOT_FOUND``、
      405→``METHOD_NOT_ALLOWED``），响应体仍为四字段壳；
    - 未捕获异常 → 500 ``{code, message, data, request_id}``。
    """

    @app.exception_handler(DomainError)
    async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        status_code = _STATUS_BY_CODE.get(exc.code, exc.status_code)
        payload = dict(exc.to_dict())
        payload["request_id"] = _current_request_id(request)
        return JSONResponse(status_code=status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_payload(
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                {"errors": jsonable_encoder(exc.errors())},
                request_id=_current_request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _CODE_BY_HTTP_STATUS.get(exc.status_code, ErrorCode.UNKNOWN)
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(code, str(exc.detail), request_id=_current_request_id(request)),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=_payload(
                ErrorCode.INTERNAL_ERROR,
                "Internal server error",
                request_id=_current_request_id(request),
            ),
        )
