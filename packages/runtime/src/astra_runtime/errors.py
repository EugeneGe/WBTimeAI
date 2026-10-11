"""Runtime 运行时错误工厂（复用 :class:`astra_core.ErrorCode`，设计 §2.7.1 / §2.7.2）。

W5 / T1-23 / T1-24：``MAX_ITERATIONS`` / ``CONTEXT_LENGTH_EXCEEDED`` / ``TOOL_TIMEOUT``
三个运行时错误码已加入 ``astra_core.error_codes.ErrorCode``（F17）。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode

__all__ = [
    "max_iterations_error",
    "context_length_exceeded_error",
    "tool_timeout_error",
    "run_conflict_error",
    "run_timeout_error",
]

#: Run 级超时错误类型（遥测字段 ``agent_run.error_type`` 用字符串，无独立 ``ErrorCode``）。
RUN_TIMEOUT = "RUN_TIMEOUT"


def max_iterations_error(message: str | None = None, **data: object) -> DomainError:
    """ReAct 迭代上界（``MAX_ITERATIONS``）。"""
    return DomainError(
        message or "ReAct 循环达到最大迭代次数",
        code=ErrorCode.MAX_ITERATIONS,
        data=dict(data),
    )


def context_length_exceeded_error(message: str | None = None, **data: object) -> DomainError:
    """上下文超窗且无法通过 ``TRUNCATE_OLDEST`` 满足（``CONTEXT_LENGTH_EXCEEDED``）。"""
    return DomainError(
        message or "上下文长度超出预算，且无法通过 TRUNCATE_OLDEST 满足",
        code=ErrorCode.CONTEXT_LENGTH_EXCEEDED,
        data=dict(data),
    )


def tool_timeout_error(message: str | None = None, **data: object) -> DomainError:
    """工具执行超时（``TOOL_TIMEOUT``）。"""
    return DomainError(
        message or "工具执行超时",
        code=ErrorCode.TOOL_TIMEOUT,
        data=dict(data),
    )


def run_conflict_error(message: str | None = None, **data: object) -> DomainError:
    """同 Conversation 活跃 Run 超限（``CONFLICT`` → HTTP 409，非静默排队）。"""
    return DomainError(
        message or "同一会话活跃 Run 数超限，拒绝新 Run",
        code=ErrorCode.CONFLICT,
        status_code=409,
        data=dict(data),
    )


def run_timeout_error(message: str | None = None, **data: object) -> DomainError:
    """Run 级总超时（``status_code=504``）。"""
    return DomainError(
        message or "Run 执行总超时",
        code=ErrorCode.TOOL_TIMEOUT,
        status_code=504,
        data=dict(data),
    )
