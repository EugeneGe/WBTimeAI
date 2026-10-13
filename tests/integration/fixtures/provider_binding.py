"""M1 执行期绑定测试夹具（内存 / 离线，**不联网 / 不碰 PG**）。

供 ``tests/integration/test_model_provider_binding.py`` 复用：

- :class:`FakeModelProviderRepository`：内存租户 Provider 仓储（可注入多行验匹配 / 跨租户），
  并记录 ``list_by_tenant`` / ``get`` 调用（供断言「stub 旁路不查行」等）；
- :class:`FakeCredentialDecoder`：固定明文解密器（便于断言「明文不回显」）；
- :class:`RecordingHandler` / :func:`build_recording_client`：基于 ``httpx.MockTransport``
  的**录制回放**客户端（复用 ``tests/contracts/support.py`` 的 cassette handler 思路），
  记录出站请求（供断言 ``Authorization: Bearer <secret>``）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
from astra_domain import MODEL_PROVIDER_STATUS_ACTIVE, ModelProvider

#: 固定伪密钥（测试用）；断言「不回显」时以它为哨兵串。
FAKE_SECRET = "sk-m1-fake-secret-do-not-echo-0123456789"


class FakeModelProviderRepository:
    """内存 ``ModelProviderRepository``（实现 ``Repository`` + ``list_by_tenant``）。"""

    def __init__(self, *, rows: list[ModelProvider] | None = None) -> None:
        self._rows: dict[str, ModelProvider] = {}
        for row in rows or ():
            self._rows[row.id] = row
        #: ``list_by_tenant`` 调用记录（租户 id）。
        self.list_by_tenant_calls: list[str] = []
        #: ``get`` 调用记录（实体 id）。
        self.get_calls: list[str] = []

    def get(self, entity_id: str) -> ModelProvider | None:
        """按主键获取（记录调用）。"""
        self.get_calls.append(entity_id)
        return self._rows.get(entity_id)

    def add(self, entity: ModelProvider) -> ModelProvider:
        """新增（内存）。"""
        self._rows[entity.id] = entity
        return entity

    def list(self, **filters: Any) -> list[ModelProvider]:
        """按等值条件列出（内存）。"""
        return [
            row
            for row in self._rows.values()
            if all(getattr(row, key, None) == value for key, value in filters.items())
        ]

    def update(self, entity: ModelProvider) -> ModelProvider:
        """更新（内存）。"""
        self._rows[entity.id] = entity
        return entity

    def delete(self, entity: ModelProvider) -> None:
        """删除（内存）。"""
        self._rows.pop(entity.id, None)

    def list_by_tenant(self, tenant_id: str) -> list[ModelProvider]:
        """列出某租户下的全部 Provider（记录调用）。"""
        self.list_by_tenant_calls.append(tenant_id)
        return [row for row in self._rows.values() if row.tenant_id == tenant_id]


class FakeCredentialDecoder:
    """固定明文解密器（``decrypt(credential_id) -> FAKE_SECRET``）。"""

    def __init__(self, *, secret: str = FAKE_SECRET) -> None:
        self._secret = secret
        #: ``decrypt`` 调用记录（credential_id）。
        self.decrypt_calls: list[str] = []

    def decrypt(self, credential_id: str) -> str:
        """返回固定明文（记录调用）。"""
        self.decrypt_calls.append(credential_id)
        return self._secret


class RecordingHandler:
    """``httpx.MockTransport`` handler：记录请求并回放固定 chat 响应（不联网）。"""

    def __init__(self, *, content: str = "Hello!") -> None:
        self.requests: list[httpx.Request] = []
        self._payload = json.dumps(
            {
                "model": "mock-model",
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, text=self._payload, headers={"content-type": "application/json"})


def build_recording_client(handler: RecordingHandler) -> httpx.Client:
    """构造带录制回放 transport 的 ``httpx.Client``（离线）。"""
    return httpx.Client(transport=httpx.MockTransport(handler))


def make_row(
    *,
    tenant_id: str,
    provider_type: str,
    endpoint: str | None = None,
    credential_id: str | None = None,
    status: str = MODEL_PROVIDER_STATUS_ACTIVE,
    name: str = "",
    created_at: datetime | None = None,
) -> ModelProvider:
    """构造一条租户 ``ModelProvider`` 行（内存，不落库）。"""
    row = ModelProvider(
        tenant_id=tenant_id,
        name=name or provider_type,
        type=provider_type,
        endpoint=endpoint,
        credential_id=credential_id,
        status=status,
    )
    if created_at is not None:
        row.created_at = created_at
    return row
