"""跨层统一异常层级。

以 :class:`AstraError` 作为平台异常基类（继承自 :class:`DomainError`），
派生常用语义异常。API 层（T0-08）将捕获 :class:`AstraError` 并映射为
统一响应 ``{code, message, data}``（HTTP 状态取 ``status_code``）。
"""

from __future__ import annotations

from .error import DomainError
from .error_codes import ErrorCode

__all__ = [
    "AstraError",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "PermissionDeniedError",
    "UnauthorizedError",
    "NotImplementedYetError",
]


class AstraError(DomainError):
    """Astra AI 平台统一异常基类。"""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = "Internal error"
    status_code: int = 500


class NotFoundError(AstraError):
    """资源不存在（HTTP 404）。"""

    code: ErrorCode = ErrorCode.NOT_FOUND
    message: str = "Resource not found"
    status_code: int = 404


class ValidationError(AstraError):
    """参数/数据校验失败（HTTP 422）。"""

    code: ErrorCode = ErrorCode.VALIDATION_ERROR
    message: str = "Validation error"
    status_code: int = 422


class ConflictError(AstraError):
    """资源冲突（HTTP 409）。"""

    code: ErrorCode = ErrorCode.CONFLICT
    message: str = "Resource conflict"
    status_code: int = 409


class PermissionDeniedError(AstraError):
    """权限不足（HTTP 403）。"""

    code: ErrorCode = ErrorCode.PERMISSION_DENIED
    message: str = "Permission denied"
    status_code: int = 403


class UnauthorizedError(AstraError):
    """未认证（HTTP 401）。"""

    code: ErrorCode = ErrorCode.UNAUTHORIZED
    message: str = "Unauthorized"
    status_code: int = 401


class NotImplementedYetError(AstraError):
    """功能尚未实现（HTTP 501）。

    用于 Phase 0 骨架路由占位（T0-08），亦服务于 Feature Flag 的
    「行为降级而非模块缺失」约定。
    """

    code: ErrorCode = ErrorCode.NOT_IMPLEMENTED
    message: str = "Not implemented yet"
    status_code: int = 501
