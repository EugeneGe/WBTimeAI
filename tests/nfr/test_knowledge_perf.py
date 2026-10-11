"""NFR：Knowledge ``search()`` p95 基线 + 记忆抽取 token 上限（F-2b；W6 遗留观察项）。

覆盖：

1. **``N-P2-01`` · ``search()`` p95（SQLite FTS5 关键字路）**——造 ~1000 条分块（含 FTS 索引），
   对 :meth:`~astra_knowledge.retriever.KnowledgeRetriever.search` 跑 ``N=20`` 次，取 p95；
   PG 真路经 :func:`~tests.nfr._support.resolve_pg_url` 门控（本机无 PG → skip；缺口 C2-28）。
2. **``N-P2-04`` · 记忆抽取 token 上限**——:class:`~astra_memory.extractor.MemoryExtractor` 抽取后
   断言 ``last_token_usage <= extraction_token_limit``；用 spy Provider 断言下发
   ``max_tokens == limit - input_tokens``（输入截断）；``extraction_enabled=False`` 时**不抽取**。

**门控语义**（对齐 :mod:`tests.nfr.test_perf_baseline`）：``ASTRA_TEST_REQUIRE_NFR=1``（nightly）
时**严格执行**基线断言——**超基线即红**；未置时（本地 / 自验）仅**测量 + 报告**。

**基线值**为**建议值**（设计 §3.1），可用环境变量覆盖：``ASTRA_NFR_KNOWLEDGE_SEARCH_P95_MS``。
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from typing import Any

import pytest
import sqlalchemy as sa
from astra_domain import KnowledgeQuery
from astra_knowledge import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    build_knowledge_repositories,
    build_knowledge_retriever,
)
from astra_memory import MemoryExtractor, MemoryManager, SqlMemoryStore, build_memory_repositories
from astra_model import ChatMessage, ChatResult, TokenCount
from sqlalchemy.orm import Session, sessionmaker

from tests.nfr._support import enforce_nfr, percentile, resolve_pg_url, with_connect_timeout

# -- 基线（建议值，可经环境变量覆盖；设计 §3.1） ------------------------------

#: ``search()`` p95 上界（毫秒，SQLite FTS5 关键字路）——**建议值 / 设计 §3.1**。
KNOWLEDGE_SEARCH_P95_MS = int(os.environ.get("ASTRA_NFR_KNOWLEDGE_SEARCH_P95_MS", "250"))

#: 分块规模（设计 §3.1：~1000 chunk）。
CHUNK_COUNT = 1000

#: 检索测量次数（取 p95）。
SEARCH_ITERATIONS = 20

#: 检索返回条数。
SEARCH_TOP_K = 10

KB_ID = "kb-nfr"
DOC_ID = "doc-nfr"
QUERY_TEXT = "knowledge retrieval"

_EMBED_DIMENSION = 8


# -- SQLite FTS5 基础设施（仿迁移 0013） --------------------------------------


def _ensure_sqlite_fts(engine: Any) -> None:  # noqa: ANN401 - sa.Engine
    """建 external-content FTS5 虚表 + 触发器（``create_all`` 不含迁移专属虚表）。"""
    ddl = [
        "CREATE VIRTUAL TABLE IF NOT EXISTS document_chunk_fts USING fts5("
        "content, content='document_chunk', content_rowid='rowid')",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_ai AFTER INSERT ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_ad AFTER DELETE ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); END",
        "CREATE TRIGGER IF NOT EXISTS document_chunk_au AFTER UPDATE ON document_chunk BEGIN "
        "INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); "
        "INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END",
    ]
    with engine.begin() as connection:
        for statement in ddl:
            connection.execute(sa.text(statement))


def _build_retriever(factory: sessionmaker[Session]) -> Any:  # noqa: ANN401
    """装配 stub 路由的最小 ``KnowledgeRetriever``（SQLite 关键字路）。"""
    from astra_model import ModelRegistry, ModelRouter
    from astra_model.stub import StubModelProvider

    registry = ModelRegistry()
    registry.register("stub", StubModelProvider(dimension=_EMBED_DIMENSION))
    return build_knowledge_retriever(
        session_factory=factory, model_router=ModelRouter(registry), vector_search=False
    )


def _seed_chunks(factory: sessionmaker[Session], *, count: int) -> None:
    """植一个 KB + 1 文档 + ``count`` 条分块（触发 FTS 索引）。"""
    repositories = build_knowledge_repositories(factory)
    repositories.knowledge_bases.add(
        KnowledgeBase(
            id=KB_ID,
            tenant_id="t-nfr",
            workspace_id="ws-nfr",
            name="nfr-kb",
            status="ACTIVE",
            created_by="u-nfr",
        )
    )
    repositories.documents.add(
        Document(
            id=DOC_ID,
            tenant_id="t-nfr",
            knowledge_base_id=KB_ID,
            title="nfr",
            source_type="text",
            status="READY",
        )
    )
    repositories.chunks.add_many(
        [
            DocumentChunk(
                id=f"chunk-{index:05d}",
                document_id=DOC_ID,
                ordinal=index,
                content=f"astra knowledge retrieval chunk number {index} topic {index % 10}",
                meta={"ordinal": index},
            )
            for index in range(count)
        ]
    )


# -- 用例 1：search() p95（SQLite FTS5 关键字路） -----------------------------


def test_knowledge_search_p95_sqlite(nfr_sqlite_factory: sessionmaker[Session]) -> None:
    """``N-P2-01``：~1000 chunk 下 ``search()`` p95（SQLite FTS5）低于建议基线。"""
    engine = nfr_sqlite_factory.kw["bind"]
    _ensure_sqlite_fts(engine)
    _seed_chunks(nfr_sqlite_factory, count=CHUNK_COUNT)

    retriever = _build_retriever(nfr_sqlite_factory)
    # 预热一次（排除首查编译 / 连接开销）。
    retriever.search(QUERY_TEXT, kb_ids=[KB_ID], top_k=SEARCH_TOP_K)

    latencies: list[float] = []
    for _ in range(SEARCH_ITERATIONS):
        start = time.perf_counter()
        hits = retriever.search(QUERY_TEXT, kb_ids=[KB_ID], top_k=SEARCH_TOP_K)
        latencies.append((time.perf_counter() - start) * 1000.0)
        assert hits, "检索未命中任何分块"

    p95 = percentile(latencies, 95)
    print(
        f"[NFR N-P2-01] knowledge search(SQLite/FTS5)：n={len(latencies)} "
        f"p50={percentile(latencies, 50):.2f}ms p95={p95:.2f}ms max={max(latencies):.2f}ms"
    )
    enforce_nfr("N-P2-01 / knowledge search p95(SQLite/FTS5)", p95, KNOWLEDGE_SEARCH_P95_MS)


def test_knowledge_search_p95_postgres_gated() -> None:
    """``N-P2-01`` · PG 真路 p95（``resolve_pg_url()`` 门控；本机无 PG → skip）。

    承接 **C2-28**：pgvector 语义检索路的 p95 需 PG + pgvector 权威环境方可复现，
    本机无 PG 运行时，故本路**未复现**（与 ``test_retriever_golden`` 的 PG 语义路同口径）。
    """
    url = with_connect_timeout(resolve_pg_url())

    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_config import Settings
    from astra_database import create_engine_from_settings

    engine = create_engine_from_settings(
        Settings(mode="server", database_url=url, secret_key="nfr-pg-secret")
    )
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - 依 PG 可用性而定
        if os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1":
            pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法连接 PostgreSQL：{exc}")
        pytest.skip(f"无法连接 PostgreSQL：{exc}")
    finally:
        engine.dispose()

    pytest.skip(
        "PG 语义检索（pgvector）p95 归权威 PG 环境（缺口 C2-28：本机无 pgvector 运行时，未复现）"
    )


# -- 用例 2：记忆抽取 token 上限（N-P2-04） -----------------------------------


class _SpyExtractionProvider:
    """记录下发 ``max_tokens`` / prompt 的 spy ``ModelProvider``（确定性计数）。"""

    def __init__(
        self,
        *,
        content: str = "[]",
        usage: dict[str, Any] | None = None,
        token_count: int = 10,
    ) -> None:
        self._content = content
        self._usage = usage if usage is not None else {"total_tokens": 0}
        self._token_count = int(token_count)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: Sequence[Any], **options: Any) -> ChatResult:
        """记录调用（含 ``max_tokens``）并返回预置结果。"""
        self.calls.append({"messages": list(messages), "options": dict(options)})
        return ChatResult(content=self._content, usage=dict(self._usage))

    def count_tokens(self, text: str, **options: Any) -> TokenCount:  # noqa: ARG002 - 协议签名
        """返回**常量**计数（确定性驱动输入截断判定）。"""
        return TokenCount(count=self._token_count)

    def stream(self, messages: Sequence[Any], **options: Any) -> Any:  # pragma: no cover
        yield self._content

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Any]:  # pragma: no cover
        return []


def test_extraction_dispatch_bounds_tokens_and_truncates_input() -> None:
    """``N-P2-04``：下发 ``max_tokens == limit - input_tokens``；``last_token_usage <= limit``。"""
    limit = 50
    token_count = 100  # > limit*0.5 → 触发输入截断
    provider = _SpyExtractionProvider(
        content="[]", usage={"total_tokens": 5}, token_count=token_count
    )
    extractor = MemoryExtractor(model_provider=provider, token_limit=limit)

    messages = [ChatMessage(role="user", content="x" * 4000)]
    extractor.extract(messages=messages, token_budget=limit)

    assert provider.calls, "抽取器未调用 Provider"
    call = provider.calls[-1]
    # 输入截断：下发 user 内容短于原始（原 4000 char）。
    assert len(call["messages"][-1].content) < 4000

    expected_input = min(token_count, limit)
    expected_max_tokens = max(1, limit - expected_input)
    assert call["options"]["max_tokens"] == expected_max_tokens
    # 抽取消耗不超过上限。
    assert extractor.last_token_usage <= limit


def test_extraction_under_limit_does_not_truncate() -> None:
    """``N-P2-04``：输入未超预算 → 不截断；``max_tokens == limit - input_tokens``。"""
    limit = 100
    token_count = 10
    provider = _SpyExtractionProvider(
        content="[]", usage={"total_tokens": 5}, token_count=token_count
    )
    extractor = MemoryExtractor(model_provider=provider, token_limit=limit)

    rendered = "hello world"
    extractor.extract(messages=[ChatMessage(role="user", content=rendered)], token_budget=limit)

    call = provider.calls[-1]
    assert call["messages"][-1].content == f"user: {rendered}", "未超预算不应截断输入"
    expected_input = min(token_count, limit)
    assert call["options"]["max_tokens"] == max(1, limit - expected_input)
    assert extractor.last_token_usage <= limit


def test_extraction_disabled_skips_extraction(
    nfr_sqlite_factory: sessionmaker[Session],
) -> None:
    """``N-P2-04``：``extraction_enabled=False`` → **不抽取**（不调用 Provider / 不落库）。"""
    from types import SimpleNamespace

    provider = _SpyExtractionProvider(content="[]", usage={"total_tokens": 5})
    repositories = build_memory_repositories(nfr_sqlite_factory)
    settings = SimpleNamespace(extraction_enabled=False, extraction_token_limit=2000)
    manager = MemoryManager(
        store=SqlMemoryStore(repository=repositories.memories),
        extractor=MemoryExtractor(model_provider=provider),
        relation_repository=repositories.relations,
        settings=settings,
    )

    run = SimpleNamespace(
        id="run-1",
        tenant_id="t-nfr",
        user_id="u-nfr",
        agent_id="a1",
        conversation_id="c1",
        workspace_id="ws-nfr",
        trigger="user",
    )
    saved = manager.extract(
        run=run, messages=[ChatMessage(role="user", content="记住：我喜欢深色主题")]
    )

    assert saved == []
    assert provider.calls == [], "抽取开关关闭时不得调用 Provider"


def test_retrieve_maps_query_through_workspace(
    nfr_sqlite_factory: sessionmaker[Session],
) -> None:
    """回归闸：``retrieve``（RP-02）经 ``workspace_id`` 回落可召回（NFR 模块内自洽）。"""
    engine = nfr_sqlite_factory.kw["bind"]
    _ensure_sqlite_fts(engine)
    _seed_chunks(nfr_sqlite_factory, count=5)
    retriever = _build_retriever(nfr_sqlite_factory)

    chunks = retriever.retrieve(KnowledgeQuery(text=QUERY_TEXT, workspace_id="ws-nfr", top_k=3))
    assert chunks, "retrieve 未召回"
