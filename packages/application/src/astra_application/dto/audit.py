"""审计 DTO（设计 §2.18.1）。

:class:`AuditRecordDTO` 承载**规范字段**（十要素）+ ``extensions`` 命名空间扩展：

- 规范字段之外的数据**必须**放入 ``extensions``，键采用稳定反向域名 / 插件 ID 命名空间，
  且**不得覆写**规范字段（本 DTO 在 ``__post_init__`` 校验）；
- ``actor_id`` 存储为 ``user_id``、``occurred_at`` 存储为 ``created_at``（提供只读别名）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from astra_core import ValidationError
from astra_domain import AUDIT_OUTCOME_SUCCESS, AuditLog

from .base import DTO

__all__ = ["AuditRecordDTO", "STANDARD_AUDIT_FIELDS"]

#: 规范字段名（``extensions`` 不得覆写其中任何一项）。
STANDARD_AUDIT_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "tenant_id",
        "organization_id",
        "workspace_id",
        "user_id",
        "agent_id",
        "run_id",
        "tool_call_id",
        "action",
        "resource_type",
        "resource_id",
        "outcome",
        "duration_ms",
        "token_usage",
        "cost",
        "request_id",
        "trace_id",
        "ip",
        "metadata",
        "extensions",
        "created_at",
    }
)


@dataclass
class AuditRecordDTO(DTO):
    """审计记录 DTO（规范字段 + ``extensions``）。

    Attributes:
        tenant_id: 强制隔离字段（纳入隔离不变量 I-2/I-3）。
        action: 动作（登录 / 授权变更 / 工具调用 / 审批 / …）。
        request_id: 请求标识（重放幂等去重键）。
        user_id: 操作者标识（存储自 ``actor_id``）。
        organization_id / workspace_id: 组织 / 工作区归属（可空）。
        agent_id / run_id / tool_call_id: 关联 Agent / Run / ToolCall（可空）。
        resource_type / resource_id: 资源类型 / 标识（可空）。
        outcome: 结果（``SUCCESS`` / ``DENIED`` / ``FAILED``）。
        duration_ms: 耗时（毫秒，可空）。
        token_usage: token 用量（JSON 结构）。
        cost: 成本（可空）。
        trace_id: 链路标识（可空）。
        ip: 来源 IP（可空）。
        metadata: 入参 / 结果摘要（**待掩码**）。
        extensions: 命名空间扩展（不得覆写规范字段）。
        id: 记录标识（可空；为空时由实体默认 ``generate_id`` 生成）。
        created_at: 发生时刻（可空；存储自 ``occurred_at``）。
    """

    tenant_id: str = ""
    action: str = ""
    request_id: str = ""
    user_id: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    outcome: str = AUDIT_OUTCOME_SUCCESS
    duration_ms: int | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    cost: Decimal | None = None
    trace_id: str | None = None
    ip: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValidationError("审计记录 tenant_id 不能为空", data={"field": "tenant_id"})
        if not self.action:
            raise ValidationError("审计记录 action 不能为空", data={"field": "action"})
        if not self.request_id:
            raise ValidationError("审计记录 request_id 不能为空", data={"field": "request_id"})
        overridden = STANDARD_AUDIT_FIELDS & set(self.extensions)
        if overridden:
            raise ValidationError(
                "extensions 不得覆写规范字段",
                data={"field": "extensions", "overridden": sorted(overridden)},
            )

    @property
    def actor_id(self) -> str | None:
        """规范字段 ``actor_id``（存储为 ``user_id``）。"""
        return self.user_id

    @property
    def occurred_at(self) -> datetime | None:
        """规范字段 ``occurred_at``（存储为 ``created_at``）。"""
        return self.created_at

    def to_entity(self, *, metadata: dict[str, Any] | None = None) -> AuditLog:
        """转换为 :class:`~astra_domain.AuditLog` 实体。

        Args:
            metadata: 覆写后的 ``metadata``（通常为**已脱敏**版本）；为 ``None``
                时使用本 DTO 的 ``metadata``。

        Returns:
            审计记录实体（``id`` 缺省时由实体默认 ``generate_id`` 生成）。
        """
        entity = AuditLog(
            tenant_id=self.tenant_id,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            agent_id=self.agent_id,
            run_id=self.run_id,
            tool_call_id=self.tool_call_id,
            action=self.action,
            resource_type=self.resource_type,
            resource_id=self.resource_id,
            outcome=self.outcome,
            duration_ms=self.duration_ms,
            token_usage=dict(self.token_usage),
            cost=self.cost,
            request_id=self.request_id,
            trace_id=self.trace_id,
            ip=self.ip,
            metadata=dict(metadata if metadata is not None else self.metadata),
            extensions=dict(self.extensions),
        )
        if self.id is not None:
            entity.id = self.id
        if self.created_at is not None:
            entity.created_at = self.created_at
        return entity
