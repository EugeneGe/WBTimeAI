"""引擎构建：依连接串选择引擎/方言（上层不感知方言）。"""

from __future__ import annotations

from typing import Any

from astra_config import Settings
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

__all__ = ["create_engine_from_settings", "build_engine", "SQLITE_BUSY_TIMEOUT_SECONDS"]

#: SQLite 并发写等待上限（秒）——多写者竞争（如 ``BEGIN IMMEDIATE`` 取锁）时「等待」而非
#: 立即 ``database is locked``。显式固化（对齐 ``tests/nfr/conftest.py`` 的 30s），不依赖
#: pysqlite 默认的 5s（W8-2 / C-2；亦惠及 W8-3 的 SQLite 写路径）。
SQLITE_BUSY_TIMEOUT_SECONDS = 30


def create_engine_from_settings(settings: Settings, *, echo: bool | None = None) -> Engine:
    """依 ``settings`` 创建 SQLAlchemy 引擎。

    SQLite 与 PostgreSQL 通过连接串切换，方言差异由 :mod:`astra_database.types` 吸收。

    Args:
        settings: 生效配置（读取 ``database_url`` 与 ``sql_echo``）。
        echo: 覆盖 ``sql_echo``（``None`` 时取配置值）。

    Returns:
        SQLAlchemy :class:`~sqlalchemy.engine.Engine`。
    """
    url = settings.database_url
    echo_flag = settings.sql_echo if echo is None else echo

    engine_kwargs: dict[str, Any] = {
        "echo": echo_flag,
        "future": True,
        "pool_pre_ping": True,
    }

    if url.startswith("sqlite"):
        # SQLite 允许跨线程使用（TestClient / 多线程场景）；并显式设 busy-timeout，
        # 使并发写者竞争时**等待**而非立即 ``database is locked``（W8-2 / C-2）。
        engine_kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
        }

    return create_engine(url, **engine_kwargs)


#: 语义等价别名，便于调用点表达。
build_engine = create_engine_from_settings
