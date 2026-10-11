"""Plugin / ExtensionPoint 跨包 DTO（设计 §2.14.1；W1b 架构裁定 §1.2）。

本模块是 **8 个 ExtensionPoint 契约的输入 / 输出类型**的**唯一来源**，随其 Protocol
一并冻结（Phase 3–4 只填充实现，不得改签名）。所有 DTO 均为 ``frozen=True`` dataclass
或 :class:`enum.StrEnum`，**零框架依赖**（C-03）——不得 import Web / ORM / 校验框架。

- :data:`AuditEvent` 为既有 :class:`~astra_domain.entities.audit.AuditLog` 的**类型别名**
  （复用、不重定义，裁定 §1.3④）；
- ``ChatMessage`` / ``ChatResult`` / ``ModelProvider`` 复用 ``astra_model``（见 ``astra_plugin``）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .entities.audit import AuditLog

__all__ = [
    "ExtensionContext",
    "Principal",
    "AuthCredential",
    "PolicyRequest",
    "PolicyEffect",
    "PolicyDecision",
    "PolicyExplanation",
    "AuditEvent",
    "SinkHealth",
    "RotationResult",
    "ModelRef",
    "ProviderConfig",
    "ModelCapability",
    "ConnectorActionSpec",
    "AuthorizeParams",
    "CredentialRef",
    "ConnectorResult",
    "ConnectorHealth",
    "UISlot",
]


# -- 上下文 / 主体 -----------------------------------------------------------


@dataclass(frozen=True)
class ExtensionContext:
    """ExtensionPoint 调用上下文（8 点统一 ``ctx`` 形参，裁定 §1.1-3）。

    Attributes:
        tenant_id: 租户标识（必填）。
        workspace_id: 工作区标识（可空）。
        user_id: 用户标识（可空）。
        request_id: 请求标识（默认空串）。
        trace_id: 链路标识（可空）。
    """

    tenant_id: str
    workspace_id: str | None = None
    user_id: str | None = None
    request_id: str = ""
    trace_id: str | None = None


@dataclass(frozen=True)
class Principal:
    """已认证主体（``auth_provider.authenticate`` 输出）。"""

    subject_id: str
    tenant_id: str
    kind: str
    roles: tuple[str, ...] = ()
    claims: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthCredential:
    """认证凭证（``auth_provider.authenticate`` 输入）。

    🔴 ``payload`` **不得包含明文落日志**（凭证纪律 C-07）。
    """

    scheme: str
    payload: Mapping[str, Any] = field(default_factory=dict)


# -- 策略引擎 -----------------------------------------------------------------


class PolicyEffect(StrEnum):
    """策略裁决效果（对齐 P1-b 预留枚举：``TOOL_EFFECT_*``）。"""

    ALLOW = "ALLOW"
    DENY = "DENY"
    APPROVAL = "APPROVAL"


@dataclass(frozen=True)
class PolicyRequest:
    """策略评估请求（``policy_engine.evaluate`` / ``explain`` 输入）。"""

    subject: Mapping[str, Any]
    action: str
    resource: Mapping[str, Any]
    environment: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    """策略裁决（``policy_engine.evaluate`` 输出）。"""

    effect: PolicyEffect
    matched_policy_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PolicyExplanation:
    """策略裁决解释（``policy_engine.explain`` 输出）。"""

    decision: PolicyDecision
    matched_rules: tuple[str, ...] = ()
    notes: str = ""


# -- 审计 ---------------------------------------------------------------------


#: 审计事件类型别名（复用既有实体，**不重定义**；裁定 §1.3④）。
AuditEvent = AuditLog


@dataclass(frozen=True)
class SinkHealth:
    """审计落点健康状态（``audit_sink.health`` 输出）。"""

    ok: bool
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


# -- 密钥 / 加密 --------------------------------------------------------------


@dataclass(frozen=True)
class RotationResult:
    """密钥轮换结果（``secret_provider.rotate`` 输出；须支持中断恢复 QA-45）。"""

    rotated: bool
    key_version: str | None = None
    resumed: bool = False
    message: str = ""


# -- 模型 ---------------------------------------------------------------------


@dataclass(frozen=True)
class ModelRef:
    """模型引用（``model_gateway.route`` 输出 / 候选）。"""

    provider: str
    model: str


@dataclass(frozen=True)
class ProviderConfig:
    """Provider 装配配置（``model_provider.create`` 输入）。"""

    provider_type: str
    name: str
    options: Mapping[str, Any] = field(default_factory=dict)
    credential_ref: str | None = None


class ModelCapability(StrEnum):
    """模型能力枚举（``model_provider.capabilities`` 输出元素）。"""

    CHAT = "CHAT"
    STREAM = "STREAM"
    EMBEDDINGS = "EMBEDDINGS"
    COUNT_TOKENS = "COUNT_TOKENS"
    TOOLS = "TOOLS"
    VISION = "VISION"


# -- Connector ----------------------------------------------------------------


@dataclass(frozen=True)
class ConnectorActionSpec:
    """Connector 动作声明（``connector.actions`` 输出元素）。"""

    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    required_permission: str | None = None


@dataclass(frozen=True)
class AuthorizeParams:
    """授权参数（``connector.authorize`` 输入）。"""

    scopes: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CredentialRef:
    """凭证引用（``connector.authorize`` 输出；仅引用标识，**不含明文**）。"""

    credential_id: str


@dataclass(frozen=True)
class ConnectorResult:
    """Connector 执行结果（``connector.execute`` 输出）。"""

    ok: bool
    output: Any = None
    error: str | None = None


@dataclass(frozen=True)
class ConnectorHealth:
    """Connector 健康状态（``connector.health`` 输出）。"""

    ok: bool
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


# -- UI 扩展 ------------------------------------------------------------------


@dataclass(frozen=True)
class UISlot:
    """UI 插槽声明（``ui_extension.slots`` 输出元素）。"""

    slot_key: str
    title: str
    entry_url: str
    required_permission: str | None = None
