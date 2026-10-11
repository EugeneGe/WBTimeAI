"""审计组领域实体（设计 §2.15.1 审计组 / §2.18，修订 R-14）。

纯 dataclass，零框架依赖（C-03）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..constants import AUDIT_OUTCOME_SUCCESS
from .base import AggregateRoot

__all__ = ["AuditLog"]


@dataclass
class AuditLog(AggregateRoot):
    """基础审计记录（对齐需求 §47 十要素 / 设计 §2.18.1）.

    Attributes:
        organization_id: 组织标识（可空）。
        workspace_id: 工作区标识（可空）。
        user_id: 操作者标识（可空，存储自 ``actor_id``）。
        agent_id / run_id / tool_call_id: 关联 Agent / Run / ToolCall（可空）。
        action: 动作（登录 / 授权变更 / 工具调用 / 审批 / …）。
        resource_type / resource_id: 资源类型 / 标识（可空）。
        outcome: 结果（``AUDIT_OUTCOME_*``）。
        duration_ms: 耗时（毫秒，可空）。
        token_usage: token 用量（JSON 结构，可空）。
        cost: 成本（可空）。
        request_id: 请求标识（幂等去重键）。
        trace_id: 链路标识（可空）。
        ip: 来源 IP（可空）。
        metadata: 入参 / 结果摘要（**已脱敏**，可空）。
        extensions: 命名空间扩展（不得覆写标准字段，可空）。
    """

    organization_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
    action: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    outcome: str = AUDIT_OUTCOME_SUCCESS
    duration_ms: int | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    cost: Decimal | None = None
    request_id: str = ""
    trace_id: str | None = None
    ip: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)
