"""Astra AI 基础模块（``astra_core``）。

全平台地基，包含：

- :mod:`astra_core.id`：**统一 ID 入口** ``generate_id()``（UUIDv7，决策 D2）
- :mod:`astra_core.result`：``Result`` / ``Ok`` / ``Err``（无异常控制流）
- :mod:`astra_core.error`：``DomainError`` 基类（+ 重导出 ``ErrorCode``）
- :mod:`astra_core.error_codes`：统一错误码枚举
- :mod:`astra_core.exception`：``AstraError`` 及跨层统一异常层级
- :mod:`astra_core.events`：``DomainEvent`` 领域事件基类
"""

from __future__ import annotations

from .error import DomainError
from .error_codes import ErrorCode
from .events import DomainEvent
from .exception import (
    AstraError,
    ConflictError,
    NotFoundError,
    NotImplementedYetError,
    PermissionDeniedError,
    UnauthorizedError,
    ValidationError,
)
from .id import generate_id
from .result import Err, Ok, Result

__all__ = [
    # id（唯一 ID 入口）
    "generate_id",
    # result
    "Result",
    "Ok",
    "Err",
    # error / error codes / exception
    "DomainError",
    "ErrorCode",
    "AstraError",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "PermissionDeniedError",
    "UnauthorizedError",
    "NotImplementedYetError",
    # events
    "DomainEvent",
]
