"""Tool 层错误码与构造助手（**复用** :class:`astra_core.ErrorCode`）。

本模块只做语义化封装：把 Tool 层的常见失败（权限拒绝 / 未授权动作 / 沙箱缺失 /
路径越界 / SSRF 拒绝 / 非法 scope）统一映射为 ``astra_core`` 既有的 :class:`ErrorCode`，
避免在能力包内私造错误码枚举。

🔴 复用（不新增）``ErrorCode`` 成员：``PERMISSION_DENIED`` / ``VALIDATION_ERROR`` /
   ``NOT_FOUND`` / ``CONFIGURATION_ERROR``。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode

__all__ = [
    "ToolErrorCode",
    "permission_denied",
    "validation_error",
    "not_found",
    "sandbox_required",
    "configuration_error",
]


class ToolErrorCode:
    """Tool 层错误码别名（复用 ``ErrorCode``，便于集中检索）。"""

    PERMISSION_DENIED = ErrorCode.PERMISSION_DENIED
    VALIDATION_ERROR = ErrorCode.VALIDATION_ERROR
    NOT_FOUND = ErrorCode.NOT_FOUND
    CONFIGURATION_ERROR = ErrorCode.CONFIGURATION_ERROR


def permission_denied(message: str, **data: Any) -> DomainError:
    """构造「权限拒绝」错误（``PERMISSION_DENIED``）。"""
    return DomainError(message, code=ErrorCode.PERMISSION_DENIED, data=dict(data))


def validation_error(message: str, **data: Any) -> DomainError:
    """构造「校验失败」错误（``VALIDATION_ERROR``）。"""
    return DomainError(message, code=ErrorCode.VALIDATION_ERROR, data=dict(data))


def not_found(message: str, **data: Any) -> DomainError:
    """构造「资源不存在」错误（``NOT_FOUND``）。"""
    return DomainError(message, code=ErrorCode.NOT_FOUND, data=dict(data))


def sandbox_required(message: str, **data: Any) -> DomainError:
    """构造「缺少沙箱」错误（``CONFIGURATION_ERROR``）。"""
    return DomainError(message, code=ErrorCode.CONFIGURATION_ERROR, data=dict(data))


def configuration_error(message: str, **data: Any) -> DomainError:
    """构造「配置错误」错误（``CONFIGURATION_ERROR``）。"""
    return DomainError(message, code=ErrorCode.CONFIGURATION_ERROR, data=dict(data))
