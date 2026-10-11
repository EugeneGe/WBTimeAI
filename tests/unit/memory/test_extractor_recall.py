"""``MemoryExtractor`` / ``MemoryRecall`` / ``MemoryManager`` 单元测试（W6 / T2-33）。

覆盖：

- **抽取**：LLM 候选解析（含 ```json 代码块）/ 规则过滤（长度 / 敏感 / 去重 / 非法类别）；
- **成本（NFR N4）**：单次抽取 token 用量 **≤ 上限**；
- **隔离**：非用户触发**不抽取 / 不召回 ``USER``**（B5 / B11）；``private`` 非本人作用域不可召回；
  **租户级兜底**保证非 ``private`` 记忆任何触发下均可召回（恒追加）；
- **权重**：``importance × recency`` 排序（时效半衰期）；
- **记忆管理器**：``remember`` / ``recall``（RP-03 面）+ ``forget`` 级联 + ``prune`` TTL。

🔴 纯逻辑单测：``ModelProvider`` / ``MemoryStore`` 均以最小 fake 注入（零 DB / 零真实 LLM）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from astra_common.time import utcnow
from astra_domain import MemoryQuery, MemoryRecord
from astra_memory import (
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_PROJECT,
    MEMORY_KIND_USER,
    SCOPE_TYPE_PROJECT,
    SCOPE_TYPE_USER,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_PRIVATE,
    VISIBILITY_WORKSPACE,
    Memory,
    MemoryDraft,
    MemoryExtractor,
    MemoryManager,
    MemoryRecall,
)
from astra_model import ChatMessage, ChatResult, TokenCount

from tests.fixtures.memory import DEFAULT_TENANT, DEFAULT_USER, make_memory

# -- 测试替身 ----------------------------------------------------------------


class _FakeProvider:
    """最小 ``ModelProvider``（``chat`` 回固定 JSON；``count_tokens`` 回固定值）。"""

    def __init__(self, *, content: str = "[]", count: int = 10, total_tokens: int = 5) -> None:
        self._content = content
        self._count = count
        self._total = total_tokens
        self.last_options: dict[str, Any] = {}

    def chat(self, messages: Any, **options: Any) -> ChatResult:
        self.last_options = options
        return ChatResult(content=self._content, usage={"total_tokens": self._total})

    def count_tokens(self, text: str, **options: Any) -> TokenCount:  # noqa: ARG002 - 协议签名
        return TokenCount(count=self._count)

    def stream(self, messages: Any, **options: Any) -> Any:  # pragma: no cover - 未使用
        yield self._content

    def embeddings(self, texts: Any, **options: Any) -> list[Any]:  # pragma: no cover - 未使用
        return []


class _FakeStore:
    """最小内存 ``MemoryStore``（复刻 SQL 仓储的隔离过滤语义）。"""

    def __init__(self) -> None:
        self._items: dict[str, Memory] = {}

    def upsert(self, memory: Memory) -> Memory:
        self._items[memory.id] = memory
        return memory

    def delete(self, memory_id: str, *, tenant_id: str) -> None:
        item = self._items.get(memory_id)
        if item is not None and item.tenant_id == tenant_id:
            del self._items[memory_id]

    def prune(self, *, now: datetime) -> int:
        expired = [
            mid
            for mid, item in self._items.items()
            if item.expires_at is not None and item.expires_at <= now
        ]
        for mid in expired:
            del self._items[mid]
        return len(expired)

    def search(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        visibility: list[str] | None = None,
        kinds: list[str] | None = None,
        text: str | None = None,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[Memory]:
        reference = now or utcnow()
        result: list[Memory] = []
        for item in self._items.values():
            if item.tenant_id != tenant_id:
                continue
            if scope_type is not None and item.scope_type != scope_type:
                continue
            if scope_id is not None and item.scope_id != scope_id:
                continue
            if visibility and item.visibility not in visibility:
                continue
            if kinds and item.kind not in kinds:
                continue
            if text and text.lower() not in (item.content or "").lower():
                continue
            if item.expires_at is not None and item.expires_at <= reference:
                continue
            result.append(item)
        return result[:limit] if limit and limit > 0 else result


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="我喜欢喝咖啡")]


# -- 抽取器 ------------------------------------------------------------------


def test_extractor_parses_and_filters_candidates() -> None:
    """解析 LLM JSON → 规则过滤（保留合法 / 剔短 / 剔敏感 / 去重 / 剔非法类别）。"""
    payload = json.dumps(
        [
            {
                "kind": "LONG_TERM",
                "memory_type": "fact",
                "content": "用户喜欢咖啡",
                "importance": 0.8,
                "confidence": 0.9,
            },
            {
                "kind": "USER",
                "memory_type": "preference",
                "content": "用户名叫张三",
                "importance": 0.5,
                "confidence": 0.5,
            },
            {"kind": "LONG_TERM", "content": "ab"},  # 长度不足
            {"kind": "LONG_TERM", "content": "邮箱 alice@example.com"},  # 敏感
            {"kind": "LONG_TERM", "content": "用户喜欢咖啡"},  # 去重
            {"kind": "NOT_A_KIND", "content": "非法类别内容"},  # 非法 kind
        ]
    )
    extractor = MemoryExtractor(model_provider=_FakeProvider(content=payload))
    drafts = extractor.extract(messages=_messages(), trigger="user")
    assert [draft.content for draft in drafts] == ["用户喜欢咖啡", "用户名叫张三"]
    assert drafts[0].kind == MEMORY_KIND_LONG_TERM
    assert drafts[0].importance == 0.8


def test_extractor_parses_fenced_json_block() -> None:
    """```json 代码块容错解析。"""
    content = '```json\n[{"kind": "LONG_TERM", "content": "偏好简洁回复"}]\n```'
    extractor = MemoryExtractor(model_provider=_FakeProvider(content=content))
    drafts = extractor.extract(messages=_messages(), trigger="user")
    assert [draft.content for draft in drafts] == ["偏好简洁回复"]


def test_extractor_non_user_trigger_drops_user_kind() -> None:
    """🔴 非用户触发**剔除 ``USER``**（B11，对称 R-19）。"""
    candidates = [
        MemoryDraft(kind=MEMORY_KIND_USER, content="用户名叫张三"),
        MemoryDraft(kind=MEMORY_KIND_LONG_TERM, content="用户喜欢咖啡"),
    ]
    extractor = MemoryExtractor(model_provider=_FakeProvider())
    kept = extractor.filter(candidates, trigger="schedule")
    assert [draft.kind for draft in kept] == [MEMORY_KIND_LONG_TERM]
    # 用户触发时保留。
    assert len(extractor.filter(candidates, trigger="user")) == 2


def test_extractor_without_provider_returns_empty() -> None:
    """未注入 Provider → 不抽取（返回空，非异常）。"""
    assert MemoryExtractor(model_provider=None).extract(messages=_messages(), trigger="user") == []


def test_extractor_token_usage_within_budget() -> None:
    """🔴 单次抽取 token 用量 **≤ 上限**（NFR N4 / §5 #10）。"""
    provider = _FakeProvider(content="[]", count=10, total_tokens=1_000_000)
    extractor = MemoryExtractor(model_provider=provider, token_limit=2000)
    extractor.extract(messages=_messages(), trigger="user", token_budget=100)
    assert extractor.last_token_usage <= 100
    assert extractor.token_limit == 2000


# -- 召回器 ------------------------------------------------------------------


def test_recall_orders_by_importance() -> None:
    """召回按 ``importance`` 降序（同等时效）。"""
    store = _FakeStore()
    store.upsert(
        make_memory(
            content="高重要度",
            importance=0.9,
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    store.upsert(
        make_memory(
            content="低重要度",
            importance=0.1,
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    recall = MemoryRecall(store=store)
    records = recall.recall(
        MemoryQuery(text="重要度", tenant_id=DEFAULT_TENANT, workspace_id="ws1")
    )
    assert [record.content for record in records] == ["高重要度", "低重要度"]


def test_recall_applies_recency_decay() -> None:
    """时效半衰期：旧记忆权重衰减（同重要度下新记忆优先）。"""
    now = utcnow()
    store = _FakeStore()
    store.upsert(
        make_memory(
            content="旧记忆",
            importance=0.5,
            created_at=now - timedelta(days=60),
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    store.upsert(
        make_memory(
            content="新记忆",
            importance=0.5,
            created_at=now,
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    recall = MemoryRecall(store=store, recency_half_life_days=30.0)
    records = recall.recall(
        MemoryQuery(text="记忆", tenant_id=DEFAULT_TENANT, workspace_id="ws1"), now=now
    )
    assert [record.content for record in records] == ["新记忆", "旧记忆"]


def test_recall_non_user_trigger_excludes_user_memory() -> None:
    """🔴 非用户触发**不召回 ``USER``**（B5）。"""
    store = _FakeStore()
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


def test_recall_private_requires_own_scope() -> None:
    """🔴 ``private`` 记忆在**非本人作用域**下不可召回（R-19）。"""
    store = _FakeStore()
    store.upsert(
        make_memory(
            kind=MEMORY_KIND_USER,
            scope_type=SCOPE_TYPE_USER,
            scope_id=DEFAULT_USER,
            visibility=VISIBILITY_PRIVATE,
            content="用户私有事实",
        )
    )
    recall = MemoryRecall(store=store)
    # 用户触发但查询未提供 user_id → 无本人作用域 → 不含 private。
    anonymous = recall.recall(
        MemoryQuery(tenant_id=DEFAULT_TENANT, workspace_id="ws1", trigger="user")
    )
    assert [record.content for record in anonymous] == []
    # 用户触发且提供 user_id → 含本人 private。
    owned = recall.recall(
        MemoryQuery(
            tenant_id=DEFAULT_TENANT,
            workspace_id="ws1",
            user_id=DEFAULT_USER,
            trigger="user",
        )
    )
    assert [record.content for record in owned] == ["用户私有事实"]


def test_recall_tenant_fallback_reaches_non_private_scope() -> None:
    """租户级兜底（恒追加）：非 ``private`` 的 ``PROJECT`` 记忆无需精确作用域即可召回。"""
    store = _FakeStore()
    store.upsert(
        make_memory(
            kind=MEMORY_KIND_PROJECT,
            scope_type=SCOPE_TYPE_PROJECT,
            scope_id="p1",
            visibility=VISIBILITY_WORKSPACE,
            content="项目约定",
        )
    )
    recall = MemoryRecall(store=store)
    records = recall.recall(MemoryQuery(tenant_id=DEFAULT_TENANT))
    assert [record.content for record in records] == ["项目约定"]


def test_recall_empty_tenant_returns_empty() -> None:
    """缺 ``tenant_id`` → 恒空（隔离不变量强制）。"""
    store = _FakeStore()
    store.upsert(make_memory(content="任意", visibility=VISIBILITY_WORKSPACE))
    assert MemoryRecall(store=store).recall(MemoryQuery(tenant_id="")) == []


def test_recall_cross_tenant_isolation() -> None:
    """跨租户不可召回。"""
    store = _FakeStore()
    store.upsert(make_memory(tenant_id="t1", content="t1 记忆", visibility=VISIBILITY_WORKSPACE))
    assert MemoryRecall(store=store).recall(MemoryQuery(tenant_id="t2")) == []


# -- 记忆管理器（RP-03 面 + Rich 面） -----------------------------------------


def test_manager_remember_then_recall() -> None:
    """``remember`` 落库 → ``recall`` 命中（RP-03 面）。"""
    store = _FakeStore()
    manager = MemoryManager(store=store)
    manager.remember(
        MemoryRecord(
            key="m1",
            content="记住我",
            tenant_id=DEFAULT_TENANT,
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    records = manager.recall(MemoryQuery(text="记住", tenant_id=DEFAULT_TENANT, workspace_id="ws1"))
    assert [record.content for record in records] == ["记住我"]


def test_manager_extract_persists_candidates() -> None:
    """``extract`` 抽取 → 落库（返回 ``Memory`` 列表）。"""
    payload = json.dumps(
        [
            {
                "kind": "LONG_TERM",
                "memory_type": "fact",
                "content": "用户喜欢咖啡",
                "importance": 0.7,
                "confidence": 0.8,
            }
        ]
    )
    store = _FakeStore()
    manager = MemoryManager(
        store=store, extractor=MemoryExtractor(model_provider=_FakeProvider(content=payload))
    )
    run = SimpleNamespace(
        id="run1",
        tenant_id=DEFAULT_TENANT,
        user_id=DEFAULT_USER,
        agent_id="a1",
        conversation_id="c1",
        workspace_id="ws1",
        trigger="user",
    )
    saved = manager.extract(run=run, messages=_messages())
    assert len(saved) == 1
    assert saved[0].content == "用户喜欢咖啡"
    assert saved[0].tenant_id == DEFAULT_TENANT
    assert saved[0].scope_type == SCOPE_TYPE_WORKSPACE


def test_manager_extract_respects_disabled_switch() -> None:
    """抽取开关关闭 → 不抽取（返回空）。"""
    payload = json.dumps([{"kind": "LONG_TERM", "content": "用户喜欢咖啡"}])
    store = _FakeStore()
    manager = MemoryManager(
        store=store,
        extractor=MemoryExtractor(model_provider=_FakeProvider(content=payload)),
        settings=SimpleNamespace(extraction_enabled=False),
    )
    run = SimpleNamespace(id="run1", tenant_id=DEFAULT_TENANT, trigger="user")
    assert manager.extract(run=run, messages=_messages()) == []


def test_manager_extract_token_budget_is_capped() -> None:
    """``extract`` 全程 token 用量受 ``extraction_token_limit`` 约束（NFR N4）。"""
    store = _FakeStore()
    extractor = MemoryExtractor(
        model_provider=_FakeProvider(content="[]", count=10, total_tokens=1_000_000)
    )
    manager = MemoryManager(
        store=store, extractor=extractor, settings=SimpleNamespace(extraction_token_limit=50)
    )
    run = SimpleNamespace(id="run1", tenant_id=DEFAULT_TENANT, trigger="user")
    manager.extract(run=run, messages=_messages())
    assert manager.last_token_usage <= 50


def test_manager_forget_cascades_relations() -> None:
    """``forget`` 显式级联删关系（§13-e）。"""
    deleted: list[str] = []

    class _RelRepo:
        def delete_by_memory(self, memory_id: str) -> int:
            deleted.append(memory_id)
            return 1

    store = _FakeStore()
    manager = MemoryManager(store=store, relation_repository=_RelRepo())
    manager.remember(
        MemoryRecord(
            key="m1", content="待删", tenant_id=DEFAULT_TENANT, visibility=VISIBILITY_WORKSPACE
        )
    )
    manager.forget("m1", tenant_id=DEFAULT_TENANT)
    assert deleted == ["m1"]
    assert manager.recall(MemoryQuery(tenant_id=DEFAULT_TENANT)) == []


def test_manager_prune_removes_expired() -> None:
    """``prune`` 清理到期记忆（TTL 遗忘）。"""
    store = _FakeStore()
    store.upsert(
        make_memory(
            content="已过期",
            expires_at=utcnow() - timedelta(hours=1),
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    store.upsert(
        make_memory(
            content="未过期",
            kind=MEMORY_KIND_LONG_TERM,
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
        )
    )
    manager = MemoryManager(store=store)
    assert manager.prune() == 1
    assert [record.content for record in manager.recall(MemoryQuery(tenant_id=DEFAULT_TENANT))] == [
        "未过期"
    ]
