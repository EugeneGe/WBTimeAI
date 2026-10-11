"""NFR PostgreSQL 侧基线（W8 / T1-38；设计 §3.1 N1/N2 · ``N-P1-01``/``N-P1-02``）。

**PG 门控**（防假绿，对齐 ``test_postgres_smoke`` 与 ``tests/integration/conftest.py``）：

- 未设 ``ASTRA_TEST_PG_URL`` 且未要求 → 本模块**整体不收集**（见 ``tests/nfr/conftest.py``），
  默认本地 run 零噪声；
- 设了 ``ASTRA_TEST_PG_URL``（或 ``ASTRA_TEST_REQUIRE_PG=1``）→ 收集并实跑，
  CI nightly ``nfr.yml`` 提供 postgres service（**A17**：本机无运行时，故 PG 侧经 CI 实跑）。

覆盖：

1. **单 Run 写 1000 条 ``agent_event``（PG）**——``add_many`` 批量写入耗时基线（``N-P1-01``）；
2. **并发活跃 Run 上界（PG）**——``SELECT ... FOR UPDATE`` 行锁下同会话并发创建**恰好**到上限
   （``N-P1-02``；对比 SQLite 参考 harnéss 的非原子缺口，见 ``test_concurrency`` 模块说明）。

🔴 **库隔离（P2-105）**：PG 基线**不**与迁移套件共用 ``astra_test``。原 ``_drop_all()``
只清 ORM 表、遗留 ``alembic_version``（表已空但版本仍 ``0017``）令 ``alembic check`` /
``downgrade base`` **假漂移**，且两套件相互清表。改为**专用库** ``<db>_nfr``
（``ASTRA_TEST_NFR_PG_URL`` 可覆盖），每次起始 ``_reset_schema``：``drop_all`` +
``DROP TABLE IF EXISTS alembic_version``（**不**用 ``DROP SCHEMA public CASCADE``——
会连带删掉 pgvector 扩展对象）。
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from astra_conversation import SqlAgentRunRepository
from astra_core import DomainError, ErrorCode
from astra_domain import AgentRun, ConcurrencyConfig
from astra_runtime import ConcurrencyController
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from tests.nfr._support import (
    bulk_write_1000,
    enforce_nfr,
    resolve_pg_url,
    seed_parent_graph,
    with_connect_timeout,
)

#: 单 Run 批量写 1000 条 ``agent_event`` 耗时上界（毫秒，PostgreSQL）。
EVENT_BULK_1000_PG_MS = int(os.environ.get("ASTRA_NFR_EVENT_BULK_1000_PG_MS", "5000"))

#: NFR PG 基线**专用库**名后缀（P2-105：与迁移套件隔离）。
NFR_DB_SUFFIX = "_nfr"


def _nfr_pg_url() -> str:
    """解析 NFR 专用 PG 连接串（独立库 ``<db>_nfr``；不存在则幂等 ``CREATE DATABASE``）。

    ``ASTRA_TEST_NFR_PG_URL`` 显式给出时**直接用**（不再派生 / 建库）。
    """
    override = os.environ.get("ASTRA_TEST_NFR_PG_URL")
    if override:
        return with_connect_timeout(override)

    url = make_url(resolve_pg_url())
    database = url.database or "postgres"
    target = f"{database}{NFR_DB_SUFFIX}"
    admin = sa.create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True
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
    # 🔴 必须 ``render_as_string(hide_password=False)``：``str(URL)`` 默认把密码渲染为 ``***``。
    return with_connect_timeout(url.set(database=target).render_as_string(hide_password=False))


def _ensure_vector_extension(engine: Engine) -> None:
    """容忍式 ``CREATE EXTENSION IF NOT EXISTS vector``（对齐 ``0013`` 的功能性降级语义）。

    仅在安装了 ``pgvector`` Python 包（``VectorType`` 渲染 ``vector(d)``）时才是必需；
    缺权限 / 无扩展文件时**WARN 不阻塞**（此时 ``VectorType`` 退化 ``JSON``，基线仍可跑）。
    """
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except sa.exc.SQLAlchemyError:  # pragma: no cover - 依环境而定
        pass


def _reset_schema(engine: Engine) -> None:
    """把 NFR 专用库重置为「到达即净」（P2-105）。

    - ``Base.metadata.drop_all`` 删全部 ORM 表；
    - 额外 ``DROP TABLE IF EXISTS alembic_version``（alembic 自有表，不属 ORM 元数据）——
      否则「表已清空但 ``alembic_version`` 仍指向 0017」会令后续 ``alembic check`` 假漂移。
    """
    from astra_database import Base

    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")


def _pg_engine() -> tuple[Engine, sessionmaker[Session]]:
    """建 NFR **专用库** PG 引擎 + 起始重置 schema + 建表，返回 ``(engine, session_factory)``。

    skip / fail 语义见 :func:`tests.nfr._support.resolve_pg_url`（``REQUIRE_PG=1`` 即 fail）。
    """
    url = _nfr_pg_url()

    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_config import Settings
    from astra_database import Base, create_engine_from_settings, create_session_factory

    engine = create_engine_from_settings(
        Settings(mode="server", database_url=url, secret_key="nfr-pg-secret")
    )
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except sa.exc.SQLAlchemyError as exc:  # pragma: no cover - 依 PG 可用性而定
        engine.dispose()
        if os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1":
            pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法连接 PostgreSQL：{exc}")
        pytest.skip(f"无法连接 PostgreSQL：{exc}")

    _ensure_vector_extension(engine)
    _reset_schema(engine)
    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


def test_thousand_agent_events_bulk_write_baseline_postgres() -> None:  # pragma: no cover - CI
    """PostgreSQL（CI nightly 实跑）：单 Run 批量写 1000 条事件低于基线。"""
    engine, factory = _pg_engine()
    try:
        graph = seed_parent_graph(factory, create_run=True)
        assert graph.run_id is not None
        elapsed_ms = bulk_write_1000(factory, graph.run_id)
    finally:
        engine.dispose()
    enforce_nfr("N-P1-01 / 1000 事件批量写入(PG)", elapsed_ms, EVENT_BULK_1000_PG_MS)


def test_concurrent_active_runs_bounded_postgres() -> None:  # pragma: no cover - CI
    """PG 行锁下同会话并发创建**恰好**到上限（``SELECT ... FOR UPDATE`` 生效）。

    需先存在 ``conversation`` 行，行锁方有可锁对象（真实流程中会话先于 Run 建立）。
    """
    engine, factory = _pg_engine()
    try:
        graph = seed_parent_graph(factory)
        repo = SqlAgentRunRepository(factory)
        limit = 3
        concurrency = ConcurrencyController(ConcurrencyConfig(max_runs_per_conversation=limit))
        workers = 12
        barrier = threading.Barrier(workers)
        outcomes: list[str] = []
        lock = threading.Lock()

        def attempt(_index: int) -> None:
            barrier.wait()
            try:
                concurrency.guard_run_creation(
                    repo,
                    AgentRun(
                        tenant_id=graph.tenant_id,
                        conversation_id=graph.conversation_id,
                        agent_id=graph.agent_id,
                        agent_version_id=graph.agent_version_id,
                    ),
                )
                outcome = "ok"
            except DomainError as exc:
                assert exc.code is ErrorCode.CONFLICT
                outcome = "conflict"
            with lock:
                outcomes.append(outcome)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in [pool.submit(attempt, i) for i in range(workers)]:
                future.result()

        active = repo.list_active_by_conversation(graph.conversation_id)
    finally:
        engine.dispose()

    assert outcomes.count("ok") == limit, outcomes
    assert len(active) == limit
