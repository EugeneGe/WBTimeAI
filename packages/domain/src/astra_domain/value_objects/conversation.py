"""Conversation 组值对象（设计 §2.6 / 修订 R-04）。

纯标准库实现（零框架依赖，C-03）：

- :class:`RunMode`：``INLINE`` / ``QUEUED``（断连语义参数化）；
- :class:`RunStatus`：Run 状态 + **终态判定**；
- :class:`MessageRole`：消息角色合法值；
- :class:`ToolCallStatus`：工具调用状态。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from astra_core import ValidationError

from ..constants import (
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_SYSTEM,
    MESSAGE_ROLE_TOOL,
    MESSAGE_ROLE_USER,
    RUN_MODE_INLINE,
    RUN_MODE_QUEUED,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    TOOL_CALL_STATUS_DENIED,
    TOOL_CALL_STATUS_FAILED,
    TOOL_CALL_STATUS_PENDING,
    TOOL_CALL_STATUS_RUNNING,
    TOOL_CALL_STATUS_SUCCESS,
)

__all__ = ["RunMode", "RunStatus", "MessageRole", "ToolCallStatus"]


def _ensure_value(enum_cls: type[StrEnum], value: Any, *, field_name: str) -> Any:
    """校验并归一化字符串枚举取值。"""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise ValidationError(
            f"{field_name} 取值非法",
            data={"field": field_name, "value": str(value)},
        ) from exc


class RunMode(StrEnum):
    """Run 模式（设计 §2.6，修订 R-04）。"""

    INLINE = RUN_MODE_INLINE
    QUEUED = RUN_MODE_QUEUED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | RunMode) -> RunMode:
        """校验并归一化 Run 模式。"""
        return _ensure_value(cls, value, field_name="run_mode")


class RunStatus(StrEnum):
    """Run 状态（设计 §2.6）。

    终态为 ``SUCCESS`` / ``FAILED`` / ``CANCELLED``；``PENDING`` / ``RUNNING``
    为进行中。
    """

    PENDING = RUN_STATUS_PENDING
    RUNNING = RUN_STATUS_RUNNING
    SUCCESS = RUN_STATUS_SUCCESS
    FAILED = RUN_STATUS_FAILED
    CANCELLED = RUN_STATUS_CANCELLED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def terminal_values(cls) -> tuple[str, ...]:
        """返回全部**终态**字面值。"""
        return (cls.SUCCESS.value, cls.FAILED.value, cls.CANCELLED.value)

    @classmethod
    def non_terminal_values(cls) -> tuple[str, ...]:
        """返回全部**进行中**字面值。"""
        return (cls.PENDING.value, cls.RUNNING.value)

    def is_terminal(self) -> bool:
        """判断当前状态是否为终态。"""
        return self in (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.CANCELLED)

    @classmethod
    def is_terminal_value(cls, value: str) -> bool:
        """按字面值判断是否为终态（非法值 → ``ValidationError``）。"""
        return cls.ensure(value).is_terminal()

    @classmethod
    def ensure(cls, value: str | RunStatus) -> RunStatus:
        """校验并归一化 Run 状态。"""
        return _ensure_value(cls, value, field_name="run_status")


class MessageRole(StrEnum):
    """消息角色（设计 §2.6）。"""

    SYSTEM = MESSAGE_ROLE_SYSTEM
    USER = MESSAGE_ROLE_USER
    ASSISTANT = MESSAGE_ROLE_ASSISTANT
    TOOL = MESSAGE_ROLE_TOOL

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | MessageRole) -> MessageRole:
        """校验并归一化消息角色。"""
        return _ensure_value(cls, value, field_name="message_role")


class ToolCallStatus(StrEnum):
    """工具调用状态（设计 §2.6 / §2.5.3）。"""

    PENDING = TOOL_CALL_STATUS_PENDING
    RUNNING = TOOL_CALL_STATUS_RUNNING
    SUCCESS = TOOL_CALL_STATUS_SUCCESS
    FAILED = TOOL_CALL_STATUS_FAILED
    DENIED = TOOL_CALL_STATUS_DENIED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | ToolCallStatus) -> ToolCallStatus:
        """校验并归一化工具调用状态。"""
        return _ensure_value(cls, value, field_name="tool_call_status")
