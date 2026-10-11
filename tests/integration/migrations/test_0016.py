"""迁移 ``0016_phase2_organization_scope`` 集成测试（W7 / T2-40）。

覆盖（W7 开工前架构裁定 §4.2 / §4.3；team-lead 拍板 R7 / R8 / R9 / R11 / R-open#5）：

- **无未回填**：在 ``0015`` 状态种入租户业务资源（workspace / agent / task / skill / tool /
  project / audit_log）→ ``upgrade 0016`` → 断言各业务资源行 ``organization_id IS NOT NULL``
  （**显式全局资源除外**：``source='builtin'`` 的 ``tool`` 保持 ``NULL``）；
- **默认组织**：每个 tenant 幂等建 ``slug='default'`` 组织（S2）；
- **回填策略**：有 ``workspace_id`` 者经 workspace 推导；无 workspace 者回填默认组织；
  ``workspace`` 直接回填默认组织；
- **双向**：``upgrade 0016`` → ``downgrade 0015``（**只移除本迁移新增的列 / 索引 / 外键**：
  ``audit_log`` / ``project`` / ``workspace_environment`` / ``schedule`` 的 ``organization_id``
  保留；``organization`` 行**不删**）→ ``upgrade 0016``；
- **``organization_id`` 统一口径**：12 张 L1 表 upgrade 后均含列 + ``ix_<表>_organization_id`` +
  ``fk_<表>_organization_id``（镜像 ``membership`` / ``project`` 先例）；downgrade 后三者均移除；
- **单 head**：``0016`` 的 ``down_revision == 0015``，且为唯一 head；
- 静态：``0016`` **不 ``DROP EXTENSION vector``**；downgrade ``drop_column`` 白名单不含
  ``audit_log`` / ``project`` / ``workspace_environment`` / ``schedule``；
- PostgreSQL：同链路（PG 权威 ``alembic check`` 零漂移），受 ``ASTRA_TEST_PG_URL`` 门控。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[3]

_REV_0015 = "0015_phase2_workspace_task"
_REV_0016 = "0016_phase2_organization_scope"

#: 本迁移**加列 + 建索引**的 12 张 L1 表。
L1_ADD_COLUMN_TABLES: tuple[str, ...] = (
    "workspace",
    "agent",
    "conversation",
    "credential",
    "knowledge_base",
    "mcp_server",
    "memory",
    "task",
    "workflow",
    "model_provider",
    "tool",
    "skill",
)

#: 已有 ``organization_id`` 列（列非本迁移新增）→ downgrade **不得** drop 的表。
PRESERVED_ORG_TABLES: tuple[str, ...] = (
    "project",
    "workspace_environment",
    "schedule",
    "audit_log",
)

#: 种入后期望 ``organization_id`` 非空（显式全局资源除外）。
SEEDED_BUSINESS_TABLES: tuple[str, ...] = (
    "workspace",
    "agent",
    "task",
    "skill",
    "project",
    "audit_log",
)

#: 本用例种入、且 **0015 时尚无** ``organization_id`` 列的表（0016 的 S1 才加列）。
SEEDED_L1_TABLES: tuple[str, ...] = ("workspace", "agent", "task", "skill")

#: 0015 时**已含** ``organization_id`` 列的表 → upgrade 前可观测「未回填（NULL）」。
PRE_EXISTING_ORG_TABLES: tuple[str, ...] = ("project", "audit_log")

_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"
_CONNECT_TIMEOUT_SECONDS = 10

# 种入标识（SQLite 用例）。
_T = "00000000-0000-7000-8000-000000000001"
_U = "00000000-0000-7000-8000-000000000002"
_WS = "00000000-0000-7000-8000-000000000003"
_AGENT = "00000000-0000-7000-8000-000000000004"
_TASK_WS = "00000000-0000-7000-8000-000000000005"
_TASK_NOWS = "00000000-0000-7000-8000-000000000006"
_SKILL = "00000000-0000-7000-8000-000000000007"
_TOOL_BUILTIN = "00000000-0000-7000-8000-000000000008"
_TOOL_TENANT = "00000000-0000-7000-8000-000000000009"
_PROJECT = "00000000-0000-7000-8000-00000000000a"
_AUDIT_WS = "00000000-0000-7000-8000-00000000000b"
_AUDIT_NOWS = "00000000-0000-7000-8000-00000000000c"

#: 统计某 tenant 的默认组织数（复用 SQL）。
_DEFAULT_ORG_COUNT_SQL = (
    "SELECT count(*) FROM organization WHERE tenant_id = :t AND slug = 'default'"
)


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


def _columns(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(engine).get_columns(table)}


def _index_names(engine: Engine, table: str) -> set[str]:
    inspector = sa.inspect(engine)
    return {str(index["name"]) for index in inspector.get_indexes(table) if index.get("name")}


def _fk_names(engine: Engine, table: str) -> set[str]:
    inspector = sa.inspect(engine)
    return {str(fk["name"]) for fk in inspector.get_foreign_keys(table) if fk.get("name")}


def _scalar(engine: Engine, sql: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(sa.text(sql), params).scalar_one()


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


def _seed_0015_state(engine: Engine) -> None:
    """在 ``0015`` 状态种入最小租户业务资源（organization_id 尚未回填）。

    🔴 用**显式列清单**的裸 SQL（此时 ORM 已含 head 的 ``organization_id`` 列，DB 尚无，
    不可经 ORM 写入）。
    """
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
            "INSERT INTO tool (id, tenant_id, name, display_name, description, category, source, "
            "input_schema, output_schema, requires_sandbox, status, tool_ref) "
            "VALUES (:tb, NULL, 'filesystem', 'FS', NULL, 'builtin', 'builtin', "
            "NULL, NULL, 0, 'ACTIVE', NULL)",
            {"tb": _TOOL_BUILTIN},
        ),
        (
            "INSERT INTO tool (id, tenant_id, name, display_name, description, category, source, "
            "input_schema, output_schema, requires_sandbox, status, tool_ref) "
            "VALUES (:tt, :t, 'my_tool', 'My', NULL, 'custom', 'plugin', "
            "NULL, NULL, 0, 'ACTIVE', NULL)",
            {"tt": _TOOL_TENANT, "t": _T},
        ),
        (
            "INSERT INTO project (id, tenant_id, organization_id, workspace_id, name, description, "
            "repo_url, default_branch, settings, created_by) "
            "VALUES (:pj, :t, NULL, :ws, 'P', NULL, NULL, NULL, NULL, :u)",
            {"pj": _PROJECT, "t": _T, "ws": _WS, "u": _U},
        ),
        (
            "INSERT INTO audit_log (id, tenant_id, organization_id, workspace_id, user_id, "
            "agent_id, run_id, tool_call_id, action, resource_type, resource_id, outcome, "
            "request_id) "
            "VALUES (:al, :t, NULL, :ws, NULL, NULL, NULL, NULL, 'demo', NULL, NULL, "
            "'SUCCESS', 'req-1')",
            {"al": _AUDIT_WS, "t": _T, "ws": _WS},
        ),
        (
            "INSERT INTO audit_log (id, tenant_id, organization_id, workspace_id, user_id, "
            "agent_id, run_id, tool_call_id, action, resource_type, resource_id, outcome, "
            "request_id) "
            "VALUES (:al, :t, NULL, NULL, NULL, NULL, NULL, NULL, 'demo', NULL, NULL, "
            "'SUCCESS', 'req-2')",
            {"al": _AUDIT_NOWS, "t": _T},
        ),
    ]
    with engine.begin() as connection:
        for sql, params in statements:
            connection.execute(sa.text(sql), params)


def test_migration_0016_single_head() -> None:
    """``0016`` 的 ``down_revision == 0015``，且位于唯一 head 的**祖先链**上。

    🔴 W9 / T2-45：新增 head ``0017`` 后，``0016`` **不再是**全局 head（本断言原先硬编 0016
    为 head，现改为「单链线性 + 0016 在 head 祖先链上」——全局唯一 head 的**恒等**断言由最新
    迁移测试 ``test_0017.py::test_migration_0017_single_head`` 承担）。仅收紧口径（仍断言单 head）。
    """
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(_alembic_config())
    revision = scripts.get_revision(_REV_0016)
    assert revision.down_revision == _REV_0015
    heads = scripts.get_heads()
    assert len(heads) == 1, f"迁移链应为单 head：{heads}"
    chain: list[str] = []
    current = scripts.get_revision(heads[0])
    while current is not None:
        chain.append(current.revision)
        current = scripts.get_revision(current.down_revision) if current.down_revision else None
    assert _REV_0016 in chain, f"0016 不在 head({heads[0]}) 祖先链上：{chain}"


def test_migration_0016_backfill_and_bidirectional_sqlite() -> None:
    """0015 种入 → upgrade 0016（无未回填）→ downgrade 0015（只删新增列/索引）→ upgrade 0016。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_org.db")
    config = _alembic_config()
    try:
        # -- 0015：种入业务资源（organization_id 未回填） -------------------
        command.upgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            _seed_0015_state(engine)
            assert _scalar(engine, "SELECT count(*) FROM organization") == 0
            # 0015 状态：L1 表**尚无** organization_id 列（0016 的 S1 才加列）。
            for table in SEEDED_L1_TABLES:
                assert "organization_id" not in _columns(engine, table), table
            # 0015 已含列者（project / audit_log）此时全为 NULL（未回填）。
            before = {
                table: _scalar(
                    engine, f"SELECT count(*) FROM {table} WHERE organization_id IS NULL"
                )
                for table in PRE_EXISTING_ORG_TABLES
            }
            assert all(int(v) > 0 for v in before.values()), before
        finally:
            engine.dispose()

        # -- upgrade 0016：回填 + 验证无遗漏（迁移内 S4）+ 零漂移 ----------
        command.upgrade(config, _REV_0016)
        engine = sa.create_engine(url)
        try:
            default_org = _scalar(
                engine,
                "SELECT id FROM organization WHERE tenant_id = :t AND slug = 'default'",
                t=_T,
            )
            assert default_org is not None
            # 无未回填（显式全局资源除外）。
            for table in SEEDED_BUSINESS_TABLES:
                assert (
                    int(
                        _scalar(
                            engine,
                            f"SELECT count(*) FROM {table} WHERE organization_id IS NULL",
                        )
                    )
                    == 0
                ), table
            assert (
                int(
                    _scalar(
                        engine,
                        "SELECT count(*) FROM tool "
                        "WHERE organization_id IS NULL AND source <> 'builtin'",
                    )
                )
                == 0
            )

            # 回填策略校验：经 workspace 推导 + 无 workspace 默认组织 + builtin 保持 NULL。
            def _org(table: str, entity_id: str) -> object:
                return _scalar(
                    engine, f"SELECT organization_id FROM {table} WHERE id = :i", i=entity_id
                )

            assert _org("workspace", _WS) == default_org
            assert _org("agent", _AGENT) == default_org
            assert _org("task", _TASK_WS) == default_org
            assert _org("task", _TASK_NOWS) == default_org
            assert _org("skill", _SKILL) == default_org
            assert _org("project", _PROJECT) == default_org
            assert _org("audit_log", _AUDIT_WS) == default_org
            assert _org("audit_log", _AUDIT_NOWS) == default_org
            assert _org("tool", _TOOL_TENANT) == default_org
            # 🔴 全局内置 Tool 保持 NULL（不表示跨组织共享）。
            assert (
                _scalar(engine, "SELECT organization_id FROM tool WHERE id = :i", i=_TOOL_BUILTIN)
                is None
            )
            for table in L1_ADD_COLUMN_TABLES:
                assert f"ix_{table}_organization_id" in _index_names(engine, table), table
                assert f"fk_{table}_organization_id" in _fk_names(engine, table), table
            # 🔴 W9 / T2-45：0016 已非 head（head＝0017）→ 中间版本漂移断言无效
            #    （``compare_metadata`` 比对 head 元数据，0017 四表会被误判为漂移）；
            #    漂移断言下移至下方 **head** 阶段（对齐 test_0015 先例；仅收紧口径）。
        finally:
            engine.dispose()

        # -- downgrade 0015：只移除新增列 / 索引 --------------------------
        command.downgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            for table in L1_ADD_COLUMN_TABLES:
                assert "organization_id" not in _columns(engine, table), table
                assert f"ix_{table}_organization_id" not in _index_names(engine, table), table
                assert f"fk_{table}_organization_id" not in _fk_names(engine, table), table
            for table in PRESERVED_ORG_TABLES:
                assert "organization_id" in _columns(engine, table), table
            # organization 行不删；audit_log 组织归属不改回。
            assert int(_scalar(engine, "SELECT count(*) FROM organization")) >= 1
            assert (
                _scalar(engine, "SELECT organization_id FROM audit_log WHERE id = :i", i=_AUDIT_WS)
                is not None
            )
        finally:
            engine.dispose()

        # -- 再 upgrade 0016：幂等回填 + 零漂移 ---------------------------
        command.upgrade(config, _REV_0016)
        engine = sa.create_engine(url)
        try:
            for table in L1_ADD_COLUMN_TABLES:
                assert "organization_id" in _columns(engine, table), table
                assert f"fk_{table}_organization_id" in _fk_names(engine, table), table
            assert (
                int(
                    _scalar(
                        engine,
                        "SELECT count(*) FROM agent WHERE organization_id IS NULL",
                    )
                )
                == 0
            )
        finally:
            engine.dispose()

        # -- 升到 head 断言零漂移（W9 / T2-45：0017 起 head ≠ 0016）-------
        command.upgrade(config, "head")
        engine = sa.create_engine(url)
        try:
            _assert_no_drift(engine)
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0016_default_org_idempotent_sqlite() -> None:
    """S2 幂等：重复 upgrade 不产生重复默认组织；每个 tenant 各一默认组织。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "phase2_org_idem.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _REV_0015)
        engine = sa.create_engine(url)
        try:
            _seed_0015_state(engine)
        finally:
            engine.dispose()

        command.upgrade(config, _REV_0016)
        engine = sa.create_engine(url)
        try:
            assert (
                int(
                    _scalar(
                        engine,
                        _DEFAULT_ORG_COUNT_SQL,
                        t=_T,
                    )
                )
                == 1
            )
        finally:
            engine.dispose()

        command.downgrade(config, _REV_0015)
        command.upgrade(config, _REV_0016)
        engine = sa.create_engine(url)
        try:
            assert (
                int(
                    _scalar(
                        engine,
                        _DEFAULT_ORG_COUNT_SQL,
                        t=_T,
                    )
                )
                == 1
            )
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_migration_0016_no_drop_extension_vector() -> None:
    """🔴 ``0016`` 的**可执行 SQL** 中**不得** ``DROP EXTENSION vector``。"""
    import ast

    source = (
        REPO_ROOT / "migrations" / "versions" / "0016_phase2_organization_scope.py"
    ).read_text(encoding="utf-8")
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
    assert not dropped, f"0016 迁移可执行 SQL 含 DROP EXTENSION：{dropped}"


def test_migration_0016_downgrade_drop_column_whitelist_static() -> None:
    """🔴 ``0016`` downgrade ``drop_column`` 白名单 = 12 张 L1 表（不含 ``audit_log`` 等）。"""
    import ast

    source = (
        REPO_ROOT / "migrations" / "versions" / "0016_phase2_organization_scope.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    # 收集 downgrade() 函数体里的 drop_column 目标表（含 batch_op.drop_column）。
    downgrade_fn = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    dropped: set[str] = set()
    for node in ast.walk(downgrade_fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "drop_column":
            # op.drop_column(table, "organization_id") 的第 1 个位置参数即表名。
            if node.args and isinstance(node.args[0], ast.Constant):
                dropped.add(str(node.args[0].value))
    # 本迁移以 batch_alter_table 承接 SQLite 删列，故 drop_column 目标在 batch 上下文；
    # 静态断言：明令禁删的表不得出现在 drop_column 调用中（且不留 drop_table）。
    for table in PRESERVED_ORG_TABLES:
        assert table not in dropped, f"downgrade 不得 drop {table}.organization_id"
    drop_tables = [
        node.args[0].value
        for node in ast.walk(downgrade_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "drop_table"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert not drop_tables, f"0016 downgrade 不应 drop_table：{drop_tables}"


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_migration_0016_postgres() -> None:
    """PostgreSQL（权威方言）：upgrade 0016（对象存在性）→ downgrade 0015 → upgrade **head**
    （零漂移口径，与 SQLite 分支同构）。"""
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
            command.upgrade(config, _REV_0016)
            engine = sa.create_engine(url)
            try:
                for table in L1_ADD_COLUMN_TABLES:
                    assert "organization_id" in _columns(engine, table), table
                    assert f"fk_{table}_organization_id" in _fk_names(engine, table), table
            finally:
                engine.dispose()

            command.downgrade(config, _REV_0015)
            engine = sa.create_engine(url)
            try:
                for table in L1_ADD_COLUMN_TABLES:
                    assert "organization_id" not in _columns(engine, table), table
                for table in PRESERVED_ORG_TABLES:
                    assert "organization_id" in _columns(engine, table), table
            finally:
                engine.dispose()

            # -- 升到 head 断言零漂移（W9 / T2-45：0017 起 head ≠ 0016）-------
            command.upgrade(config, "head")
            engine = sa.create_engine(url)
            try:
                _assert_no_drift(engine)
            finally:
                engine.dispose()
        finally:
            command.downgrade(config, _REV_0015)
    finally:
        reset_settings_cache()
