"""QA-W6 独立探针（严过关 · 尝试证伪隔离 / TTL / 抽取成本断言）。

本文件由 **QA（严过关）** 独立编写，**不采信工程师自报**，对 W6 关键不变量做**负向验证**
（尝试构造「非用户触发仍召回/抽取 USER」、「跨租户可见」、「USER 跨人可见」的路径）：

- P1 非用户触发**绝不召回** ``USER``（即便该 ``USER`` 记忆被误写为 ``workspace`` 可见）；
- P2 非用户触发**绝不抽取/落库** ``USER``（B11 / ``P2-75``）；
- P3 **跨租户**召回恒不可见（I-2 / I-3）；
- P4 ``USER`` 私有记忆**仅本人可见**（他人触发不可见）；
- P5 ``SHORT_TERM`` **TTL fake clock** 到期清理（``I-P2-09``）；
- P6 抽取**单次 token 上限**与**可关闭开关**（§5 #10 / NFR N4）。

🔴 真实 SQLite（``session_factory`` 预建全量 schema）；PG 路受环境门控（本机无 PG）。
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from astra_common.time import utcnow
from astra_domain import MemoryQuery
from astra_memory import (
    MEMORY_KIND_SHORT_TERM,
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

from tests.fixtures.memory import DEFAULT_TENANT, DEFAULT_USER, make_memory


class _FakeProvider:
    """最小 ``ModelProvider``（回固定 JSON；可配 token 用量；可作 spy）。"""

    def __init__(
        self,
        content: str,
        *,
        total_tokens: int = 8,
        count: int = 5,
        echo_real_usage: bool = False,
    ) -> None:
        self._content = content
        self._total_tokens = total_tokens
        self._count = count
        self._echo_real_usage = echo_real_usage
        #: 最近一次 ``chat`` 的 ``max_tokens`` 实参（成本上限 spy）。
        self.last_max_tokens: int | None = None

    def chat(self, messages: Any, **options: Any) -> ChatResult:  # noqa: ARG002 - 协议签名
        max_tokens = options.get("max_tokens")
        self.last_max_tokens = int(max_tokens) if max_tokens is not None else None
        # 行为良好的 Provider：输出 token 不超 ``max_tokens``（真实世界语义）。
        usage = self._total_tokens
        if self._echo_real_usage and max_tokens is not None:
            usage = min(self._total_tokens, int(max_tokens))
        return ChatResult(content=self._content, usage={"total_tokens": usage})

    def count_tokens(self, text: str, **options: Any) -> TokenCount:  # noqa: ARG002 - 协议签名
        return TokenCount(count=self._count)

    def stream(self, messages: Any, **options: Any) -> Any:  # pragma: no cover - 未使用
        yield self._content

    def embeddings(self, texts: Any, **options: Any) -> list[Any]:  # pragma: no cover - 未使用
        return []


def _store(session_factory: object) -> SqlMemoryStore:
    return SqlMemoryStore(repository=build_memory_repositories(session_factory).memories)


def test_probe_non_user_trigger_never_recalls_user_even_workspace_visible(
    session_factory: object,
) -> None:
    """P1：即便 ``USER`` 记忆被误写为 ``workspace`` 可见，非用户触发**绝不召回**。"""
    store = _store(session_factory)
    # 故意构造「越权可见」的 USER 记忆（workspace 可见）——证伪尝试。
    store.upsert(
        make_memory(
            kind=MEMORY_KIND_USER,
            scope_type=SCOPE_TYPE_USER,
            scope_id=DEFAULT_USER,
            visibility=VISIBILITY_WORKSPACE,
            content="越权可见的用户私有事实",
        )
    )
    recall = MemoryRecall(store=store)
    for trigger in ("schedule", "event", "webhook"):
        records = recall.recall(
            MemoryQuery(
                tenant_id=DEFAULT_TENANT,
                workspace_id="ws1",
                agent_id="a1",
                user_id=DEFAULT_USER,
                trigger=trigger,
            )
        )
        assert records == [], f"非用户触发 {trigger} 竟召回了 USER：{records}"


def test_probe_user_memory_only_owner_visible(session_factory: object) -> None:
    """P4：``USER`` 私有记忆**仅本人可见**（他人触发不可见）。"""
    store = _store(session_factory)
    store.upsert(
        make_memory(
            kind=MEMORY_KIND_USER,
            scope_type=SCOPE_TYPE_USER,
            scope_id="owner-a",
            visibility=VISIBILITY_PRIVATE,
            content="owner-a 私有事实",
        )
    )
    recall = MemoryRecall(store=store)
    other = recall.recall(
        MemoryQuery(tenant_id=DEFAULT_TENANT, user_id="intruder-b", trigger="user")
    )
    assert other == [], f"他人触发了 owner-a 的 USER 私有记忆：{other}"
    owner = recall.recall(MemoryQuery(tenant_id=DEFAULT_TENANT, user_id="owner-a", trigger="user"))
    assert [r.content for r in owner] == ["owner-a 私有事实"]


def test_probe_cross_tenant_recall_invisible(session_factory: object) -> None:
    """P3：跨租户召回恒不可见（store 与 recall 双层）。"""
    store = _store(session_factory)
    store.upsert(
        make_memory(
            tenant_id="tenant-a",
            kind="LONG_TERM",
            scope_type=SCOPE_TYPE_WORKSPACE,
            scope_id="ws1",
            visibility=VISIBILITY_WORKSPACE,
            content="A 租户共享事实",
        )
    )
    assert store.search(tenant_id="tenant-b") == []
    recall = MemoryRecall(store=store)
    leaked = recall.recall(MemoryQuery(tenant_id="tenant-b", workspace_id="ws1", trigger="user"))
    assert leaked == [], f"跨租户召回泄漏：{leaked}"


def test_probe_non_user_trigger_extract_skips_user(session_factory: object) -> None:
    """P2：非用户触发**不抽取/落库** ``USER``（B11 / ``P2-75``）。"""
    payload = json.dumps(
        [
            {"kind": "USER", "content": "用户私有偏好", "memory_type": "preference"},
            {"kind": "LONG_TERM", "content": "项目共享结论", "memory_type": "fact"},
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
        id="run-sched",
        tenant_id=DEFAULT_TENANT,
        user_id=None,  # 非用户触发无 user
        agent_id="a1",
        conversation_id="c1",
        workspace_id="ws1",
        trigger="schedule",
    )
    saved = manager.extract(run=run, messages=[ChatMessage(role="user", content="随便说点什么")])
    kinds = sorted(m.kind for m in saved)
    assert "USER" not in kinds, f"非用户触发竟落库 USER：{kinds}"
    assert kinds == ["LONG_TERM"]

    # 直接验证抽取器规则过滤层同样剔除 USER。
    drafts = context_filter_check(payload)
    assert all(d.kind != MEMORY_KIND_USER for d in drafts)


def context_filter_check(payload: str) -> list[Any]:
    """直接调用 ``MemoryExtractor.filter`` 验证非用户触发剔除 ``USER``（规则层）。"""
    extractor = MemoryExtractor(model_provider=_FakeProvider(payload))
    from astra_memory import MemoryDraft

    candidates = [
        MemoryDraft(kind="USER", content="用户私有偏好", memory_type="preference"),
        MemoryDraft(kind="LONG_TERM", content="项目共享结论", memory_type="fact"),
    ]
    return extractor.filter(candidates, trigger="event")


def test_probe_short_term_ttl_fake_clock_prune(session_factory: object) -> None:
    """P5：``SHORT_TERM`` TTL fake clock 到期清理（``I-P2-09``）。"""
    repositories = build_memory_repositories(session_factory)
    store = SqlMemoryStore(repository=repositories.memories)
    base = utcnow()
    store.upsert(
        make_memory(
            kind=MEMORY_KIND_SHORT_TERM,
            scope_type="conversation",
            scope_id="c1",
            visibility=VISIBILITY_WORKSPACE,
            content="会话短期记忆",
            expires_at=base + timedelta(seconds=60),
        )
    )
    manager = MemoryManager(store=store, relation_repository=repositories.relations)
    # fake clock：未到期 → 不清
    assert manager.prune(now=base) == 0
    assert store.search(tenant_id=DEFAULT_TENANT, now=base) != []
    # fake clock：快进 61s → 清理 1 条
    assert manager.prune(now=base + timedelta(seconds=61)) == 1
    assert store.search(tenant_id=DEFAULT_TENANT, now=base + timedelta(seconds=61)) == []


def test_probe_extraction_request_is_bounded(session_factory: object) -> None:
    """P6：抽取**成本受真正约束**——下发给 Provider 的 ``max_tokens`` ≤ 上限（§5 #10 / NFR N4）。

    说明（QA 观察）：``MemoryExtractor.last_token_usage`` 以 ``min(limit, used)`` 夹紧，
    故 ``MemoryManager`` 内 ``last_token_usage > budget`` 的丢弃分支**不可达**（死代码）。
    但 NFR N4 的真实语义是「真实用量 ≤ 上限」——由 (i) 输入截断 + (ii) ``max_tokens`` 限定
    共同保证。本探针以 **spy Provider** 断言下发的 ``max_tokens`` 确实受限，从而证明
    成本上限**真的生效**（而非仅靠夹紧的报告值自证）。
    """
    payload = json.dumps(
        [{"kind": "LONG_TERM", "content": "一条很长的事实内容", "importance": 0.5}]
    )
    repositories = build_memory_repositories(session_factory)
    store = SqlMemoryStore(repository=repositories.memories)
    provider = _FakeProvider(payload, total_tokens=1_000_000, echo_real_usage=True)
    limit = 40
    manager = MemoryManager(
        store=store,
        extractor=MemoryExtractor(model_provider=provider, token_limit=2000),
        relation_repository=repositories.relations,
        settings=SimpleNamespace(extraction_token_limit=limit, extraction_enabled=True),
    )
    run = SimpleNamespace(
        id="run-limit",
        tenant_id=DEFAULT_TENANT,
        user_id=DEFAULT_USER,
        agent_id="a1",
        conversation_id="c1",
        workspace_id="ws1",
        trigger="user",
    )
    manager.extract(run=run, messages=[ChatMessage(role="user", content="内容")])
    # 真实机制：下发给 Provider 的 max_tokens ≤ 上限（成本受限）。
    assert provider.last_max_tokens is not None, "未向 Provider 下发 max_tokens"
    assert (
        provider.last_max_tokens <= limit
    ), f"max_tokens={provider.last_max_tokens} > 上限 {limit}"
    # 报告用量 ≤ 上限（NFR N4 的「差值 ≤ 上限」断言）。
    assert manager.last_token_usage <= limit


def test_probe_extraction_can_be_disabled(session_factory: object) -> None:
    """P6b：抽取**可关闭开关**（``extraction_enabled=False``）。"""
    payload = json.dumps([{"kind": "LONG_TERM", "content": "应被关闭开关拦截", "importance": 0.5}])
    repositories = build_memory_repositories(session_factory)
    store = SqlMemoryStore(repository=repositories.memories)
    manager = MemoryManager(
        store=store,
        extractor=MemoryExtractor(model_provider=_FakeProvider(payload)),
        relation_repository=repositories.relations,
        settings=SimpleNamespace(extraction_enabled=False, extraction_token_limit=2000),
    )
    run = SimpleNamespace(
        id="run-off",
        tenant_id=DEFAULT_TENANT,
        user_id=DEFAULT_USER,
        agent_id="a1",
        conversation_id="c1",
        workspace_id="ws1",
        trigger="user",
    )
    assert manager.extract(run=run, messages=[ChatMessage(role="user", content="内容")]) == []
