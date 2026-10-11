"""Retriever golden 语料双路集成测试（W5 / T2-30）。

覆盖（W5 开工前架构裁定 §2.4 / §3.4 / B5 / B7 / R-40 / DoD D10）：

- **SQLite FTS5 关键字路**：以固定 golden 语料（20 文档）断言 ``chunk_id`` 集合 ⊇ 期望集合、
  ``score`` 排序稳定（``-bm25`` 降序），并断言 ``metadata.mode == "keyword"``；
- **PG 语义路**：断言 :class:`SemanticRetriever` 的映射 / 排序（用 stub 向量仓储，无需 PG）；
  真实 pgvector 路受 ``ASTRA_TEST_PG_URL`` 门控，**在权威 PG 上实跑真实余弦召回端到端断言**
  （C2-31：受控向量 → ``<=>`` 排序 + 分数 + 引用回溯；本机无 PG → skip）。
  该用例建表落在**专用库** ``<db>_knowledge``（见 :func:`_dedicated_pg_url`），
  不污染共享库 schema / ``alembic_version``；
- **capability 选路**：``vector_search`` 构造期二选一（**禁运行时 try/except 推断**）；
- **KB 解析（B7）**：``agent_version_id`` 绑定路 vs ``workspace_id`` 回落路（§12-d 默认）；
- **``resolve_vector_search_capability``**：三态解析（显式覆盖 / SQLite 自动 False）。
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from astra_domain import KnowledgeQuery
from astra_knowledge import (
    AgentKnowledge,
    Document,
    DocumentChunk,
    Embedder,
    FtsRetriever,
    KnowledgeBase,
    KnowledgeRetriever,
    SemanticRetriever,
    SqlAgentKnowledgeRepository,
    SqlDocumentChunkRepository,
    SqlDocumentRepository,
    SqlEmbeddingRepository,
    SqlKnowledgeBaseRepository,
    build_knowledge_retriever,
    resolve_vector_search_capability,
)
from astra_model import ModelRegistry, ModelRouter
from astra_model.stub import StubModelProvider
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "knowledge"
CORPUS = FIXTURES / "corpus"

_EMBED_DIMENSION = 8
_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"

#: C2-31 真实召回用例**专用库**名后缀（与迁移套件 / 其它 PG 套件物理隔离）。
_KNOWLEDGE_DB_SUFFIX = "_knowledge"


def _expected() -> dict[str, Any]:
    """读取 golden 期望集。"""
    return json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


def _ensure_sqlite_fts(engine: sa.Engine) -> None:
    """在隔离 SQLite 上建 external-content FTS5 虚表 + ``ai``/``ad``/``au`` 触发器（仿 ``0013``）。

    测试基础设施：``session_factory`` 经 ``Base.metadata.create_all`` 建表，不含迁移专属
    FTS5 虚表（由 ``0013`` 创建），故此处按同口径补齐以驱动关键字路。
    """
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


def _router() -> ModelRouter:
    """构造 stub Model Router（维度 ``_EMBED_DIMENSION``）。"""
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider(dimension=_EMBED_DIMENSION))
    return ModelRouter(registry)


def _seed(session_factory: object) -> dict[str, Any]:
    """植入 golden KB + 20 文档 + 20 分块 + 1 条 ``agent_knowledge`` 绑定（固定 ID）。"""
    expected = _expected()
    kb_id = str(expected["kb_id"])
    workspace_id = str(expected["workspace_id"])
    kb_repository = SqlKnowledgeBaseRepository(session_factory)  # type: ignore[arg-type]
    document_repository = SqlDocumentRepository(session_factory)  # type: ignore[arg-type]
    chunk_repository = SqlDocumentChunkRepository(session_factory)  # type: ignore[arg-type]
    binding_repository = SqlAgentKnowledgeRepository(session_factory)  # type: ignore[arg-type]

    kb_repository.add(
        KnowledgeBase(
            id=kb_id,
            tenant_id="t-golden",
            workspace_id=workspace_id,
            name="golden",
            created_by="u-golden",
            status="ACTIVE",
            embedding_model={
                "provider": "stub",
                "model": "stub-embed",
                "dimensions": _EMBED_DIMENSION,
            },
            chunk_config={"strategy": "fixed", "size": 800, "overlap": 100},
        )
    )

    files = sorted(path for path in CORPUS.iterdir() if path.suffix in {".md", ".txt"})
    assert len(files) >= 20, f"golden 语料文档数不足：{len(files)}"
    for index, path in enumerate(files, start=1):
        document = document_repository.add(
            Document(
                id=f"doc-{index:03d}",
                knowledge_base_id=kb_id,
                title=path.stem,
                source_type="text",
                mime="text/markdown" if path.suffix == ".md" else "text/plain",
                status="READY",
            )
        )
        chunk_repository.add(
            DocumentChunk(
                id=f"chunk-{index:03d}",
                document_id=document.id,
                ordinal=0,
                content=path.read_text(encoding="utf-8"),
                meta={"format": path.suffix.lstrip("."), "source": path.name},
            )
        )

    binding_repository.add(
        AgentKnowledge(
            id="ak-golden",
            tenant_id="t-golden",
            agent_version_id=str(expected["agent_version_id"]),
            knowledge_base_id=kb_id,
            enabled=True,
        )
    )
    return {"kb_id": kb_id, "workspace_id": workspace_id, "expected": expected}


@pytest.fixture()
def golden(session_factory: object) -> dict[str, Any]:
    """建 FTS5 虚表 + 植入 golden 语料，返回上下文。"""
    engine = session_factory.kw["bind"]  # type: ignore[attr-defined]
    _ensure_sqlite_fts(engine)
    return _seed(session_factory)


# -- SQLite FTS5 关键字路 golden ---------------------------------------------


def test_fts_retriever_golden_chunk_ids_and_ordering(
    golden: dict[str, Any], session_factory
) -> None:
    """固定 golden 语料：``chunk_id`` 集合 ⊇ 期望集合 + ``score`` 排序稳定（I-P2-07）。"""
    retriever = build_knowledge_retriever(
        session_factory=session_factory, model_router=_router(), vector_search=False
    )
    assert isinstance(retriever, KnowledgeRetriever)
    assert retriever.vector_search is False
    assert isinstance(retriever.backend, FtsRetriever)

    for case in golden["expected"]["queries"]:
        results = retriever.search(str(case["text"]), kb_ids=[golden["kb_id"]], top_k=25)
        returned = {item.chunk_id for item in results}
        assert returned >= set(case["expected_chunk_ids"]), (
            f"query={case['text']!r}：召回 {sorted(returned)} 未覆盖期望 "
            f"{case['expected_chunk_ids']}"
        )
        scores = [item.score for item in results]
        assert scores == sorted(scores, reverse=True), f"query={case['text']!r}：score 未降序"
        assert all(item.metadata.get("mode") == "keyword" for item in results)


def test_fts_retriever_returns_references(golden: dict[str, Any], session_factory) -> None:
    """引用可回溯：``source`` / ``metadata.document_id`` / ``ordinal`` 齐备。"""
    retriever = build_knowledge_retriever(
        session_factory=session_factory, model_router=_router(), vector_search=False
    )
    results = retriever.search("retrieval", kb_ids=[golden["kb_id"]], top_k=5)
    assert results, "未召回任何分块"
    top = results[0]
    assert top.chunk_id == "chunk-001"
    assert top.source == "doc-001"
    assert top.metadata.get("document_id") == "doc-001"
    assert top.metadata.get("ordinal") == 0


def test_retrieve_maps_to_knowledge_chunks_via_workspace(
    golden: dict[str, Any], session_factory
) -> None:
    """RP-02 ``retrieve``：经 ``workspace_id`` 回落解析 KB，映射为 ``KnowledgeChunk``。"""
    retriever = build_knowledge_retriever(
        session_factory=session_factory, model_router=_router(), vector_search=False
    )
    chunks = retriever.retrieve(
        KnowledgeQuery(text="retrieval", workspace_id=golden["workspace_id"], top_k=5)
    )
    assert chunks, "retrieve 未召回"
    assert all(isinstance(chunk.content, str) and chunk.content for chunk in chunks)
    assert any(chunk.source == "doc-001" for chunk in chunks)


def test_retrieve_resolves_kb_via_agent_version(golden: dict[str, Any], session_factory) -> None:
    """RP-02 ``retrieve``：经 ``agent_version_id`` 绑定解析 KB（B7 主路）。"""
    retriever = build_knowledge_retriever(
        session_factory=session_factory, model_router=_router(), vector_search=False
    )
    chunks = retriever.retrieve(
        KnowledgeQuery(
            text="sqlite",
            agent_version_id=str(golden["expected"]["agent_version_id"]),
            top_k=5,
        )
    )
    assert chunks, "retrieve（绑定路）未召回"
    assert any(chunk.source == "doc-006" for chunk in chunks)


def test_retrieve_empty_without_kb_resolution(session_factory) -> None:
    """既无 ``agent_version_id`` 又无 ``workspace_id`` → 空（保守：不跨工作区召回）。"""
    retriever = build_knowledge_retriever(
        session_factory=session_factory, model_router=_router(), vector_search=False
    )
    assert retriever.retrieve(KnowledgeQuery(text="retrieval")) == []


# -- PG 语义路（stub 断言 + 真实 PG 门控） ------------------------------------


class _StubEmbeddingRepository:
    """仅实现 ``search_semantic`` 的 stub 向量仓储（断言语义路映射 / 排序）。"""

    def __init__(self, pairs: list[tuple[DocumentChunk, float]]) -> None:
        self._pairs = pairs

    def search_semantic(
        self,
        vector: list[float],
        *,
        knowledge_base_ids: list[str],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """返回预置 ``(chunk, score)`` 对（截断 ``top_k``）。"""
        return list(self._pairs[:top_k])


def test_semantic_retriever_maps_and_orders(golden: dict[str, Any], session_factory) -> None:
    """语义路（stub）：保持分数降序、映射为 ``RetrievedChunk``（``mode="semantic"``）。"""
    pairs = [
        (DocumentChunk(id="chunk-007", document_id="doc-007", ordinal=0, content="postgres"), 0.92),
        (
            DocumentChunk(id="chunk-002", document_id="doc-002", ordinal=0, content="embedding"),
            0.64,
        ),
    ]
    semantic = SemanticRetriever(
        embedding_repository=_StubEmbeddingRepository(pairs),  # type: ignore[arg-type]
        knowledge_base_repository=SqlKnowledgeBaseRepository(session_factory),
        embedder=Embedder(model_router=_router(), embedding_dimensions=_EMBED_DIMENSION),
    )
    results = semantic.search("postgres", kb_ids=[golden["kb_id"]], top_k=2)
    assert [item.chunk_id for item in results] == ["chunk-007", "chunk-002"]
    assert [item.score for item in results] == [0.92, 0.64]
    assert all(item.metadata.get("mode") == "semantic" for item in results)


def test_retriever_selects_semantic_backend() -> None:
    """capability 选路：``vector_search=True`` → 注入 ``SemanticRetriever``（构造期一次性）。"""
    semantic = SemanticRetriever(
        embedding_repository=_StubEmbeddingRepository([]),  # type: ignore[arg-type]
        knowledge_base_repository=None,  # type: ignore[arg-type]
        embedder=Embedder(model_router=_router(), embedding_dimensions=_EMBED_DIMENSION),
    )
    fts = FtsRetriever(chunk_repository=None)  # type: ignore[arg-type]
    retriever = KnowledgeRetriever(vector_search=True, semantic=semantic, fts=fts)
    assert retriever.backend is semantic
    retriever_fts = KnowledgeRetriever(vector_search=False, semantic=semantic, fts=fts)
    assert retriever_fts.backend is fts


# -- capability 解析（B5） ----------------------------------------------------


def test_resolve_vector_search_capability_explicit() -> None:
    """显式三态：``True`` / ``False`` 覆盖优先（不触 DB）。"""
    assert resolve_vector_search_capability(explicit=True, session_factory=None) is True  # type: ignore[arg-type]
    assert resolve_vector_search_capability(explicit=False, session_factory=None) is False  # type: ignore[arg-type]


def test_resolve_vector_search_capability_sqlite_auto(session_factory) -> None:
    """``None``（自动）+ SQLite → 确定性探测得 ``False``。"""
    assert resolve_vector_search_capability(explicit=None, session_factory=session_factory) is False


#: PG 语义路固定维度（＝ ``embedding.vector`` 列维度 ``EMBEDDING_DIMENSIONS``；
#: 受控向量必须等长，否则 PG ``vector(1536)`` 列拒收）。
_PG_EMBED_DIMENSION = 1536


def _unit_vector(index: int, dimensions: int = _PG_EMBED_DIMENSION) -> list[float]:
    """``dimensions`` 维单位基向量 ``e_index``（受控向量的余弦相似度可精确预期）。"""
    vector = [0.0] * dimensions
    vector[index] = 1.0
    return vector


def _mixed_vector(dimensions: int = _PG_EMBED_DIMENSION) -> list[float]:
    """``0.9·e0 + 0.1·e1``：与 ``e0`` 的余弦相似度 ＝ ``0.9/√0.82``（严格介于 1.0 与 0.0）。"""
    vector = [0.0] * dimensions
    vector[0], vector[1] = 0.9, 0.1
    return vector


class _FixedVectorEmbedder:
    """返回**固定**查询向量的 ``Embedder`` 替身（仅用于端到端映射断言）。

    🔴 只替换「文本 → 向量」这一步（``ModelProvider`` 职责，另有用例覆盖）；
       ``SemanticRetriever → SqlEmbeddingRepository → pgvector <=>`` 全链仍为**真实**。
    """

    def __init__(self, vector: list[float]) -> None:
        self._vector = list(vector)

    def embed(self, texts: Sequence[str], *, kb: KnowledgeBase) -> list[list[float]]:
        """对每个输入文本返回同一固定向量。"""
        return [list(self._vector) for _ in texts]


def _purge_pg_rows(
    factory: sessionmaker[Session],
    *,
    tenant_id: str,
    user_id: str,
    kb_id: str,
    doc_id: str,
    chunk_ids: list[str],
) -> None:
    """清理本用例**自有行**（不 ``drop_all`` 全库——避免与其它套件互扰，P2-105 教训）。"""
    from astra_database.models.identity import Tenant as OrmTenant
    from astra_database.models.identity import User as OrmUser
    from astra_database.models.knowledge import Document as OrmDocument
    from astra_database.models.knowledge import DocumentChunk as OrmDocumentChunk
    from astra_database.models.knowledge import Embedding as OrmEmbedding
    from astra_database.models.knowledge import KnowledgeBase as OrmKnowledgeBase

    with factory() as session:
        session.execute(sa.delete(OrmEmbedding).where(OrmEmbedding.chunk_id.in_(chunk_ids)))
        session.execute(sa.delete(OrmDocumentChunk).where(OrmDocumentChunk.id.in_(chunk_ids)))
        session.execute(sa.delete(OrmDocument).where(OrmDocument.id == doc_id))
        session.execute(sa.delete(OrmKnowledgeBase).where(OrmKnowledgeBase.id == kb_id))
        session.execute(sa.delete(OrmUser).where(OrmUser.id == user_id))
        session.execute(sa.delete(OrmTenant).where(OrmTenant.id == tenant_id))
        session.commit()


def _add_connect_timeout(url: str) -> str:
    """为 PG 连接串注入 ``connect_timeout``（幂等，避免探测阶段长时间挂起）。"""
    if "connect_timeout" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}connect_timeout=10"


def _dedicated_pg_url(url: str) -> str:
    """派生 C2-31 **专用库**连接串（``<db>_knowledge``；不存在则幂等 ``CREATE DATABASE``）。

    🔴 本用例会 ``Base.metadata.create_all``。若落在 ``ASTRA_TEST_PG_URL`` 指向的**共享库**上，
    会把 HEAD 之后 revision 的表一并补齐而 ``alembic_version`` 不动 ⇒ 共享库陷入
    「schema 已到 head、版本仍停旧 revision」的**不可 upgrade** 状态：``alembic check``
    报假漂移，``alembic upgrade head`` 因表已存在而直接崩。与 ``P2-105``（NFR）及
    ``test_postgres_smoke`` 承接项 A **同源**，故一律隔离到专用库。

    ``ASTRA_TEST_REQUIRE_PG=1`` 时不可用即 **fail**（防假绿），否则 skip。
    """
    parsed = sa.engine.make_url(_add_connect_timeout(url))
    database = parsed.database or "postgres"
    target = f"{database}{_KNOWLEDGE_DB_SUFFIX}"
    try:
        admin = sa.create_engine(
            parsed.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True
        )
        try:
            with admin.connect() as connection:
                exists = connection.execute(
                    sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target}
                ).first()
                if exists is None:
                    connection.exec_driver_sql(f'CREATE DATABASE "{target}"')
        finally:
            admin.dispose()
    except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - 依 PG 权限而定
        if _REQUIRE_PG:
            pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法创建专用库 {target}：{exc}")
        pytest.skip(f"无法创建专用库 {target}：{exc}")
    # 🔴 必须 ``render_as_string(hide_password=False)``：``str(URL)`` 默认把密码渲染为 ``***``。
    return _add_connect_timeout(parsed.set(database=target).render_as_string(hide_password=False))


def _pg_engine_with_schema() -> tuple[sa.Engine, sessionmaker[Session]]:
    """建**专用库** PG 引擎 + 确保 ``vector`` 扩展与 ORM schema（PG 门控 skip / fail 语义）。

    对齐 ``tests/integration/conftest.py`` 与 ``tests/nfr/_support.resolve_pg_url``：
    ``ASTRA_TEST_REQUIRE_PG=1`` 时任何不可用均 **fail**（防假绿），否则 skip。
    """
    if not _PG_URL:
        if _REQUIRE_PG:
            pytest.fail(
                "ASTRA_TEST_REQUIRE_PG=1 但未设置 ASTRA_TEST_PG_URL —— C2-31 不得被跳过（防假绿）。"
            )
        pytest.skip("未设置 ASTRA_TEST_PG_URL")
    url = _dedicated_pg_url(_PG_URL)

    try:
        import pgvector.sqlalchemy  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 依环境而定
        if _REQUIRE_PG:
            pytest.fail(
                "C2-31 需 pgvector Python 包（``VectorType`` 渲染 ``vector`` 列）；"
                "请以 ``uv run --with pgvector …`` 运行。"
            )
        pytest.skip(f"pgvector Python 包不可用：{exc}")

    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_config import Settings
    from astra_database import Base, create_engine_from_settings, create_session_factory

    engine = create_engine_from_settings(
        Settings(mode="server", database_url=url, secret_key="pg-recall-secret")
    )
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - 依 PG 可用性而定
        engine.dispose()
        if _REQUIRE_PG:
            pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法连接 PostgreSQL：{exc}")
        pytest.skip(f"无法连接 PostgreSQL：{exc}")

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - 依扩展可用性而定
        engine.dispose()
        if _REQUIRE_PG:
            pytest.fail(f"无法启用 pgvector 扩展：{exc}")
        pytest.skip(f"pgvector 扩展不可用：{exc}")

    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_semantic_retriever_pg_gated() -> None:  # pragma: no cover - 依赖 PG
    """真实 PG + pgvector：余弦召回**端到端**（C2-31；权威 PG 实证）。

    覆盖此前为空白的「真实向量召回正确性」：

    1. 受控向量经 :meth:`SqlEmbeddingRepository.search_semantic` 的 pgvector ``<=>``
       **精确**按余弦序召回（``score`` ＝ 余弦相似度）；
    2. :func:`resolve_vector_search_capability` 在 PG + ``vector`` 扩展下自动解析 ``True``（B5）；
    3. :class:`SemanticRetriever`（真实仓储 + 确定性查询向量）返回同序，且引用可回溯
       （``source == document_id``）、``metadata.mode == "semantic"``。
    """
    from astra_core import generate_id
    from astra_database.models.identity import Tenant as OrmTenant
    from astra_database.models.identity import User as OrmUser
    from astra_knowledge import Document as KnowledgeDocument
    from astra_knowledge import DocumentChunk as KnowledgeChunk
    from astra_knowledge import Embedding as KnowledgeEmbedding
    from astra_knowledge import KnowledgeBase as KnowledgeBaseEntity

    engine, factory = _pg_engine_with_schema()

    tenant_id, user_id, kb_id = generate_id(), generate_id(), generate_id()
    doc_id = generate_id()
    chunk_near, chunk_mid, chunk_far = generate_id(), generate_id(), generate_id()
    expected_order = [chunk_near, chunk_mid, chunk_far]
    expected_scores = [1.0, 0.9 / math.sqrt(0.82), 0.0]

    kb_repository = SqlKnowledgeBaseRepository(factory)
    document_repository = SqlDocumentRepository(factory)
    chunk_repository = SqlDocumentChunkRepository(factory)
    embedding_repository = SqlEmbeddingRepository(factory)
    try:
        # 父图（PG 强制 FK；按 FK 拓扑分阶段 flush 钉死 INSERT 顺序）。
        with factory() as session:
            session.add(OrmTenant(id=tenant_id, slug=f"pg-{tenant_id[:8]}", name="PG Recall"))
            session.flush()
            session.add(
                OrmUser(
                    id=user_id,
                    tenant_id=tenant_id,
                    username=f"pg-{user_id[:8]}",
                    email=f"{user_id[:8]}@example.com",
                    password_hash="x",
                )
            )
            session.commit()

        kb = kb_repository.add(
            KnowledgeBaseEntity(
                id=kb_id,
                tenant_id=tenant_id,
                workspace_id=None,
                name=f"pg-{kb_id[:8]}",
                status="ACTIVE",
                created_by=user_id,
                embedding_model={
                    "provider": "stub",
                    "model": "stub-embed",
                    "dimensions": _PG_EMBED_DIMENSION,
                },
                chunk_config={"strategy": "fixed", "size": 800, "overlap": 100},
            )
        )
        document = document_repository.add(
            KnowledgeDocument(
                id=doc_id,
                knowledge_base_id=kb.id,
                title="pg-recall",
                source_type="text",
                mime="text/plain",
                status="READY",
            )
        )
        chunk_repository.add_many(
            [
                KnowledgeChunk(id=chunk_near, document_id=document.id, ordinal=0, content="near"),
                KnowledgeChunk(id=chunk_mid, document_id=document.id, ordinal=1, content="mid"),
                KnowledgeChunk(id=chunk_far, document_id=document.id, ordinal=2, content="far"),
            ]
        )
        embedding_repository.add_many(
            [
                KnowledgeEmbedding(
                    chunk_id=chunk_near,
                    model="stub-embed",
                    dimensions=_PG_EMBED_DIMENSION,
                    vector=_unit_vector(0),
                ),
                KnowledgeEmbedding(
                    chunk_id=chunk_far,
                    model="stub-embed",
                    dimensions=_PG_EMBED_DIMENSION,
                    vector=_unit_vector(1),
                ),
                KnowledgeEmbedding(
                    chunk_id=chunk_mid,
                    model="stub-embed",
                    dimensions=_PG_EMBED_DIMENSION,
                    vector=_mixed_vector(),
                ),
            ]
        )

        query = _unit_vector(0)

        # (1) 真实 pgvector `<=>` 排序 + 余弦分数
        pairs = embedding_repository.search_semantic(query, knowledge_base_ids=[kb.id], top_k=3)
        assert [chunk.id for chunk, _ in pairs] == expected_order
        assert [score for _, score in pairs] == [
            pytest.approx(value, abs=1e-5) for value in expected_scores
        ]

        # (2) capability 自动探测：PG + vector 扩展 → True（B5）
        assert resolve_vector_search_capability(explicit=None, session_factory=factory) is True

        # (3) SemanticRetriever 端到端映射（引用可回溯 + mode=semantic）
        semantic = SemanticRetriever(
            embedding_repository=embedding_repository,
            knowledge_base_repository=kb_repository,
            embedder=_FixedVectorEmbedder(query),  # type: ignore[arg-type]
        )
        results = semantic.search("near", kb_ids=[kb.id], top_k=3)
        assert [item.chunk_id for item in results] == expected_order
        assert results[0].score == pytest.approx(1.0, abs=1e-5)
        assert results[0].source == document.id
        assert results[0].metadata.get("document_id") == document.id
        assert all(item.metadata.get("mode") == "semantic" for item in results)
    finally:
        _purge_pg_rows(
            factory,
            tenant_id=tenant_id,
            user_id=user_id,
            kb_id=kb_id,
            doc_id=doc_id,
            chunk_ids=[chunk_near, chunk_mid, chunk_far],
        )
        engine.dispose()
