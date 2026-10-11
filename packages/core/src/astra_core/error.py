"""领域错误基类。

:class:`DomainError` 是**领域层/应用层**可继承的错误基类，携带
:class:`~astra_core.error_codes.ErrorCode` 与结构化 ``data``。

``ErrorCode`` 在本模块重导出，便于使用方 ``from astra_core.error import ErrorCode``。
"""

from __future__ import annotations

from typing import Any

from .error_codes import ErrorCode

__all__ = ["DomainError", "ErrorCode"]


class DomainError(Exception):
    """领域 / 应用错误基类。

    属性：
        code: 统一错误码（默认 :attr:`ErrorCode.UNKNOWN`）。
        message: 人类可读的错误信息。
        data: 附加上下文（须可 JSON 序列化）。
        status_code: 建议的 HTTP 状态码（供 Web 层映射使用，领域层不依赖 Web）。
    """

    code: ErrorCode = ErrorCode.UNKNOWN
    message: str = "Domain error"
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        data: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message if message is not None else self.message
        self.code = code if code is not None else self.code
        self.data: dict[str, Any] = dict(data) if data else {}
        self.status_code = status_code if status_code is not None else self.status_code
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """转换为统一响应字典 ``{code, message, data}``。"""
        return {
            "code": str(self.code),
            "message": self.message,
            "data": self.data,
        }

    def __repr__(self) -> str:  # noqa: D105
        return f"{type(self).__name__}(code={str(self.code)!r}, message={self.message!r})"
