"""``Idempotency-Key`` 依赖（W6 / T1-29；设计 §2.13.1；裁定 Q4/A28）。

职责：解析 ``Idempotency-Key`` 请求头 → 计算请求指纹（sha256 hex）→ 经
``IdempotencyService`` 判定命中（复用首次响应 / 冲突）。

- 键作用域 ``(tenant_id, idempotency_key)``（复用 ``0006`` 已建唯一索引，**无需迁移**）；
- 「同键同体」经 ``task.payload["request_fingerprint"]`` 比对（无新列）；
- **命中且用户不一致 / 指纹不一致** → ``DomainError(IDEMPOTENCY_KEY_REUSE)`` → 409；
- 只读接口（``Last-Event-ID`` 续传）**不走**幂等键。

Router 只依赖 ``AppServices``（C-06 / N-8）；本模块**零 ORM**。
"""

from __future__ import annotations

from typing import Annotated, Any

from astra_application import compute_request_fingerprint
from astra_application.dto import RunDTO
from fastapi import Depends, Header

from .services import AppServices

__all__ = [
    "get_idempotency_key",
    "IdempotencyKey",
    "prepare_idempotency",
]


def get_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """解析 ``Idempotency-Key`` 请求头（缺省 / 空白 → ``None``）。"""
    if idempotency_key is None:
        return None
    value = idempotency_key.strip()
    return value or None


#: ``Idempotency-Key`` 请求头依赖类型别名。
IdempotencyKey = Annotated[str | None, Depends(get_idempotency_key)]


def prepare_idempotency(
    *,
    services: AppServices,
    idempotency_key: str | None,
    tenant_id: str,
    user_id: str | None,
    agent_id: str,
    conversation_id: str,
    input: str,
    permission_scope: dict[str, Any] | None = None,
) -> tuple[str | None, str, RunDTO | None]:
    """解析幂等键 → 计算请求指纹 → 命中则返回首次 Run（复用）。

    Args:
        services: 应用服务集合（经 ``services.idempotency`` 判定）。
        idempotency_key: ``Idempotency-Key`` 头值（``None`` = 不启用幂等）。
        tenant_id: 当前租户标识（键作用域之一）。
        user_id: 当前用户标识（命中时校验一致性，防跨用户串号）。
        agent_id: Agent 标识（纳入指纹）。
        conversation_id: 会话标识（纳入指纹）。
        input: 用户输入（纳入指纹）。
        permission_scope: 可选权限 scope（提供时纳入指纹）。

    Returns:
        ``(idempotency_key, request_fingerprint, reuse_dto)``：

        - ``reuse_dto`` 非空 → 直接复用首次响应（**不重复执行**）；
        - ``reuse_dto`` 为空 → 首次执行（把 ``idempotency_key`` / ``request_fingerprint``
          透传 ``CreateAgentTaskCommand``）。

    Raises:
        DomainError: 跨用户串号或同键不同体（``IDEMPOTENCY_KEY_REUSE`` → 409）。
    """
    fingerprint = compute_request_fingerprint(
        agent_id=agent_id,
        conversation_id=conversation_id,
        input=input,
        permission_scope=permission_scope,
    )
    if not idempotency_key:
        return None, fingerprint, None
    found = services.idempotency.lookup(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        current_user_id=user_id,
        request_fingerprint=fingerprint,
    )
    reuse = None if found is None else RunDTO.from_entity(found)
    return idempotency_key, fingerprint, reuse
