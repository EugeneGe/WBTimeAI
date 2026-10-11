"""Sandbox 组值对象（设计 §2.11 / 修订 R-05）。

纯标准库实现（零框架依赖，C-03）：

- :class:`SandboxProviderKind`：``docker`` / ``local_process``（唯一执行出口）；
- :class:`SandboxSessionStatus`：会话状态（``CREATED`` / ``RUNNING`` / ``STOPPED`` / ``FAILED``）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from astra_core import ValidationError

from ..constants import (
    SANDBOX_PROVIDER_DOCKER,
    SANDBOX_PROVIDER_LOCAL_PROCESS,
    SANDBOX_SESSION_STATUS_CREATED,
    SANDBOX_SESSION_STATUS_FAILED,
    SANDBOX_SESSION_STATUS_RUNNING,
    SANDBOX_SESSION_STATUS_STOPPED,
)

__all__ = ["SandboxProviderKind", "SandboxSessionStatus"]


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


class SandboxProviderKind(StrEnum):
    """沙箱提供方种类（设计 §2.11）。"""

    DOCKER = SANDBOX_PROVIDER_DOCKER
    LOCAL_PROCESS = SANDBOX_PROVIDER_LOCAL_PROCESS

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | SandboxProviderKind) -> SandboxProviderKind:
        """校验并归一化沙箱提供方。"""
        return _ensure_value(cls, value, field_name="sandbox_provider")


class SandboxSessionStatus(StrEnum):
    """沙箱会话状态（设计 §2.11）。"""

    CREATED = SANDBOX_SESSION_STATUS_CREATED
    RUNNING = SANDBOX_SESSION_STATUS_RUNNING
    STOPPED = SANDBOX_SESSION_STATUS_STOPPED
    FAILED = SANDBOX_SESSION_STATUS_FAILED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | SandboxSessionStatus) -> SandboxSessionStatus:
        """校验并归一化沙箱会话状态。"""
        return _ensure_value(cls, value, field_name="sandbox_session_status")
