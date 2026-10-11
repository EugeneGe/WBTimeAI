"""记忆隔离 / TTL / 跨租户 / 抽取落库集成测试（W6 / T2-33 / T2-34）。

覆盖（W6 开工前架构裁定 §3.3 / §5 / B5 / B11 / I-2 / I-3）：

- **跨租户隔离**：``search`` 强制 ``tenant_id``；``delete`` 跨租户不可删；
- **``USER`` 隐私**：非用户触发（``schedule``）**不召回 ``USER``**；用户触发仅本人可见；
- **TTL**：已到期记忆不召回，``prune`` 清理并**显式级联删关系**；
- **抽取落库**：组合根订阅驱动的 ``MemoryManager.extract`` 经真实 SQLite 落库。

🔴 真实 SQLite（``session_factory`` 夹具预建全量 schema）；PG 路受环境门控。
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from astra_common.time import utcnow
from astra_domain import MemoryQuery
from astra_memory import (
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_USER,
    SCOPE_TYPE_USER,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_PRIVATE,
    VISIBILITY_WORKSPACE,
    MemoryExtractor,
    MemoryManager,
    MemoryRecall,
    SqlMemoryStore,
    build_memory_repositories,
)
from astra_model import ChatMessage, ChatResult, TokenCount

from tests.fixtures.memory import DEFAULT_TENANT, DEFAULT_USER, make_memory, make_relation


class _FakeProvider:
    """最小 ``ModelProvider``（回固定 JSON）。"""

    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, messages: Any, **options: Any) -> ChatResult:  # noqa: ARG002 - 协议签名
        return ChatResult(content=self._content, usage={"total_tokens": 8})

    def count_tokens(self, text: str, **options: Any) -> TokenCount:  # noqa: ARG002 - 协议签名
        return TokenCount(count=5)

    def stream(self, messages: Any, **options: Any) -> Any:  # pragma: no cover - 未使用
        yield self._content

    def embeddings(self, texts: Any, **options: Any) -> list[Any]:  # pragma: no cover - 未使用
        return []


def _store(session_factory: object) -> SqlMemoryStore:
    return SqlMemoryStore(repository=build_memory_repositories(session_factory).memories)


def test_cross_tenant_search_and_delete_isolation(session_factory: object) -> None:
    """跨租户：不可召回、不可删除（I-2 / I-3）。"""
    repositories = build_memory_repositories(session_factory)
    store = SqlMemoryStore(repository=repositories.memories)
    memory = store.upsert(
        make_memory(
            tenant_id="tenant-a",
            content="租户 A 的记忆",
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    assert store.search(tenant_id="tenant-b") == []
    assert [item.content for item in store.search(tenant_id="tenant-a")] == ["租户 A 的记忆"]

    store.delete(memory.id, tenant_id="tenant-b")
    assert repositories.memories.get(memory.id) is not None
    store.delete(memory.id, tenant_id="tenant-a")
    assert repositories.memories.get(memory.id) is None


def test_non_user_trigger_does_not_recall_user_memory(session_factory: object) -> None:
    """🔴 非用户触发**不召回 ``USER``**；用户触发仅本人可见（B5 / R-19）。"""
    store = _store(session_factory)
    store.upsert(
        make_memory(
            kind=MEMORY_KIND_USER,
            scope_type=SCOPE_TYPE_USER,
            scope_id=DEFAULT_USER,
            visibility=VISIBILITY_PRIVATE,
            content="用户私有事实",
        )
    )
    store.upsert(
        make_memory(
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
            content="团队共享事实",
        )
    )
    recall = MemoryRecall(store=store)

    scheduled = recall.recall(
        MemoryQuery(
            tenant_id=DEFAULT_TENANT,
            workspace_id="ws1",
            agent_id="a1",
            user_id=DEFAULT_USER,
            trigger="schedule",
        )
    )
    assert [record.content for record in scheduled] == ["团队共享事实"]

    user_triggered = recall.recall(
        MemoryQuery(
            tenant_id=DEFAULT_TENANT,
            workspace_id="ws1",
            agent_id="a1",
            user_id=DEFAULT_USER,
            trigger="user",
        )
    )
    contents = {record.content for record in user_triggered}
    assert contents == {"用户私有事实", "团队共享事实"}


def test_ttl_prune_cascades_relations(session_factory: object) -> None:
    """TTL：过期记忆不召回；``prune`` 清理并级联删关系（§13-e）。"""
    repositories = build_memory_repositories(session_factory)
    store = SqlMemoryStore(repository=repositories.memories)
    live = store.upsert(make_memory(content="未过期"))
    expired = store.upsert(make_memory(content="已过期", expires_at=utcnow() - timedelta(hours=1)))
    repositories.relations.add(
        make_relation(from_memory_id=live.id, to_memory_id=expired.id, relation="related")
    )

    assert [item.content for item in store.search(tenant_id=DEFAULT_TENANT)] == ["未过期"]

    manager = MemoryManager(store=store, relation_repository=repositories.relations)
    assert manager.prune() == 1
    assert repositories.memories.get(expired.id) is None
    assert repositories.memories.get(live.id) is not None
    assert repositories.relations.list_by_from(live.id) == []


def test_manager_extract_persists_to_sqlite(session_factory: object) -> None:
    """``MemoryManager.extract`` 经真实 SQLite 落库（抽取 → upsert → 可召回）。"""
    payload = json.dumps(
        [
            {
                "kind": "LONG_TERM",
                "memory_type": "fact",
                "content": "用户偏好深色主题",
                "importance": 0.6,
                "confidence": 0.7,
            }
        ]
    )
    repositories = build_memory_repositories(session_factory)
    store = SqlMemoryStore(repository=repositories.memories)
    manager = MemoryManager(
        store=store,
        extractor=MemoryExtractor(model_provider=_FakeProvider(payload)),
        relation_repository=repositories.relations,
    )
    run = SimpleNamespace(
        id="run-1",
        tenant_id=DEFAULT_TENANT,
        user_id=DEFAULT_USER,
        agent_id="a1",
        conversation_id="c1",
        workspace_id="ws1",
        trigger="user",
    )
    saved = manager.extract(
        run=run, messages=[ChatMessage(role="user", content="我总是用深色主题")]
    )
    assert len(saved) == 1
    assert saved[0].content == "用户偏好深色主题"

    recalled = manager.recall(
        MemoryQuery(text="深色", tenant_id=DEFAULT_TENANT, workspace_id="ws1")
    )
    assert [record.content for record in recalled] == ["用户偏好深色主题"]
