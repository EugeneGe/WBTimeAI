"""统一错误码（枚举）。

本模块是**错误码的唯一数据源**；:mod:`astra_core.error` 会重导出 ``ErrorCode``，
:mod:`astra_core.exception` 的异常层级与之关联，API 层（T0-08）将其映射为
统一响应 ``{code, message, data}``。
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ErrorCode"]


class ErrorCode(StrEnum):
    """平台统一错误码（``str`` 枚举，序列化即为字面值）。"""

    # -- 通用 ---------------------------------------------------------------
    UNKNOWN = "UNKNOWN"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    # W5 / T2-28（设计 §2.6 / 裁定 B8）：可选解析依赖缺失（**非静默**）。
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"

    # -- 认证 / 鉴权（D1 支撑） --------------------------------------------
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
    AUTH_TOKEN_REVOKED = "AUTH_TOKEN_REVOKED"
    AUTH_ACCOUNT_LOCKED = "AUTH_ACCOUNT_LOCKED"

    # -- 身份 / 多租户 ------------------------------------------------------
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
    ORGANIZATION_NOT_FOUND = "ORGANIZATION_NOT_FOUND"

    # -- Workspace / Task / 凭证 -------------------------------------------
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    CREDENTIAL_NOT_FOUND = "CREDENTIAL_NOT_FOUND"

    # -- 资源上限（W4 / T2-22；设计 §2.5 / §2.9「PARALLEL ≤ max_parallel」） ----
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"

    # -- Runtime（执行内核，W5 / T1-23；设计 §2.7.1 / §2.7.2） ---------------
    MAX_ITERATIONS = "MAX_ITERATIONS"
    CONTEXT_LENGTH_EXCEEDED = "CONTEXT_LENGTH_EXCEEDED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"

    # -- 幂等 / 重启兜底（W6 · T1-29 / T1-31；设计 §2.13.1 / §2.9） ---------
    IDEMPOTENCY_KEY_REUSE = "IDEMPOTENCY_KEY_REUSE"
    HEARTBEAT_TIMEOUT = "HEARTBEAT_TIMEOUT"

    # -- 远程 Task 事件游标（R3 / T2-60；设计 §2.8.1 / §2.9.1；I-P2-39） ----
    #: 事件续读游标已过期（所引用序号已超出保留窗口低水位）。
    #: 🔴 **加性**新增（纯 Python 枚举字面值，**无** DB 枚举迁移）；满足 I-P2-39
    #:    「过期游标返回稳定错误码」。
    EVENT_CURSOR_EXPIRED = "EVENT_CURSOR_EXPIRED"

    def __str__(self) -> str:  # noqa: D105 - 便于日志与序列化
        return self.value
