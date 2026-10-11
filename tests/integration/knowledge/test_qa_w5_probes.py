"""W5 独立 QA 探针（第二层验证；非工程师自测复述）。

本文件由 QA（严过关）独立编写，用于**负向 / 边界 / 生产 DDL 实证**，逐条对应主理人下发的
验证要求（1–8）。**不复用**工程师 golden 测试的“手工建 FTS5 虚表”设施，改以**真实迁移 `0013`
的 DDL** 驱动检索，直接检验「生产 DDL 是否真的可用」（回应工程师偏离 1 的掩盖风险）。

覆盖：
- 迁移 `0013`：downgrade **严禁 `DROP EXTENSION`**（静态断言）；方言分支为**显式**
  ``op.get_bind().dialect.name``；`embedding.chunk_id` **非空 + FK**、`document_chunk.embedding_id`
  **可空无 FK**；
- **生产 DDL 实证**：迁移建表后直接经 ``SqlDocumentChunkRepository.search_fts`` 命中（不再手工复刻
  FTS5 DDL）——若迁移的 FTS5 虚表 / 触发器有缺陷，本探针必红；
- capability 选路**负向**：``vector_search=False`` → ``FtsRetriever`` 且**不写** ``embedding`` 表；
- 检索实现模块**零运行时 try/except 方言推断**（源码级静态断言）。
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0013_phase2_knowledge.py"
KNOWLEDGE_SRC = REPO_ROOT / "packages" / "knowledge" / "src" / "astra_knowledge"


# -- 1. 迁移静态契约（不依赖 DB 方言） ---------------------------------------


def _strip_comments_and_strings(source: str) -> str:
    """剔除注释与字符串字面量（含模块 / 函数 docstring），仅保留可执行代码骨架。

    用于避免「文档字符串里出现禁用词」造成的假阳性——只对**可执行 SQL / 代码**断言。
    """
    import io
    import tokenize

    out: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        if token.type in (tokenize.NEWLINE, tokenize.NL):
            out.append("\n")
        else:
            out.append(token.string)
    return "".join(out)


def test_qa_w5_downgrade_never_drops_extension() -> None:
    """`0013` downgrade **严禁 `DROP EXTENSION vector`**（QA-31）：可执行代码级断言。"""
    source = _strip_comments_and_strings(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert (
        "DROP EXTENSION" not in source.upper()
    ), "0013 可执行代码出现 DROP EXTENSION（违反 QA-31）"
    # downgrade 函数体不得触碰 extension。
    downgrade_body = source.split("def downgrade")[-1]
    assert "EXTENSION" not in downgrade_body.upper(), "downgrade 触碰 extension —— 违反 QA-31"
    # 正向：PG 分支确有 CREATE EXTENSION（savepoint 降级，字符串字面量，用原文断言）。
    assert "CREATE EXTENSION IF NOT EXISTS vector" in MIGRATION_PATH.read_text(encoding="utf-8")


def test_qa_w5_declares_both_five_tables() -> None:
    """`0013` 建且仅建五张 Knowledge 表（含唯一键名冻结契约）。"""
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    for table in (
        "knowledge_base",
        "document",
        "document_chunk",
        "embedding",
        "agent_knowledge",
    ):
        assert f'op.create_table(\n        "{table}"' in source or f'"{table}",' in source
    for unique_name in (
        "uq_knowledge_base_tenant_name",
        "uq_document_chunk_document_ordinal",
        "uq_embedding_chunk_id",
        "uq_agent_knowledge_version_kb",
    ):
        assert unique_name in source, f"缺唯一键冻结名：{unique_name}"


def test_qa_w5_migration_dialect_branch_is_explicit() -> None:
    """方言分支必须是显式 ``op.get_bind().dialect.name``（禁 try/except 推断方言）。"""
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert source.count("op.get_bind().dialect.name") >= 2, "upgrade / downgrade 均应显式取方言"
    # 唯一允许的 try/except：CREATE EXTENSION 的功能性降级（savepoint）；不得包裹方言判定。
    # 断言：不存在「try 块内同时出现 dialect 判定」的形态。
    try_blocks = re.findall(r"try:\n(.*?)\n\s*except", source, flags=re.DOTALL)
    for block in try_blocks:
        assert "dialect" not in block, "try/except 用于方言判定 —— 违反 W5 裁定 §8-4"


def test_qa_w5_retriever_modules_have_no_runtime_try_except() -> None:
    """检索 / 嵌入落库实现**零运行时 try/except 方言或能力推断**（源码级负向断言）。"""
    for filename in (
        "retriever.py",
        "retriever_fts.py",
        "retriever_semantic.py",
        "embedding_store.py",
    ):
        text = (KNOWLEDGE_SRC / filename).read_text(encoding="utf-8")
        # 去掉 docstring / 注释行后再判 try:（docstring 里可能出现 "try/except" 字样）。
        code_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        code = "\n".join(code_lines)
        assert not re.search(
            r"^\s*try\s*:", code, flags=re.MULTILINE
        ), f"{filename} 含运行时 try/except（方言 / 能力推断被禁）"


# -- 4/5. 生产 DDL 实证（真实迁移，不手工复刻 FTS5） -------------------------


def _migrate_head_to_fresh_sqlite(tmp_dir: Path) -> str:
    """在全新 SQLite 上跑真实 `alembic upgrade head`，返回连接串。

    复刻 ``test_0013`` 的配置注入路径（``ASTRA_DATABASE_URL`` + 重置配置缓存）。
    """
    from alembic import command
    from alembic.config import Config
    from astra_config.loader import reset_settings_cache

    url = f"sqlite:///{(tmp_dir / 'qa_w5_prod.db').as_posix()}"
    import os

    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")
    return url


@pytest.fixture()
def migrated_engine() -> sa.Engine:
    """迁移 `head` 后的真实 SQLite 引擎（teardown 重置配置缓存）。"""
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _migrate_head_to_fresh_sqlite(tmp_dir)
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        reset_settings_cache()


def test_qa_w5_fts_works_from_real_migration_ddl(migrated_engine: sa.Engine) -> None:
    """**关键**：迁移 `0013` 的 FTS5 虚表 + 触发器**真实可用**（不经手工复刻 DDL）。

    直接在迁移产物上经 ORM 仓储插分块（触发 ``ai`` 触发器填充 external-content 虚表），
    再经生产 ``search_fts`` 命中——若迁移 DDL 有缺陷（列名 / content_rowid / 触发器错），
    本探针必红；从而独立证伪「工程师仅靠手工复刻 FTS5 掩盖生产 DDL 缺陷」的风险。
    """
    from astra_knowledge import (
        Document,
        DocumentChunk,
        KnowledgeBase,
        SqlDocumentChunkRepository,
        SqlDocumentRepository,
        SqlKnowledgeBaseRepository,
    )

    factory = sessionmaker(bind=migrated_engine, class_=Session)
    kb = SqlKnowledgeBaseRepository(factory).add(
        KnowledgeBase(
            tenant_id="t-qa",
            name="kb-qa",
            created_by="u-qa",
            status="ACTIVE",
            embedding_model={"provider": "stub", "model": "m", "dimensions": 8},
            chunk_config={"strategy": "fixed", "size": 800, "overlap": 100},
        )
    )
    document = SqlDocumentRepository(factory).add(
        Document(
            knowledge_base_id=kb.id,
            title="qa",
            source_type="text",
            status="READY",
        )
    )
    chunk_repository = SqlDocumentChunkRepository(factory)
    saved = chunk_repository.add(
        DocumentChunk(
            document_id=document.id,
            ordinal=0,
            content="qaalphaunique zeta knowledge marker text",
        )
    )

    # 生产 DDL：既未手工建虚表，亦未手工建触发器；完全依赖迁移 0013。
    hits = chunk_repository.search_fts("qaalphaunique", knowledge_base_ids=[kb.id], top_k=5)
    assert hits, "迁移 0013 的 FTS5 虚表 / 触发器未生效（生产 DDL 缺陷）"
    assert saved.id in {chunk.id for chunk, _ in hits}


def test_qa_w5_nullability_and_fk_direction(migrated_engine: sa.Engine) -> None:
    """`embedding.chunk_id` 非空 + FK；`document_chunk.embedding_id` 可空、**无** FK。"""
    inspector = sa.inspect(migrated_engine)

    embedding_cols = {c["name"]: c for c in inspector.get_columns("embedding")}
    assert embedding_cols["chunk_id"]["nullable"] is False
    embedding_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("embedding")}
    assert "document_chunk" in embedding_fks, embedding_fks

    chunk_cols = {c["name"]: c for c in inspector.get_columns("document_chunk")}
    assert chunk_cols["embedding_id"]["nullable"] is True
    chunk_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("document_chunk")}
    assert "embedding" not in chunk_fks, "document_chunk 出现指向 embedding 的外键（双向环）"
    assert "document" in chunk_fks


def test_qa_w5_downgrade_only_drops_own_objects(migrated_engine: sa.Engine) -> None:
    """downgrade 至 `0012`：仅 drop 自有五表 + FTS5 虚表；`0012` 表保留。"""
    from alembic import command
    from alembic.config import Config
    from astra_config.loader import reset_settings_cache

    url = str(migrated_engine.url)
    import os

    os.environ["ASTRA_DATABASE_URL"] = url
    reset_settings_cache()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.downgrade(config, "0012_phase2_workflow")

    inspector = sa.inspect(migrated_engine)
    remaining = set(inspector.get_table_names())
    for table in (
        "knowledge_base",
        "document",
        "document_chunk",
        "embedding",
        "agent_knowledge",
        "document_chunk_fts",
    ):
        assert table not in remaining, f"downgrade 未清理自有对象：{table}"
    assert {"workflow", "workflow_run", "approval", "task"}.issubset(remaining)
    reset_settings_cache()


# -- 2/6. capability 选路负向 + 组合根实证 -----------------------------------


def test_qa_w5_vector_search_false_writes_no_embedding(session_factory) -> None:
    """负向：``vector_search=False``（SQLite）→ `embedding` 表零写入、`embedding_id` 保持 NULL。"""
    from astra_knowledge import (
        Document,
        DocumentChunk,
        EmbeddingStore,
        KnowledgeBase,
        SqlDocumentChunkRepository,
        SqlDocumentRepository,
        SqlEmbeddingRepository,
        SqlKnowledgeBaseRepository,
    )

    kb = SqlKnowledgeBaseRepository(session_factory).add(
        KnowledgeBase(
            tenant_id="t1",
            name="kb-neg",
            created_by="u1",
            status="ACTIVE",
            embedding_model={"provider": "stub", "model": "m", "dimensions": 8},
            chunk_config={"strategy": "fixed", "size": 800, "overlap": 100},
        )
    )
    document = SqlDocumentRepository(session_factory).add(
        Document(knowledge_base_id=kb.id, title="d", status="EMBEDDING")
    )
    chunk_repository = SqlDocumentChunkRepository(session_factory)
    chunks = chunk_repository.add_many(
        [DocumentChunk(document_id=document.id, ordinal=i, content=f"c{i}") for i in range(2)]
    )
    store = EmbeddingStore(
        embedding_repository=SqlEmbeddingRepository(session_factory),
        chunk_repository=chunk_repository,
        vector_search=False,
    )
    assert store.write(chunks, [[0.0] * 8, [0.1] * 8], kb=kb) == []
    assert SqlEmbeddingRepository(session_factory).list() == []
    assert all(chunk_repository.get(c.id).embedding_id is None for c in chunks)


def test_qa_w5_capability_false_selects_fts_backend(session_factory) -> None:
    """构造期选路：``vector_search=False`` → ``FtsRetriever``（**非**语义路）。"""
    from astra_knowledge import (
        FtsRetriever,
        KnowledgeRetriever,
        SemanticRetriever,
        build_knowledge_retriever,
    )
    from astra_model import ModelRegistry, ModelRouter
    from astra_model.stub import StubModelProvider

    registry = ModelRegistry()
    registry.register("stub", StubModelProvider(dimension=8))
    retriever = build_knowledge_retriever(
        session_factory=session_factory,
        model_router=ModelRouter(registry),
        vector_search=False,
    )
    assert isinstance(retriever, KnowledgeRetriever)
    assert retriever.vector_search is False
    assert isinstance(retriever.backend, FtsRetriever)
    assert not isinstance(retriever.backend, SemanticRetriever)


def test_qa_w5_api_imports_knowledge_and_builds_services() -> None:
    """组合根实证：`astra_api` 能 import knowledge 真实实现（无 ModuleNotFoundError）。"""
    import astra_knowledge
    from astra_api.dependencies.services import build_app_services  # noqa: F401
    from astra_knowledge import KnowledgeRetriever, build_knowledge_retriever  # noqa: F401

    # 真实装配（经 Providers 之后）由 lifespan 覆盖；此处至少证伪 import / 装配符号缺失。
    assert hasattr(astra_knowledge, "build_knowledge_retriever")
    assert hasattr(astra_knowledge, "resolve_vector_search_capability")
    assert KnowledgeRetriever is not None


def test_qa_w5_composition_root_injects_real_retriever(client: Any) -> None:
    """组合根经 **真实 lifespan** 装配：runtime 注入**非 None** retriever（补 F28 型缺口）。

    仿 ``test_skill_resolver_wiring``：断言生产组合根
    （``build_app_services`` → ``AgentRuntime.build``）**实际注入**能力包真实实现，
    而非缺省 ``None``（否则生产知识段恒空）。
    """
    from astra_knowledge import KnowledgeRetriever

    runtime = client.app.state.services.runtime
    retriever = runtime.execution_manager._knowledge_retriever  # noqa: SLF001 - 装配接线断言
    assert retriever is not None, "组合根应注入 knowledge retriever（否则知识段恒空）"
    assert isinstance(retriever, KnowledgeRetriever)
    assert retriever.vector_search is False  # SQLite（local 模式）自动探测为 False


# -- 5. 索引任务韧性（parser 真实失败 + 重试计数） ---------------------------


def test_qa_w5_parser_failure_marks_failed(session_factory) -> None:
    """真实 **parser 失败**（非「原文不可得」）→ `document.status=FAILED` + `error` 落库。"""
    from astra_core import DomainError, ErrorCode
    from astra_knowledge import (
        Document,
        KnowledgeBase,
        KnowledgeIndexTask,
        SqlDocumentChunkRepository,
        SqlDocumentRepository,
        SqlEmbeddingRepository,
        SqlKnowledgeBaseRepository,
    )

    class _BoomRegistry:
        """解析即抛 ``DEPENDENCY_MISSING`` 的注册表替身（模拟 parser 失败）。"""

        def parse(self, data, *, mime, source_type, meta=None):  # noqa: ANN001, ANN201
            raise DomainError("boom parser", code=ErrorCode.DEPENDENCY_MISSING, data={"r": "p"})

    class _FakeStorage:
        def get(self, key: str) -> bytes:  # noqa: ANN201
            return b"content"

    kb = SqlKnowledgeBaseRepository(session_factory).add(
        KnowledgeBase(
            tenant_id="t1",
            name="kb-parser-fail",
            created_by="u1",
            status="ACTIVE",
            embedding_model={"provider": "stub", "model": "m", "dimensions": 8},
            chunk_config={"strategy": "fixed", "size": 800, "overlap": 100},
        )
    )
    document = SqlDocumentRepository(session_factory).add(
        Document(
            knowledge_base_id=kb.id,
            title="d",
            source_type="file",
            storage_key="k",
            status="PENDING",
        )
    )
    task = KnowledgeIndexTask(
        knowledge_base_repository=SqlKnowledgeBaseRepository(session_factory),
        document_repository=SqlDocumentRepository(session_factory),
        chunk_repository=SqlDocumentChunkRepository(session_factory),
        embedding_repository=SqlEmbeddingRepository(session_factory),
        storage=_FakeStorage(),
        vector_search=False,
        parser_registry=_BoomRegistry(),
    )
    with pytest.raises(DomainError):
        task.run(document.id)

    reloaded = SqlDocumentRepository(session_factory).get(document.id)
    assert reloaded is not None and reloaded.status == "FAILED"
    assert reloaded.error and "boom parser" in reloaded.error


def test_qa_w5_attempt_increments_even_on_runner_failure() -> None:
    """worker 处理器：runner 抛错时 `payload.attempt` **仍递增**（重试计数不丢，B9）。"""
    from astra_core import DomainError, ErrorCode
    from astra_worker import HandlerContext
    from astra_worker.tasks.knowledge_index import handle_knowledge_index

    def _boom(document_id: str) -> str:
        raise DomainError("index failed", code=ErrorCode.VALIDATION_ERROR, data={"r": "x"})

    message: dict[str, object] = {"payload": {"document_id": "doc-err"}}
    ctx = HandlerContext(providers=None, services={"knowledge_index": _boom})
    with pytest.raises(DomainError):
        handle_knowledge_index(message, ctx)
    assert message["payload"]["attempt"] == 1  # type: ignore[index]
