"""``CredentialRepository`` 接口（设计 §2.7）。

对应 ORM 表：``credential``。
🔴 仅接口（零 ORM）；SQLAlchemy 实现位于
``astra_security/repositories/credential_repository.py``。

🔴 记录仅承载 ``encrypted_value``（密文），**永不承载明文**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from astra_core import generate_id

__all__ = [
    "CredentialRecord",
    "CredentialRepository",
    "ModelProviderCredentialRecord",
]


@dataclass
class CredentialRecord:
    """凭证记录（仅持久化字段；``encrypted_value`` 为密文）。

    Attributes:
        id: 凭证唯一标识（UUIDv7，默认经 ``generate_id`` 生成）。
        tenant_id: 所属租户标识。
        workspace_id: 所属工作区标识（可空）。
        provider: 提供方（如 ``openai`` / ``anthropic``）。
        key_type: 键类型（如 ``api_key``）。
        encrypted_value: 密文（AES-256-GCM，**绝非明文**）。
        created_at: 创建时间（UTC）。
        name: 人类可读名（W3 / T2-15；**不得含明文密钥**，可空）。
        status: 状态（``ACTIVE`` / ``DISABLED``；默认 ``ACTIVE``）。
        last_used_at: 最近使用时间（UTC，可空）。
        metadata: 非敏感元数据（**禁明文**）。
    """

    id: str = field(default_factory=generate_id)
    tenant_id: str = ""
    workspace_id: str | None = None
    provider: str = ""
    key_type: str = ""
    encrypted_value: str = ""
    created_at: datetime | None = None
    name: str | None = None
    status: str = "ACTIVE"
    last_used_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelProviderCredentialRecord:
    """``model_provider`` × ``credential`` 关联记录（多凭证；W3 / T2-15）。

    对应 ORM 表 ``model_provider_credential``。

    Attributes:
        id: 关联记录唯一标识（UUIDv7）。
        provider_id: 模型提供方标识。
        credential_id: 凭证标识（指向 ``credential.id``）。
        weight: 加权轮询权重（``>0`` 才参与选取）。
        status: 关联状态（``ACTIVE`` / ``DISABLED``）。
        created_at: 创建时间（UTC）。
    """

    id: str = field(default_factory=generate_id)
    provider_id: str = ""
    credential_id: str = ""
    weight: int = 1
    status: str = "ACTIVE"
    created_at: datetime | None = None


@runtime_checkable
class CredentialRepository(Protocol):
    """凭证仓储接口（既有签名**一字不改**，F22 回归闸）。"""

    def add(self, record: CredentialRecord) -> CredentialRecord: ...

    def get(self, credential_id: str) -> CredentialRecord | None: ...

    def list_by_tenant(self, tenant_id: str) -> list[CredentialRecord]: ...

    def delete(self, credential_id: str) -> None: ...
