"""``IdempotencyService``——幂等记录读写（W6 / T1-29；设计 §2.13.1；裁定 Q4/A28）。

**零 Web / ORM**（应用层）：经领域 Protocol ``AgentRunRepository`` / ``TaskRepository``
读写；请求指纹存 ``task.payload["request_fingerprint"]``（**无新列**，复用既有
``task.payload`` JSON 列）。

判定口径（A28）：

- **列 / 索引**：复用 ``agent_run.idempotency_key`` +
  ``uq_agent_run_tenant_idempotency_key (tenant_id, idempotency_key)``（``0006`` 已建，
  **无需迁移**）；键作用域 = ``(tenant_id, idempotency_key)``。
- **命中且用户不一致** → ``409 CONFLICT (IDEMPOTENCY_KEY_REUSE)``（防跨用户串号）。
- **命中且用户一致、指纹一致** → 返回首次 Run（复用响应，不重复执行）。
- **命中但指纹不一致** → ``409 CONFLICT (IDEMPOTENCY_KEY_REUSE)``。
- **未命中** → 返回 ``None``（由调用方继续首次执行）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import AgentRun, AgentRunRepository, TaskRepository

from .base import ApplicationService

__all__ = ["IdempotencyService", "compute_request_fingerprint"]

#: 指纹存于 ``task.payload`` 的键名。
FINGERPRINT_PAYLOAD_KEY = "request_fingerprint"


def compute_request_fingerprint(
    *,
    agent_id: str,
    conversation_id: str,
    input: str,
    permission_scope: dict[str, Any] | None = None,
) -> str:
    """计算请求指纹 ``sha256(canonical_json(...))``（hex，64 字符）。

    canonical json =
    ``json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``。

    Args:
        agent_id: Agent 标识。
        conversation_id: 会话标识。
        input: 用户输入。
        permission_scope: 可选权限 scope（提供时纳入指纹）。

    Returns:
        64 字符 sha256 hex 指纹。
    """
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "conversation_id": conversation_id,
        "input": input,
    }
    if permission_scope:
        payload["permission_scope"] = dict(permission_scope)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyService(ApplicationService):
    """幂等记录读写服务（DI 注入领域 Protocol 仓储）。"""

    runs: AgentRunRepository
    tasks: TaskRepository

    def __init__(self, *, runs: AgentRunRepository, tasks: TaskRepository) -> None:
        super().__init__(runs=runs, tasks=tasks)

    def fingerprint(
        self,
        *,
        agent_id: str,
        conversation_id: str,
        input: str,
        permission_scope: dict[str, Any] | None = None,
    ) -> str:
        """便捷封装：计算请求指纹（见 :func:`compute_request_fingerprint`）。"""
        return compute_request_fingerprint(
            agent_id=agent_id,
            conversation_id=conversation_id,
            input=input,
            permission_scope=permission_scope,
        )

    def lookup(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        current_user_id: str | None,
        request_fingerprint: str,
    ) -> AgentRun | None:
        """按 ``(tenant_id, idempotency_key)`` 判定幂等命中。

        Returns:
            命中的首次 Run（复用）；未命中返回 ``None``。

        Raises:
            DomainError: 跨用户串号（``IDEMPOTENCY_KEY_REUSE`` → 409）；
                或同键不同体（``IDEMPOTENCY_KEY_REUSE`` → 409）。
        """
        if not idempotency_key:
            return None
        found = self.runs.get_by_idempotency_key(tenant_id, idempotency_key)
        if found is None:
            return None
        if found.user_id is not None and found.user_id != current_user_id:
            raise DomainError(
                "幂等键已被其他用户使用",
                code=ErrorCode.IDEMPOTENCY_KEY_REUSE,
                data={"idempotency_key": idempotency_key},
            )
        stored = self._stored_fingerprint(found)
        if stored is not None and stored != request_fingerprint:
            raise DomainError(
                "幂等键已用于不同请求体（同键不同体）",
                code=ErrorCode.IDEMPOTENCY_KEY_REUSE,
                data={"idempotency_key": idempotency_key},
            )
        return found

    def _stored_fingerprint(self, run: AgentRun) -> str | None:
        """读取该 Run 挂靠 ``task.payload["request_fingerprint"]``（无则 ``None``）。"""
        if run.task_id is None:
            return None
        task = self.tasks.get(run.task_id)
        if task is None:
            return None
        payload = getattr(task, "payload", None) or {}
        value = payload.get(FINGERPRINT_PAYLOAD_KEY)
        return str(value) if value is not None else None
