"""迁移 ``0018_phase2_remote_workspace`` 集成测试（R2 / T2-57）。

覆盖（裁定 R-R1R5-08 / -09 / -10；验收 ``I-P2-20`` / ``I-P2-36`` / ``I-P2-38``）：

- **单 head**：``0018`` 的 ``down_revision == 0017``，且为唯一 head（``0017`` 在祖先链上）；
- **双向（SQLite）**：``upgrade 0017`` → ``upgrade 0018``（断言 8 列 + ``project_id`` FK +
  2 索引 + **既有** ``uq_task_execution_task_attempt`` 仍在 + 零漂移）→ ``downgrade 0017``
  （断言 8 列 / 2 索引已删，``uq_task_execution_task_attempt`` **仍在**，既有基础列未动）→
  ``upgrade 0018``（幂等 + 零漂移）；
- **零漂移**：``0018`` 后 ORM ``Base.metadata`` 与 DB schema 零漂移（替代 PG 权威面）；
- **``checkout_ref`` 非空部分唯一（§8.1 / §8.3）**：多个 ``NULL`` 可共存，非空重复 →
  ``IntegrityError``；
- **A-15 查重中止（§8.2 / §8.3 / R-R1R5-09）**：``(task_id, attempt)`` 命中重复组 →
  ``0018.upgrade()`` **中止**（``RuntimeError``，不自动去重）；干净库 → 通过；
- **§08.2 校正**：``0018`` 源码**不含**对 ``uq_task_execution_task_attempt`` 的再次创建 /
  回滚删除；
- **静态**：``downgrade`` 源码不含 ``DROP EXTENSION vector``；``upgrade`` 显式读方言；
- PostgreSQL：同链路 + ``alembic check``，受 ``ASTRA_TEST_PG_URL`` 门控（本机无 PG → 不虚报）。

🔴 判「清理自有对象」读**源码字面量**（勿信 docstring）；**零漂移断言仅在上移 head 处**。
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

_MIGRATION_REL = "migrations/versions/0018_phase2_remote_workspace.py"

_REV_0017 = "0017_phase2_evaluation"
_REV_0018 = "0018_phase2_remote_workspace"

#: ``0018`` 新增的 8 个可空列。
ADDED_COLUMNS: tuple[str, ...] = (
    "project_id",
    "checkout_ref",
    "base_commit",
    "result_commit",
    "environment_digest",
    "artifact_refs",
    "heartbeat_at",
    "lease_expires_at",
)

#: ``task_execution`` 既有基础列（``0015`` 建；``0018`` 后须仍在）。
BASE_COLUMNS: tuple[str, ...] = (
    "id",
    "task_id",
    "attempt",
    "worker_id",
    "status",
    "started_at",
    "finished_at",
    "duration_ms",
    "error",
)

#: ``0018`` 新增索引名。
ADDED_INDEXES: tuple[str, ...] = (
    "ix_task_execution_project_started",
    "uq_task_execution_checkout_ref",
)

#: ``0015`` 建的唯一约束（§08.2：``0018`` 不得重复创建 / 回滚删除）。
_TASK_ATTEMPT_UQ = "uq_task_execution_task_attempt"

_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"
_CONNECT_TIMEOUT_SECONDS = 10

# 种入标识。
_T = "00000000-0000-7000-8000-000000000201"
_U = "00000000-0000-7000-8000-000000000202"
_WS = "00000000-0000-7000-8000-000000000203"
_TASK = "00000000-0000-7000-8000-000000000204"
_PROJECT = "00000000-0000-7000-8000-000000000205"
_EXEC_A = "00000000-0000-7000-8000-000000000206"
_EXEC_B = "00000000-0000-7000-8000-000000000207"
_EXEC_C = "00000000-0000-7000-8000-000000000208"
_EXEC_D = "00000000-0000-7000-8000-000000000209"


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


def _seed_task(engine: Engine) -> None:
    """在 ``0018`` 后种入最小租户 / 用户 / 工作区 / Project / Task（供 FK / 唯一键对照）。"""
    statements: list[tuple[str, dict[str, object]]] = [
        (
            "INSERT INTO tenant (id, name, slug, is_active) VALUES (:t, 'Default', 'default', 1)",
            {"t": _T},
        ),
        (
            "INSERT INTO user (id, tenant_id, username, email, password_hash, is_active, "
            "is_superuser) VALUES (:u, :t, 'rw', 'rw@example.io', 'x', 1, 1)",
            {"u": _U, "t": _T},
        ),
        (
            "INSERT INTO workspace (id, tenant_id, owner_id, name, workspace_type) "
            "VALUES (:ws, :t, :u, 'W', 'personal')",
            {"ws": _WS, "t": _T, "u": _U},
        ),
        (
            "INSERT INTO project (id, tenant_id, organization_id, workspace_id, name, description, "
            "repo_url, default_branch, settings, created_by) "
            "VALUES (:pj, :t, NULL, :ws, 'P', NULL, NULL, NULL, NULL, :u)",
            {"pj": _PROJECT, "t": _T, "ws": _WS, "u": _U},
        ),
        (
            "INSERT INTO task (id, tenant_id, workspace_id, type, status, priority, "
            "execution_mode, payload, result, idempotency_key) "
            "VALUES (:tk, :t, :ws, 'demo', 'CREATED', 0, 'INLINE', NULL, NULL, NULL)",
            {"tk": _TASK, "t": _T, "ws": _WS},
        ),
    ]
    with engine.begin() as connection:
        for sql, params in statements:
            connection.execute(sa.text(sql), params)


def _insert_execution(engine: Engine, exec_id: str, attempt: int, checkout_ref: object) -> None:
    """插入一条 ``task_execution``（供 ``checkout_ref`` 部分唯一对照）。"""
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO task_execution (id, task_id, attempt, status, checkout_ref) "
                "VALUES (:id, :task, :attempt, 'RUNNING', :ref)"
            ),
            {"id": exec_id, "task": _TASK, "attempt": attempt, "ref": checkout_ref},
        )


def test_migration_0018_single_head() -> None:
    """``0018`` 的 ``down_revision == 0017``，且为唯一 head（``0017`` 在祖先链上）。"""
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(_alembic_config())
    heads = scripts.get_heads()
    assert len(heads) == 1, f"迁移链应为单 head：{heads}"
    assert heads == [_REV_0018], heads
    assert scripts.get_revision(_REV_0018).down_revision == _REV_0017
    ancestors = {
        revision.revision for revision in scripts.walk_revisions(head=heads[0], base="base")
    }
    assert _REV_0018 in ancestors and _REV_0017 in ancestors, ancestors


def test_migration_0018_bidirectional_and_constraints_sqlite() -> None:
    """0017 → upgrade 0018（8 列 + FK + 2 索引 + 既有唯一约束 + 零漂移）→ downgrade 0017 →
    再 upgrade。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_rw.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0017)
        command.upgrade(config, _REV_0018)
        engine = sa.create_engine(url)
        try:
            columns = _columns(engine, "task_execution")
            for column in ADDED_COLUMNS:
                assert column in columns, column
            for column in BASE_COLUMNS:
                assert column in columns, column

            indexes = _index_names(engine, "task_execution")
            for index in ADDED_INDEXES:
                assert index in indexes, index

            # §08.2：既有 ``uq_task_execution_task_attempt`` 仍在（本迁移不重复创建）。
            uq = _unique_constraints(engine, "task_execution")
            assert uq.get(_TASK_ATTEMPT_UQ) == {"task_id", "attempt"}, uq

            # ``project_id`` → ``project`` FK 存在。
            assert "project" in _fk_referred_tables(engine, "task_execution")

            _assert_no_drift(engine)
        finally:
            engine.dispose()

        # downgrade 0017：8 列 + 2 索引已删；既有唯一约束 / 基础列未动。
        command.downgrade(config, _REV_0017)
        engine = sa.create_engine(url)
        try:
            columns = _columns(engine, "task_execution")
            for column in ADDED_COLUMNS:
                assert column not in columns, column
            for column in BASE_COLUMNS:
                assert column in columns, column
            indexes = _index_names(engine, "task_execution")
            for index in ADDED_INDEXES:
                assert index not in indexes, index
            # §08.2：``uq_task_execution_task_attempt`` **不得**被本迁移 drop。
            uq = _unique_constraints(engine, "task_execution")
            assert uq.get(_TASK_ATTEMPT_UQ) == {"task_id", "attempt"}, uq
        finally:
            engine.dispose()

        # 再 upgrade 0018：幂等 + 零漂移。
        command.upgrade(config, _REV_0018)
        engine = sa.create_engine(url)
        try:
            columns = _columns(engine, "task_execution")
            for column in ADDED_COLUMNS:
                assert column in columns, column
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0018_checkout_ref_partial_unique_sqlite() -> None:
    """``checkout_ref`` 为**非空**部分唯一：多个 ``NULL`` 可共存，非空重复 → ``IntegrityError``。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_rw_ckref.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0018)
        engine = sa.create_engine(url)
        try:
            _seed_task(engine)
            # 多个 NULL 可共存（部分唯一索引 WHERE checkout_ref IS NOT NULL）。
            _insert_execution(engine, _EXEC_A, 1, None)
            _insert_execution(engine, _EXEC_B, 2, None)
            # 非空唯一值可插入。
            _insert_execution(engine, _EXEC_C, 3, "wr_ref-1")
            # 非空重复 → IntegrityError。
            with pytest.raises(IntegrityError):
                _insert_execution(engine, _EXEC_D, 4, "wr_ref-1")
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0018_duplicate_attempt_guard_abort_sqlite() -> None:
    """A-15：``(task_id, attempt)`` 命中重复组 → ``0018.upgrade()`` **中止**（不自动去重）。

    构造既有 ``task_execution``（**无**唯一约束、含重复 ``(task_id, attempt)``）并把库 stamp 在
    ``0017``，再 ``upgrade`` 到 ``0018`` → 迁移首部查重命中，抛 ``RuntimeError``。
    """
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_rw_dup.db")
    config = _alembic_config()
    try:
        engine = sa.create_engine(url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "CREATE TABLE task_execution ("
                        "id VARCHAR(36) PRIMARY KEY, task_id VARCHAR(36), attempt INTEGER, "
                        "status VARCHAR(50))"
                    )
                )
                connection.execute(sa.text("CREATE TABLE task (id VARCHAR(36) PRIMARY KEY)"))
                connection.execute(sa.text("CREATE TABLE project (id VARCHAR(36) PRIMARY KEY)"))
                connection.execute(
                    sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                )
                connection.execute(
                    sa.text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                    {"rev": _REV_0017},
                )
                # 两条重复 ``(task_id, attempt)``。
                connection.execute(
                    sa.text(
                        "INSERT INTO task_execution (id, task_id, attempt, status) "
                        "VALUES ('e1', 't1', 1, 'RUNNING'), ('e2', 't1', 1, 'SUCCEEDED')"
                    )
                )
        finally:
            engine.dispose()

        with pytest.raises(RuntimeError, match="0018 迁移中止"):
            command.upgrade(config, _REV_0018)

        # 迁移中止后库仍留在 0017（无部分应用）。
        engine = sa.create_engine(url)
        try:
            assert "task_execution" in _table_names(engine)
            with engine.connect() as connection:
                current = connection.execute(
                    sa.text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            assert current == _REV_0017, current
            assert "project_id" not in _columns(engine, "task_execution")
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0018_duplicate_guard_helper_clean_and_hit() -> None:
    """``_duplicate_attempt_groups`` 直测：干净表 → 空；含重复 → 命中分组（纯查询、无副作用）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("mig_0018", REPO_ROOT / _MIGRATION_REL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tmp_dir = Path(tempfile.mkdtemp())
    url = f"sqlite:///{(tmp_dir / 'phase2_rw_guard.db').as_posix()}"
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "CREATE TABLE task_execution ("
                    "id VARCHAR(36) PRIMARY KEY, task_id VARCHAR(36), attempt INTEGER)"
                )
            )
            # 干净：无重复。
            connection.execute(
                sa.text("INSERT INTO task_execution VALUES ('e1', 't1', 1), ('e2', 't1', 2)")
            )
        with engine.connect() as connection:
            assert module._duplicate_attempt_groups(connection) == []

        with engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO task_execution VALUES ('e3', 't1', 1)"))
        with engine.connect() as connection:
            groups = module._duplicate_attempt_groups(connection)
        assert len(groups) == 1, groups
        assert groups[0][0] == "t1" and groups[0][1] == 1 and groups[0][2] == 2, groups
    finally:
        engine.dispose()


def test_migration_0018_no_drop_extension_vector_and_explicit_dialect() -> None:
    """🔴 ``downgrade`` **可执行 SQL** 不得 ``DROP EXTENSION vector``；``upgrade`` 显式读方言。

    另断言（§08.2）：源码**不得**对 ``uq_task_execution_task_attempt`` 重复创建 / 回滚删除。
    """
    import ast

    source = (REPO_ROOT / _MIGRATION_REL).read_text(encoding="utf-8")
    tree = ast.parse(source)
    sql_texts: list[str] = []
    call_strings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                call_strings.append(arg.value)
                if isinstance(func, ast.Attribute) and func.attr in {"execute", "exec_driver_sql"}:
                    sql_texts.append(arg.value)
    dropped = [text for text in sql_texts if "drop extension" in text.lower()]
    assert not dropped, f"0018 迁移可执行 SQL 含 DROP EXTENSION：{dropped}"
    assert "op.get_bind().dialect.name" in source

    # §08.2：不得重复建 / 回滚删 ``uq_task_execution_task_attempt``（可执行调用中零引用；
    # 文档字符串中的说明性引用不计）。
    leaked = [text for text in call_strings if "uq_task_execution_task_attempt" in text]
    assert not leaked, f"0018 不得在可执行调用中引用 0015 既有唯一约束：{leaked}"
    assert "UniqueConstraint" not in source, "0018 不得再次创建表级唯一约束"


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_migration_0018_postgres() -> None:
    """PostgreSQL（权威方言）：upgrade 0018 → 零漂移 → downgrade 0017 → upgrade 0018。"""
    assert _PG_URL is not None
    url = _PG_URL
    os.environ["ASTRA_MODE"] = "server"
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
            command.upgrade(config, _REV_0018)
            engine = sa.create_engine(url)
            try:
                columns = _columns(engine, "task_execution")
                for column in ADDED_COLUMNS:
                    assert column in columns, column
                assert "project" in _fk_referred_tables(engine, "task_execution")
                assert _unique_constraints(engine, "task_execution").get(_TASK_ATTEMPT_UQ) == {
                    "task_id",
                    "attempt",
                }
                _assert_no_drift(engine)
            finally:
                engine.dispose()

            command.downgrade(config, _REV_0017)
            engine = sa.create_engine(url)
            try:
                columns = _columns(engine, "task_execution")
                for column in ADDED_COLUMNS:
                    assert column not in columns, column
                assert _unique_constraints(engine, "task_execution").get(_TASK_ATTEMPT_UQ) == {
                    "task_id",
                    "attempt",
                }
            finally:
                engine.dispose()

            command.upgrade(config, _REV_0018)
            engine = sa.create_engine(url)
            try:
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, _REV_0017)
    finally:
        reset_settings_cache()
