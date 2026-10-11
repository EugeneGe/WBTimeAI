"""``tests/nfr`` 专用 fixture / 辅助（W8 / T1-38）。

提供 NFR 基线所需的**共享构造**：

- :func:`build_sqlite_engine` / :func:`build_session_factory`：带 **busy-timeout** 的 SQLite
  引擎与会话工厂——并发用例（``N-P1-02``）多线程写同一库时的必需设置（默认 SQLite 5s
  锁等待在多写竞争下会 ``database is locked``）；
- :func:`ensure_schema`：把 ORM 全表建到指定引擎（幂等）；
- :func:`nfr_sqlite_factory`：基于 ``tmp_path`` 的会话工厂 fixture。

其余环境隔离（``ASTRA_MODE`` / ``ASTRA_DATABASE_URL`` / 配置缓存）复用根 ``conftest`` 的
``isolated_settings_env``，避免重复。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

#: PG 门控：未配置 ``ASTRA_TEST_PG_URL`` 且未要求时，**不收集** PG 侧基线模块，使默认本地 run
#: 零噪声（对齐 ``tests/integration/conftest.py``）；CI nightly 配置 PG 后收集并实跑。
collect_ignore: list[str] = []
if not os.environ.get("ASTRA_TEST_PG_URL") and os.environ.get("ASTRA_TEST_REQUIRE_PG") != "1":
    collect_ignore.append("test_pg_baselines.py")

#: 并发写竞争下的 SQLite 锁等待上限（秒）；避免多线程写同一库时 ``database is locked``。
SQLITE_BUSY_TIMEOUT_SECONDS = 30


def build_sqlite_engine(url: str) -> Engine:
    """按 ``url`` 建 SQLite 引擎（``check_same_thread=False`` + busy-timeout）。

    Args:
        url: SQLite 连接串（``sqlite:///...``）。

    Returns:
        可跨线程并发使用的引擎。
    """
    return sa.create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_SECONDS},
    )


def ensure_schema(engine: Engine) -> None:
    """把全部 ORM 表建到 ``engine``（幂等）。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_database import Base

    Base.metadata.create_all(engine)


def build_session_factory(url: str) -> tuple[Engine, sessionmaker[Session]]:
    """建 SQLite 引擎 + 建表 + 返回 ``(engine, session_factory)``（并发用例共享入口）。"""
    from astra_database import create_session_factory

    engine = build_sqlite_engine(url)
    ensure_schema(engine)
    return engine, create_session_factory(engine)


@pytest.fixture()
def nfr_sqlite_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    """基于 ``tmp_path`` 的 SQLite 会话工厂（busy-timeout，支持多线程并发写）。"""
    db_file = tmp_path / "nfr.db"
    engine, factory = build_session_factory(f"sqlite:///{db_file.as_posix()}")
    try:
        yield factory
    finally:
        engine.dispose()
