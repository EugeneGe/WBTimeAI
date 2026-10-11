"""Sandbox 组领域实体（设计 §2.15.1 Sandbox 组 / §2.11）。

纯 dataclass，零框架依赖（C-03）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..constants import SANDBOX_PROVIDER_LOCAL_PROCESS, SANDBOX_SESSION_STATUS_CREATED
from .base import AggregateRoot

__all__ = ["SandboxSession"]


@dataclass
class SandboxSession(AggregateRoot):
    """沙箱会话.

    Attributes:
        run_id: 关联 Run 标识（可空）。
        workspace_id: 归属工作区标识（可空）。
        provider: 提供方（``SandboxProviderKind`` 字面值）。
        image: 镜像（可空）。
        status: 会话状态（``SandboxSessionStatus`` 字面值）。
        container_ref: 容器 / 子进程引用（可空）。
        workdir: 工作目录。
        ended_at: 结束时刻（可空）。
    """

    run_id: str | None = None
    workspace_id: str | None = None
    provider: str = SANDBOX_PROVIDER_LOCAL_PROCESS
    image: str | None = None
    status: str = SANDBOX_SESSION_STATUS_CREATED
    container_ref: str | None = None
    workdir: str = ""
    ended_at: datetime | None = None
