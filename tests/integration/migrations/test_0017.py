"""迁移 ``0017_phase2_evaluation`` 集成测试（W9 / T2-45）。

覆盖（W9 开工前架构裁定 §3 / §9；验收 ``I-P2-20``）：

- **单 head**：``0017`` 的 ``down_revision == 0016``，且位于迁移链**唯一 head 的祖先链**上
  （``0018`` 加入后 head 前移至 ``0018``，R-R1R5-10 D-1 预修：**加性收紧、零放宽**）；
- **双向（SQLite）**：``upgrade 0016`` → ``upgrade 0017``（断言四表 + 唯一键
  ``(dataset_id, case_key)`` / ``idempotency_key`` / ``(evaluation_run_id, case_id)`` + FK +
  组织 / 工作区索引）→ ``downgrade 0016``（断言四表已删、既有表**未动**）→ ``upgrade 0017``；
- **零漂移**：``0017`` 四表结构断言 + **head 处** ORM ``Base.metadata`` 与 DB schema 零漂移
  （``0018`` 加入后 head 前移；中间版本断言会误判漂移，替代 PG 权威面）；
- **负向对照**：同 ``(dataset_id, case_key)`` 二插 → ``IntegrityError``（防假绿）；
- **组织范围（R3）**：``evaluation_dataset`` / ``evaluation_run`` 直接列
  ``organization_id``（+ 索引）；``evaluation_case`` / ``evaluation_result`` **无**组织列；
- **静态**：``downgrade`` 源码不含 ``DROP EXTENSION vector``；``upgrade`` 显式读方言；
- PostgreSQL：同链路，受 ``ASTRA_TEST_PG_URL`` 门控（本机无 PG → 不虚报通过）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[3]

_REV_0016 = "0016_phase2_organization_scope"
_REV_0017 = "0017_phase2_evaluation"
_REV_0018 = "0018_phase2_remote_workspace"

#: 本迁移自有四表。
EVAL_TABLES: tuple[str, ...] = (
    "evaluation_dataset",
    "evaluation_case",
    "evaluation_run",
    "evaluation_result",
)

#: 直接列 ``organization_id`` / ``workspace_id`` 的 L1 表（R3）。
ORG_WS_TABLES: tuple[str, ...] = ("evaluation_dataset", "evaluation_run")

#: 子资源（经父推导；**无**组织 / 工作区列）。
DERIVED_TABLES: tuple[str, ...] = ("evaluation_case", "evaluation_result")

#: 既有表（downgrade 后必须仍在——「不动任何既有表」）。
PRESERVED_TABLES: tuple[str, ...] = ("agent", "memory", "workspace", "organization", "tenant")

_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"
_CONNECT_TIMEOUT_SECONDS = 10

# 种入标识。
_T = "00000000-0000-7000-8000-000000000101"
_U = "00000000-0000-7000-8000-000000000102"
_DS = "00000000-0000-7000-8000-000000000103"
_CASE_A = "00000000-0000-7000-8000-000000000104"
_CASE_B = "00000000-0000-7000-8000-000000000105"


def _alembic_config():
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


def _unique_constraints(engine: Engine, table: str) -> dict[str, set[str]]:
    inspector = sa.inspect(engine)
    result: dict[str, set[str]] = {}
    for constraint in inspector.get_unique_constraints(table):
        name = constraint.get("name")
        if name:
            result[str(name)] = {str(col) for col in (constraint.get("column_names") or [])}
    return result


def _fk_referred_tables(engine: Engine, table: str) -> set[str]:
    inspector = sa.inspect(engine)
    return {
        str(fk["referred_table"])
        for fk in inspector.get_foreign_keys(table)
        if fk.get("referred_table")
    }


def _assert_no_drift(engine: Engine) -> None:
    """断言 ORM 元数据与 DB schema 零漂移（**过滤 FTS5 虚表 / 影子对象**）。"""
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


def _seed_dataset(engine: Engine) -> None:
    """在 ``0017`` 后种入最小租户 / 用户 / 任务集（供唯一键负向对照）。"""
    statements: list[tuple[str, dict[str, object]]] = [
        (
            "INSERT INTO tenant (id, name, slug, is_active) VALUES (:t, 'Default', 'default', 1)",
            {"t": _T},
        ),
        (
            "INSERT INTO user (id, tenant_id, username, email, password_hash, is_active, "
            "is_superuser) VALUES (:u, :t, 'eval', 'eval@example.io', 'x', 1, 1)",
            {"u": _U, "t": _T},
        ),
        (
            "INSERT INTO evaluation_dataset (id, tenant_id, organization_id, workspace_id, name, "
            "version, parent_dataset_id, status, description, created_by) "
            "VALUES (:ds, :t, NULL, NULL, 'DS', 1, NULL, 'DRAFT', NULL, :u)",
            {"ds": _DS, "t": _T, "u": _U},
        ),
    ]
    with engine.begin() as connection:
        for sql, params in statements:
            connection.execute(sa.text(sql), params)


def _insert_case(engine: Engine, case_id: str, case_key: str) -> None:
    """插入一条 ``evaluation_case``（供唯一键对照）。"""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO evaluation_case (id, dataset_id, case_key, input, expected, "
                "assertions, tags, position) "
                "VALUES (:id, :ds, :key, '{}', NULL, NULL, NULL, 0)"
            ),
            {"id": case_id, "ds": _DS, "key": case_key},
        )


def test_migration_0017_single_head() -> None:
    """``0017`` 的 ``down_revision == 0016``，且位于迁移链**唯一 head 的祖先链**上。

    🔴 ``0018_phase2_remote_workspace``（R2 / T2-57）加入后波段 head 前移——本断言
    （R-R1R5-10 D-1 预修）改为「**单 head** + ``0017`` 在祖先链 + 相邻下行关系」，
    **加性收紧、零放宽**（不再硬编 ``0017`` 为 head）。
    """
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(_alembic_config())
    heads = scripts.get_heads()
    assert len(heads) == 1, f"迁移链应为单 head：{heads}"
    head = heads[0]
    ancestors = {revision.revision for revision in scripts.walk_revisions(head=head, base="base")}
    assert _REV_0017 in ancestors, ancestors
    assert scripts.get_revision(_REV_0017).down_revision == _REV_0016
    # ``0017`` 的直接后继（波段终点 = ``0018``）下行关系锁定。
    assert scripts.get_revision(_REV_0018).down_revision == _REV_0017


def test_migration_0017_bidirectional_and_constraints_sqlite() -> None:
    """0016 → upgrade 0017（四表 + 唯一键 + FK + 索引）→ 上移 head 零漂移 →
    downgrade 0016 → 再 upgrade head。

    🔴 **R-R1R5-10 同步（0018 加入后 head 前移）**：零漂移断言**仅在 head 处有效**
    （ORM 元数据 = head，含 ``0018`` 加性列；中间版本断言会误判漂移）——本用例将结构性
    断言留在 ``0017``，零漂移断言上移至 ``head``（**加性收紧、零放宽**）。
    """
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_eval.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0016)
        command.upgrade(config, _REV_0017)
        engine = sa.create_engine(url)
        try:
            tables = _table_names(engine)
            for table in EVAL_TABLES:
                assert table in tables, table

            # 组织 / 工作区直接列（R3）。
            for table in ORG_WS_TABLES:
                columns = _columns(engine, table)
                assert "organization_id" in columns, table
                assert "workspace_id" in columns, table
                assert f"ix_{table}_organization_id" in _index_names(engine, table), table
                assert f"ix_{table}_workspace_id" in _index_names(engine, table), table
                assert {"tenant", "organization", "workspace"} <= _fk_referred_tables(engine, table)

            # 子资源经父推导（无组织 / 工作区列）。
            for table in DERIVED_TABLES:
                columns = _columns(engine, table)
                assert "organization_id" not in columns, table
                assert "workspace_id" not in columns, table

            # 唯一键。
            case_uq = _unique_constraints(engine, "evaluation_case")
            assert case_uq.get("uq_evaluation_case_dataset_case_key") == {
                "dataset_id",
                "case_key",
            }, case_uq
            run_uq = _unique_constraints(engine, "evaluation_run")
            assert run_uq.get("uq_evaluation_run_idempotency_key") == {"idempotency_key"}, run_uq
            result_uq = _unique_constraints(engine, "evaluation_result")
            assert result_uq.get("uq_evaluation_result_run_case") == {
                "evaluation_run_id",
                "case_id",
            }, result_uq

            # FK 拓扑（单向无环）。
            assert "evaluation_dataset" in _fk_referred_tables(engine, "evaluation_case")
            assert {"evaluation_run", "evaluation_case", "agent_run"} <= _fk_referred_tables(
                engine, "evaluation_result"
            )
            assert {"evaluation_dataset", "agent", "agent_version"} <= _fk_referred_tables(
                engine, "evaluation_run"
            )
            assert "evaluation_dataset" in _fk_referred_tables(engine, "evaluation_dataset")

            # 负向对照：同 (dataset_id, case_key) 二插 → IntegrityError。
            _seed_dataset(engine)
            _insert_case(engine, _CASE_A, "duplicate-key")
            with pytest.raises(IntegrityError):
                _insert_case(engine, _CASE_B, "duplicate-key")
        finally:
            engine.dispose()

        # 零漂移：上移 head（``0018``）后断言（仅 head 处 ORM 元数据与 DB 一致）。
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            for table in EVAL_TABLES:
                assert table in _table_names(engine), table
            _assert_no_drift(engine)
        finally:
            engine.dispose()

        # downgrade 0016：四表已删、既有表未动。
        command.downgrade(config, _REV_0016)
        engine = sa.create_engine(url)
        try:
            tables = _table_names(engine)
            for table in EVAL_TABLES:
                assert table not in tables, table
            for table in PRESERVED_TABLES:
                assert table in tables, table
        finally:
            engine.dispose()

        # 再 upgrade head：幂等 + 零漂移。
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            tables = _table_names(engine)
            for table in EVAL_TABLES:
                assert table in tables, table
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0017_idempotency_key_nullable_unique_sqlite() -> None:
    """``idempotency_key`` 为**可空唯一**：多个 NULL 可共存，非空重复 → ``IntegrityError``。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_eval_idem.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0017)
        engine = sa.create_engine(url)
        try:
            _seed_dataset(engine)
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO agent (id, tenant_id, workspace_id, name, description, type, "
                        "status, current_version_id, created_by) "
                        "VALUES (:a, :t, NULL, 'A', NULL, 'PRIMARY', 'ACTIVE', NULL, :u)"
                    ),
                    {"a": "00000000-0000-7000-8000-000000000201", "t": _T, "u": _U},
                )
        finally:
            engine.dispose()

        # SQLite 表级检查：agent_version 需先建（FK 未强制，SQLite 默认关闭）。
        engine = sa.create_engine(url)
        try:

            def _insert_run(run_id: str, key: object) -> None:
                with engine.begin() as connection:
                    connection.execute(
                        sa.text(
                            "INSERT INTO evaluation_run (id, tenant_id, organization_id, "
                            "workspace_id, dataset_id, agent_id, agent_version_id, status, "
                            "idempotency_key, started_at, completed_at, summary, created_by) "
                            "VALUES (:id, :t, NULL, NULL, :ds, :a, :av, 'SUCCESS', :key, "
                            "NULL, NULL, NULL, :u)"
                        ),
                        {
                            "id": run_id,
                            "t": _T,
                            "ds": _DS,
                            "a": "00000000-0000-7000-8000-000000000201",
                            "av": "00000000-0000-7000-8000-000000000202",
                            "key": key,
                            "u": _U,
                        },
                    )

            # 多个 NULL 可共存（可空唯一）。
            _insert_run("00000000-0000-7000-8000-000000000301", None)
            _insert_run("00000000-0000-7000-8000-000000000302", None)
            # 非空重复 → IntegrityError。
            _insert_run("00000000-0000-7000-8000-000000000303", "k-1")
            with pytest.raises(IntegrityError):
                _insert_run("00000000-0000-7000-8000-000000000304", "k-1")
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0017_no_drop_extension_vector_and_explicit_dialect() -> None:
    """🔴 ``downgrade`` **可执行 SQL** 不得 ``DROP EXTENSION vector``；``upgrade`` 显式读方言。"""
    import ast

    source = (REPO_ROOT / "migrations" / "versions" / "0017_phase2_evaluation.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    sql_texts: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"execute", "exec_driver_sql"}:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                sql_texts.append(arg.value)
    dropped = [text for text in sql_texts if "drop extension" in text.lower()]
    assert not dropped, f"0017 迁移可执行 SQL 含 DROP EXTENSION：{dropped}"
    assert "op.get_bind().dialect.name" in source


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_migration_0017_postgres() -> None:
    """PostgreSQL（权威方言）：upgrade head → 零漂移 → downgrade 0016 → upgrade head。

    🔴 **R-R1R5-10 同步**：零漂移断言仅在 **head**（``0018``）处有效（ORM 元数据含 ``0018``
    加性列）；故 PG 链路亦上移至 ``head`` 断言。
    """
    assert _PG_URL is not None
    url = _PG_URL
    os.environ["ASTRA_MODE"] = "local"
    os.environ["ASTRA_DATABASE_URL"] = url
    os.environ.pop("ASTRA_CONFIG_FILE", None)

    from alembic import command
    from astra_config.loader import reset_settings_cache

    reset_settings_cache()
    config = _alembic_config()
    try:
        engine = sa.create_engine(url, connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS})
        try:
            with engine.connect():
                pass
        except SQLAlchemyError:  # pragma: no cover - 环境不可达
            pytest.skip(f"PostgreSQL 不可达：{url}")
        finally:
            engine.dispose()

        try:
            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                for table in EVAL_TABLES:
                    assert table in _table_names(engine), table
                _assert_no_drift(engine)
            finally:
                engine.dispose()

            command.downgrade(config, _REV_0016)
            engine = sa.create_engine(url)
            try:
                for table in EVAL_TABLES:
                    assert table not in _table_names(engine), table
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, _REV_0016)
    finally:
        reset_settings_cache()
