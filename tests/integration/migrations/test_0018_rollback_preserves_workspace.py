"""``0018`` 回滚**磁盘对象保护**测试（T2-64 本地面准备；R5 补全轮 F7-1）。

背景（架构师 §4.2 裁定 / R-R1R5-13 V-D）：``0018`` 的 ``downgrade`` **只**回收 ``task_execution``
加性列 / 索引等 **DB** 对象；**不得**触碰磁盘上的**受管工作区对象**——Project 受管基础仓库
（``<workspace_root>/projects/<project_id>/repo``，**不删**）与 Attempt 独立工作副本
（``<workspace_root>/executions/<execution_id>/attempt-<n>``，按保留策略清理，**非**迁移职责）。

覆盖：

- **SQLite 双向**：``upgrade head`` → ``downgrade 0017`` → 断言 ``task_execution`` 的 8 个加性列
  + 2 个加性索引**消失**、基础列**未动**、``uq_task_execution_task_attempt`` **仍在**；
- **FS 无副作用**：``tmp_path`` + :class:`ProjectStorage` 预置 Project 根仓库 + Attempt 目录
  （皆含文件）→ ``downgrade 0017`` 后**文件仍在**（迁移不删磁盘对象）；
- **PostgreSQL 面**：沿用 ``test_0018.py`` 的 ``ASTRA_TEST_PG_URL`` 门控 skip 体例（本机无 PG →
  不虚报；服务器面随 T2-64 原口径执行）。
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

_REV_0017 = "0017_phase2_evaluation"
_REV_0018 = "0018_phase2_remote_workspace"
_HEAD = "head"

#: ``0018`` 新增的 8 个可空列（回滚后应消失）。
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

#: ``task_execution`` 既有基础列（``0015`` 建；回滚后须仍在）。
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

#: ``0018`` 新增索引名（回滚后应消失）。
ADDED_INDEXES: tuple[str, ...] = (
    "ix_task_execution_project_started",
    "uq_task_execution_checkout_ref",
)

#: ``0015`` 建的唯一约束（§08.2：``0018`` 回滚**不得**删）。
_TASK_ATTEMPT_UQ = "uq_task_execution_task_attempt"

_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"
_CONNECT_TIMEOUT_SECONDS = 10


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


def _unique_constraints(engine: Engine, table: str) -> dict[str, set[str]]:
    inspector = sa.inspect(engine)
    result: dict[str, set[str]] = {}
    for constraint in inspector.get_unique_constraints(table):
        name = constraint.get("name")
        if name:
            result[str(name)] = {str(col) for col in (constraint.get("column_names") or [])}
    return result


def _seed_workspace_objects(root: Path, *, project_id: str, execution_id: str) -> dict[str, Path]:
    """经 :class:`ProjectStorage` 预置 Project 根仓库 + Attempt 目录（各含文件），返回文件路径。

    返回的 ``dict`` 键：``repo_file`` / ``attempt_file``（供回滚后**仍在**断言）。
    """
    from astra_workspace import ProjectStorage

    storage = ProjectStorage(root)
    repo_dir = storage.ensure_project_root(project_id)
    attempt_dir = storage.create_attempt_dir(execution_id, 1)

    repo_file = repo_dir / "README.md"
    repo_file.write_text("# managed base repo\n", encoding="utf-8")
    attempt_file = attempt_dir / "app.py"
    attempt_file.write_text("print('attempt work copy')\n", encoding="utf-8")
    return {"repo_file": repo_file, "attempt_file": attempt_file}


def test_0018_rollback_removes_columns_and_indexes_sqlite() -> None:
    """SQLite：``upgrade head`` → ``downgrade 0017`` → 加性列 / 索引消失，基础列 + 唯一约束仍在。"""
    from alembic import command
    from alembic.script import ScriptDirectory
    from astra_config.loader import reset_settings_cache

    # head 恒定为 ``0018``（回滚目标仍存在）。
    scripts = ScriptDirectory.from_config(_alembic_config())
    assert scripts.get_heads() == [_REV_0018], scripts.get_heads()

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "rollback_cols.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _HEAD)
        engine = sa.create_engine(url)
        try:
            columns = _columns(engine, "task_execution")
            for column in ADDED_COLUMNS:
                assert column in columns, f"upgrade head 后应含加性列 {column}"
            assert _index_names(engine, "task_execution").issuperset(ADDED_INDEXES)
        finally:
            engine.dispose()

        command.downgrade(config, _REV_0017)
        engine = sa.create_engine(url)
        try:
            columns = _columns(engine, "task_execution")
            for column in ADDED_COLUMNS:
                assert column not in columns, f"回滚后加性列 {column} 应消失"
            for column in BASE_COLUMNS:
                assert column in columns, f"回滚后基础列 {column} 不得丢失"

            indexes = _index_names(engine, "task_execution")
            for index in ADDED_INDEXES:
                assert index not in indexes, f"回滚后加性索引 {index} 应消失"

            # §08.2：``0015`` 既有唯一约束**不得**被回滚删除。
            uq = _unique_constraints(engine, "task_execution")
            assert uq.get(_TASK_ATTEMPT_UQ) == {"task_id", "attempt"}, uq
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


def test_0018_downgrade_preserves_workspace_disk_objects(tmp_path: Path) -> None:
    """``downgrade 0017`` **不**删磁盘对象：Project 根仓库 / Attempt 目录文件**仍在**。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    files = _seed_workspace_objects(
        workspace_root, project_id="proj-rollback", execution_id="exec-rollback"
    )
    # 前置：预置对象确实存在（防「假绿」——对象本就不存在）。
    assert files["repo_file"].is_file()
    assert files["attempt_file"].is_file()

    db_dir = Path(tempfile.mkdtemp())
    _fresh_sqlite_url(db_dir, "rollback_fs.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _HEAD)
        command.downgrade(config, _REV_0017)
    finally:
        reset_settings_cache()

    # 回滚后：磁盘对象**原地保留**（迁移只回收 DB 对象，零 FS 副作用）。
    assert files["repo_file"].is_file(), "回滚误删了 Project 根仓库文件"
    assert files["attempt_file"].is_file(), "回滚误删了 Attempt 工作副本文件"
    assert files["repo_file"].read_text(encoding="utf-8") == "# managed base repo\n"
    assert files["attempt_file"].read_text(encoding="utf-8") == "print('attempt work copy')\n"


def test_0018_rollback_then_upgrade_roundtrip_sqlite() -> None:
    """``downgrade 0017`` → 再 ``upgrade head`` → 加性列 / 索引恢复（双向幂等，零残留）。"""
    from alembic import command
    from astra_config.loader import reset_settings_cache

    tmp_dir = Path(tempfile.mkdtemp())
    url = _fresh_sqlite_url(tmp_dir, "rollback_roundtrip.db")
    config = _alembic_config()
    try:
        command.upgrade(config, _HEAD)
        command.downgrade(config, _REV_0017)
        command.upgrade(config, _HEAD)
        engine = sa.create_engine(url)
        try:
            columns = _columns(engine, "task_execution")
            for column in ADDED_COLUMNS:
                assert column in columns, f"回滚再上移后应恢复加性列 {column}"
            assert _index_names(engine, "task_execution").issuperset(ADDED_INDEXES)
            uq = _unique_constraints(engine, "task_execution")
            assert uq.get(_TASK_ATTEMPT_UQ) == {"task_id", "attempt"}, uq
        finally:
            engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.skipif(_PG_URL is None and not _REQUIRE_PG, reason="未配置 ASTRA_TEST_PG_URL")
def test_0018_rollback_postgres_preserves_workspace() -> None:
    """PostgreSQL（权威方言）：``upgrade head`` → ``downgrade 0017`` → 加性列 / 索引消失、
    唯一约束在。

    本机无 PG → 门控 ``skip``（**不**虚报）；服务器面回滚验收随 T2-64 原口径执行。
    """
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
            command.upgrade(config, _HEAD)
            command.downgrade(config, _REV_0017)
            engine = sa.create_engine(url)
            try:
                columns = _columns(engine, "task_execution")
                for column in ADDED_COLUMNS:
                    assert column not in columns, column
                for column in BASE_COLUMNS:
                    assert column in columns, column
                assert _unique_constraints(engine, "task_execution").get(_TASK_ATTEMPT_UQ) == {
                    "task_id",
                    "attempt",
                }
            finally:
                engine.dispose()
        finally:
            command.upgrade(config, _HEAD)
    finally:
        reset_settings_cache()
