"""迁移 ``0008–0017`` **全量双向 roundtrip**（W10 / T2-53；``I-P2-20``）。

**目的**：单一测试覆盖整段 Phase 2 迁移带（``0008_phase2_skill`` … ``0017_phase2_evaluation``）
的**一次性双向**（``upgrade head → downgrade 0007 → upgrade head``）与跨迁移不变量——补既有
逐迁移测试（``test_0008.py`` … ``test_0017.py`` 各只覆盖自身迁移带）的**聚合缺口**。

覆盖（对齐 T2-53 预研缺口 G-1~G-8）：

- **G-1** 全链单次双向（本测试）；
- **G-2** 全波段对象**消失聚合断言**（十组表 union + SQLite FTS5 虚表）；
- **G-3** ``0009`` 僵尸 ``tool`` 行清理**动态**断言（``source='mcp'`` 消失 + 非 mcp 保留）；
- **G-4** ``0015`` ``task.idempotency_key`` 列 + 唯一索引回滚断言；
- **G-5** ``downgrade base → upgrade head``（全链至空库往返）；
- **G-7** 跨带回填幂等（降→升一次：``organization`` 行**不重复**、不回退）；
- **G-8** ``alembic check`` **CLI 门禁**（``subprocess`` 调 CLI，与 ``_assert_no_drift`` 独立）；
- **F（PG 门控）** ``extension vector`` 仍在 / HNSW 随降消失——**PG 动态面 = S-2**
  （本机无 PG，skip 并标注，借服务器复现，见 ``W10-服务器复现待办.md``）。

🔴 **纪律**：判「清理自有对象」读**源码字面量**（勿信 docstring）；**零漂移断言仅在上移 head 处**
   （head 元数据含后续表，中间版本断言会误判漂移——勿重演 W9 陈测试）。

覆盖口径：SQLite（本机必绿）；PostgreSQL（``ASTRA_TEST_PG_URL`` 门控）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 回滚切点 = ``0008`` 的 ``down_revision``（Phase 2 波段前一版）。
_REV_PRE_PHASE2 = "0007_phase1_task_execution_mode"
_REV_0015 = "0015_phase2_workspace_task"
_REV_0016 = "0016_phase2_organization_scope"

#: 本波段唯一 head（若后续新增迁移，须同步扩本文件波段）。
_EXPECTED_HEAD = "0017_phase2_evaluation"

#: 逐迁移**新建表**（G-2 聚合口径；``0016`` 不新建表）。
_PHASE2_TABLES_BY_REV: dict[str, set[str]] = {
    "0008": {"skill", "skill_version", "skill_resource", "agent_skill"},
    "0009": {"mcp_server", "mcp_tool", "mcp_permission"},
    "0010": {"resource_permission", "plugin", "approval"},
    "0011": {"model_provider_credential"},
    "0012": {
        "workflow",
        "workflow_version",
        "workflow_node",
        "workflow_edge",
        "workflow_run",
        "workflow_node_run",
    },
    "0013": {"knowledge_base", "document", "document_chunk", "embedding", "agent_knowledge"},
    "0014": {"memory", "memory_relation"},
    "0015": {"project", "workspace_environment", "task_execution", "schedule"},
    "0017": {"evaluation_dataset", "evaluation_case", "evaluation_run", "evaluation_result"},
}

#: 全波段新建表 union（G-2 聚合断言集合）。
_PHASE2_ALL_TABLES: set[str] = set().union(*_PHASE2_TABLES_BY_REV.values())

#: Phase 0/1 既有表（回滚 0007 后**须保留**的代表性子集）。
_PRESERVED_TABLES: set[str] = {
    "tenant",
    "user",
    "workspace",
    "agent",
    "tool",
    "task",
    "organization",
}

#: SQLite FTS5 虚表名（``0013`` 方言专属；回滚后须消失）。
_FTS_TABLE = "document_chunk_fts"

#: ``task.idempotency_key`` 唯一索引名（``0015`` 冻结契约）。
_TASK_IDEMPOTENCY_INDEX = "uq_task_idempotency_key"

#: 种入标识（SQLite 用例；UUIDv7 形状）。
_T = "00000000-0000-7000-8000-000000000001"
_U = "00000000-0000-7000-8000-000000000002"
_WS = "00000000-0000-7000-8000-000000000003"
_AGENT = "00000000-0000-7000-8000-000000000004"
_TASK_WS = "00000000-0000-7000-8000-000000000005"
_TASK_NOWS = "00000000-0000-7000-8000-000000000006"
_SKILL = "00000000-0000-7000-8000-000000000007"
_TOOL_BUILTIN = "00000000-0000-7000-8000-000000000008"
_TOOL_PLUGIN = "00000000-0000-7000-8000-000000000009"
_TOOL_MCP = "00000000-0000-7000-8000-00000000000d"

_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"
_CONNECT_TIMEOUT_SECONDS = 10


# -- Alembic / 引擎辅助 ------------------------------------------------------


def _alembic_config():  # noqa: ANN202 - alembic.Config
    from alembic.config import Config

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def _fresh_sqlite_url(tmp_dir: Path, filename: str) -> str:
    """构造隔离的 SQLite URL 并重置配置缓存。"""
    from astra_config.loader import reset_settings_cache

    url = f"sqlite:///{(tmp_dir / filename).as_posix()}"
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()
    return url


def _table_names(engine: Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def _columns(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(engine).get_columns(table)}


def _index_names(engine: Engine, table: str) -> set[str]:
    inspector = sa.inspect(engine)
    return {str(index["name"]) for index in inspector.get_indexes(table) if index.get("name")}


def _scalar(engine: Engine, sql: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(sa.text(sql), params).scalar_one()


def _tool_sources(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT DISTINCT source FROM tool")).scalars().all()
    return {str(row) for row in rows}


def _assert_no_drift(engine: Engine) -> None:
    """断言 ORM 元数据与 DB schema 零漂移（**过滤 FTS5 / HNSW 等 DB-only 对象**）。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from astra_database.base import Base

    from ._fts_filter import without_fts_artifacts

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    residual = without_fts_artifacts(diff)
    assert not residual, f"检测到 ORM/迁移漂移：{residual}"


def _run_alembic_check_cli() -> subprocess.CompletedProcess[str]:
    """**独立**经 ``python -m alembic check`` CLI 跑零漂移门禁（G-8）。"""
    return subprocess.run(  # noqa: S603 - 受控 argv（解释器 + 模块）
        [sys.executable, "-m", "alembic", "check"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_at_0015(engine: Engine) -> None:
    """在 ``0015`` 状态种入最小跨带业务行（供 ``0016`` 回填与 ``0009`` 行清理）。

    🔴 用**显式列清单**的裸 SQL（此时 ORM 已含 head 的 ``organization_id`` 列、DB 尚无，
    不可经 ORM 写入）。含一条 ``source='mcp'`` 的 ``tool`` 行（G-3 清理目标）与
    ``source='builtin'`` 的全局行（G-3 保留对照）。
    """
    tool_columns = (
        "id, tenant_id, name, display_name, description, category, source, "
        "input_schema, output_schema, requires_sandbox, status, tool_ref"
    )
    statements: list[tuple[str, dict[str, object]]] = [
        (
            "INSERT INTO tenant (id, name, slug, is_active) VALUES (:t, 'Default', 'default', 1)",
            {"t": _T},
        ),
        (
            "INSERT INTO user (id, tenant_id, username, email, password_hash, is_active, "
            "is_superuser) VALUES (:u, :t, 'admin', 'admin@example.io', 'x', 1, 1)",
            {"u": _U, "t": _T},
        ),
        (
            "INSERT INTO workspace (id, tenant_id, owner_id, name, workspace_type) "
            "VALUES (:ws, :t, :u, 'W', 'personal')",
            {"ws": _WS, "t": _T, "u": _U},
        ),
        (
            "INSERT INTO agent (id, tenant_id, workspace_id, name, description, type, status, "
            "current_version_id, created_by) "
            "VALUES (:a, :t, :ws, 'A', NULL, 'PRIMARY', 'ACTIVE', NULL, :u)",
            {"a": _AGENT, "t": _T, "ws": _WS, "u": _U},
        ),
        (
            "INSERT INTO task (id, tenant_id, workspace_id, type, status, priority, "
            "execution_mode, payload, result, idempotency_key) "
            "VALUES (:tk, :t, :ws, 'demo', 'CREATED', 0, 'INLINE', NULL, NULL, NULL)",
            {"tk": _TASK_WS, "t": _T, "ws": _WS},
        ),
        (
            "INSERT INTO task (id, tenant_id, workspace_id, type, status, priority, "
            "execution_mode, payload, result, idempotency_key) "
            "VALUES (:tk, :t, NULL, 'demo', 'CREATED', 0, 'INLINE', NULL, NULL, NULL)",
            {"tk": _TASK_NOWS, "t": _T},
        ),
        (
            "INSERT INTO skill (id, tenant_id, name, display_name, description, category, status, "
            "current_version_id, created_by) "
            "VALUES (:sk, :t, 'S', 'S', NULL, 'cat', 'ACTIVE', NULL, :u)",
            {"sk": _SKILL, "t": _T, "u": _U},
        ),
        (
            f"INSERT INTO tool ({tool_columns}) VALUES (:tb, NULL, 'filesystem', 'FS', NULL, "
            "'builtin', 'builtin', NULL, NULL, 0, 'ACTIVE', NULL)",
            {"tb": _TOOL_BUILTIN},
        ),
        (
            f"INSERT INTO tool ({tool_columns}) VALUES (:tp, :t, 'my_tool', 'My', NULL, "
            "'custom', 'plugin', NULL, NULL, 0, 'ACTIVE', NULL)",
            {"tp": _TOOL_PLUGIN, "t": _T},
        ),
        (
            f"INSERT INTO tool ({tool_columns}) VALUES (:tm, :t, 'mcp.echo', 'MCP', NULL, "
            "'custom', 'mcp', NULL, NULL, 0, 'ACTIVE', NULL)",
            {"tm": _TOOL_MCP, "t": _T},
        ),
        (
            "INSERT INTO project (id, tenant_id, organization_id, workspace_id, name, description, "
            "repo_url, default_branch, settings, created_by) "
            "VALUES (:pj, :t, NULL, :ws, 'P', NULL, NULL, NULL, NULL, :u)",
            {"pj": "00000000-0000-7000-8000-00000000000a", "t": _T, "ws": _WS, "u": _U},
        ),
    ]
    with engine.begin() as connection:
        for sql, params in statements:
            connection.execute(sa.text(sql), params)


def _assert_phase2_tables_absent(tables: set[str]) -> None:
    """G-2：全波段新建表 + SQLite FTS5 虚表均**不存在**。"""
    present = _PHASE2_ALL_TABLES & tables
    assert not present, f"回滚 0007 后仍存在 Phase 2 波段表：{sorted(present)}"
    fts_present = {name for name in tables if name.startswith(_FTS_TABLE)}
    assert not fts_present, f"回滚 0007 后仍存在 FTS5 虚表 / 影子对象：{sorted(fts_present)}"


# -- 用例 1：全链单次双向（G-1 / G-2 / G-3 / G-4 / G-7） ----------------------


def test_migration_0008_to_0017_full_chain_roundtrip(tmp_path: Path) -> None:
    """``0015 播种 → upgrade head → check → downgrade 0007 → 断言 → upgrade head → check``。"""
    from alembic import command
    from alembic.script import ScriptDirectory
    from astra_config.loader import reset_settings_cache

    url = _fresh_sqlite_url(tmp_path, "phase2c_roundtrip.db")
    config = _alembic_config()

    # 单 head 线性（band head = 0017）。
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"迁移链应为单 head：{heads}"
    assert heads == [_EXPECTED_HEAD], heads

    try:
        # -- Phase A：升 0015 并播种（cross-band 行 + mcp tool 行）-----------
        command.upgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            _seed_at_0015(engine)
        finally:
            engine.dispose()

        # -- Phase B：升 head + 零漂移 -------------------------------------
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = _table_names(engine)
            assert _PHASE2_ALL_TABLES.issubset(tables), _PHASE2_ALL_TABLES - tables
            _assert_no_drift(engine)
            # G-4 前置：idempotency_key 列 + 唯一索引存在。
            assert "idempotency_key" in _columns(engine, "task")
            assert _TASK_IDEMPOTENCY_INDEX in _index_names(engine, "task")
            # G-3 前置：mcp tool 行存在。
            assert "mcp" in _tool_sources(engine)
            # G-7 基线：0016 S2 为 tenant 建 1 条默认组织。
            org_before = int(_scalar(engine, "SELECT count(*) FROM organization"))
            assert org_before == 1, org_before
        finally:
            engine.dispose()

        # -- Phase C/D：回滚 0007 + 断言 -----------------------------------
        command.downgrade(config, _REV_PRE_PHASE2)
        engine = sa.create_engine(url)
        try:
            tables = _table_names(engine)
            # G-2：全波段对象消失（含 FTS5 虚表）。
            _assert_phase2_tables_absent(tables)
            # 既有表保留。
            assert _PRESERVED_TABLES.issubset(tables), _PRESERVED_TABLES - tables
            # G-3：mcp 行消失，非 mcp 行保留。
            sources = _tool_sources(engine)
            assert "mcp" not in sources, sources
            assert {"builtin", "plugin"}.issubset(sources), sources
            # G-4：task.idempotency_key 列 + 唯一索引消失。
            assert "idempotency_key" not in _columns(engine, "task")
            assert _TASK_IDEMPOTENCY_INDEX not in _index_names(engine, "task")
            # G-7：organization 行**不删**（0016 downgrade 仅移除列/索引）。
            assert int(_scalar(engine, "SELECT count(*) FROM organization")) == org_before
        finally:
            engine.dispose()

        # -- Phase E：再升 head + 零漂移（往返干净）+ G-7 回填幂等 -----------
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = _table_names(engine)
            assert _PHASE2_ALL_TABLES.issubset(tables), _PHASE2_ALL_TABLES - tables
            _assert_no_drift(engine)
            # G-7：默认组织**不重复**（S2 幂等）。
            assert int(_scalar(engine, "SELECT count(*) FROM organization")) == org_before
            # G-4 往返：列 + 索引回归。
            assert "idempotency_key" in _columns(engine, "task")
            assert _TASK_IDEMPOTENCY_INDEX in _index_names(engine, "task")
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


# -- 用例 2：G-8 独立 CLI 门禁 ----------------------------------------------


def test_migration_0008_to_0017_alembic_check_cli(tmp_path: Path) -> None:
    """G-8：``python -m alembic check`` CLI（**独立**于 ``_assert_no_drift``）在 head 处零漂移。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    # 构造隔离 SQLite 并置入环境（CLI 经环境变量读取同一 DB）。
    _fresh_sqlite_url(tmp_path, "phase2c_cli_check.db")
    config = _alembic_config()

    try:
        command.upgrade(config, "head")
        result = _run_alembic_check_cli()
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "No new upgrade operations detected" in combined, combined
    finally:
        reset_settings_cache()


# -- 用例 3：G-5 全链至空库往返 ----------------------------------------------


def test_migration_full_chain_downgrade_base_roundtrip(tmp_path: Path) -> None:
    """G-5：``upgrade head → downgrade base（至空库）→ upgrade head`` 往返干净。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    url = _fresh_sqlite_url(tmp_path, "phase2c_base_roundtrip.db")
    config = _alembic_config()

    try:
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert _PHASE2_ALL_TABLES.issubset(_table_names(engine))
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        # 降 base：业务表全消失（仅 alembic_version 元数据表可留）。
        command.downgrade(config, "base")
        engine = sa.create_engine(url)
        try:
            tables = _table_names(engine)
            assert "tenant" not in tables and "skill" not in tables, tables
            assert not (_PHASE2_ALL_TABLES & tables), _PHASE2_ALL_TABLES & tables
        finally:
            engine.dispose()

        # 再升 head：零漂移。
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            assert _PHASE2_ALL_TABLES.issubset(_table_names(engine))
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


# -- 用例 4：F（PG 门控 · 动态面 = S-2） --------------------------------------


def _resolve_pg_url() -> str:
    if not _PG_URL:
        if _REQUIRE_PG:
            pytest.fail("ASTRA_TEST_REQUIRE_PG=1 但未设置 ASTRA_TEST_PG_URL —— PG 冒烟不得跳过。")
        pytest.skip("未设置 ASTRA_TEST_PG_URL（PG 全链双向 = S-2，借服务器复现）。")
    return _PG_URL


@pytest.mark.skipif(
    _PG_URL is None and not _REQUIRE_PG,
    reason="未配置 ASTRA_TEST_PG_URL（PG 全链双向 + extension vector 动态面 = S-2）",
)
def test_migration_0008_to_0017_roundtrip_postgres() -> None:  # pragma: no cover - PG 门控
    """PG（权威方言）：全链双向 + ``extension vector`` 动态面（= S-2）。

    链路：``upgrade head → check → downgrade 0007 → 断言 → upgrade head → check``。

    🔴 **动态面 = S-2**：本机无 PG（无 Docker / 无 psql）→ 借内网服务器复现；
       断言 ``SELECT extname FROM pg_extension WHERE extname='vector'`` 在回滚后仍为 1 行
       （**严禁 ``DROP EXTENSION vector``**，QA-31）。
    """
    url = _resolve_pg_url()

    from astra_config.loader import reset_settings_cache

    os.environ["ASTRA_MODE"] = "server"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)
    reset_settings_cache()

    try:
        probe = sa.create_engine(url)
        try:
            with probe.connect() as connection:
                connection.execute(sa.text("SELECT 1"))
        except SQLAlchemyError as exc:
            if _REQUIRE_PG:
                pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法连接 PostgreSQL：{exc}")
            pytest.skip(f"无法连接 PostgreSQL：{exc}")
        finally:
            probe.dispose()

        from alembic import command

        config = _alembic_config()
        try:
            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                assert _PHASE2_ALL_TABLES.issubset(_table_names(engine))
                _assert_no_drift(engine)
            finally:
                engine.dispose()

            command.downgrade(config, _REV_PRE_PHASE2)
            engine = sa.create_engine(url)
            try:
                tables = _table_names(engine)
                _assert_phase2_tables_absent(tables)
                # F / S-2：extension vector 仍在（严禁 DROP EXTENSION）。
                vector_rows = int(
                    _scalar(
                        engine,
                        "SELECT count(*) FROM pg_extension WHERE extname = 'vector'",
                    )
                )
                assert vector_rows == 1, "回滚 0007 后 extension vector 丢失（QA-31 违规）"
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, "base")
    finally:
        reset_settings_cache()
