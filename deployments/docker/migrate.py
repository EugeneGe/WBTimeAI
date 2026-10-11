#!/usr/bin/env python3
"""Astra AI 容器入口迁移编排（F4①：消除 ``api`` / ``worker`` 并发迁移竞态）。

背景
----
标准 ``docker-compose.yml`` 中 ``api`` 与 ``worker`` **同镜像、同 entrypoint**；
二者在 ``postgres(condition: service_healthy)`` 满足后**并发**执行
``alembic upgrade head``，会竞争创建 ``alembic_version`` →
``psycopg.errors.UniqueViolation``（``pg_type_typname_nsp_index``），后到者
``Exited(1)``。本脚本对 **PostgreSQL** 采用**会话级 advisory lock** 将迁移
**全局串行化**；其它方言（SQLite 等）**原样直连**执行 ``alembic upgrade head``。

纪律（对齐《TV1-修复范围补充裁定》§5.2）
--------------------------------------
- **显式方言分支**：仅依据 ``ASTRA_DATABASE_URL`` 的 scheme 前缀判定，
  **禁止** ``try`` / ``except`` 推断方言；
- **不吞异常 / 不静默降级**：任何失败必须**非零退出**，并**透传** ``alembic`` 的退出码；
- **不新增迁移**：仅执行既有 ``alembic upgrade head``（head 保持
  ``0017_phase2_evaluation``）；
- **只做迁移编排**：不含任何业务逻辑；
- **延迟导入**：``sqlalchemy`` 仅在 PostgreSQL 路径导入，SQLite / 空 URL 路径
  **零额外依赖**（社区无 Docker / 进程内路径不受影响）。

advisory lock 语义
-----------------
``pg_advisory_lock(key)`` 为**会话级**锁：持锁会话（容器进程）解锁前，其它会话对
**同 key** 的 ``pg_advisory_lock`` 阻塞等待；持锁进程崩溃时 PostgreSQL **自动释放**
该会话锁。使用**固定 key** 以实现「全局仅一个迁移者」。
"""

from __future__ import annotations

import os
import subprocess
import sys

#: PostgreSQL advisory lock key（固定；全局序列化 ``alembic upgrade``）。
_ADVISORY_LOCK_KEY = 8891001

#: 触发 advisory-lock 路径的 URL scheme 前缀（显式方言分支，非 ``try``/``except`` 推断）。
_PG_SCHEMES = ("postgresql", "postgres")


def _url_scheme(url: str) -> str:
    """返回 DB URL 的 scheme（``scheme://`` 中 ``://`` 之前部分，小写）。

    Args:
        url: 数据库连接串（如 ``postgresql+psycopg://...``）。

    Returns:
        scheme（如 ``postgresql+psycopg``）；不含 ``://`` 时返回空串。
    """
    marker = "://"
    if marker not in url:
        return ""
    return url.split(marker, 1)[0].lower()


def _is_postgres(url: str) -> bool:
    """显式判定是否 PostgreSQL（按 scheme 前缀，含 ``postgresql+psycopg``）。

    Args:
        url: 数据库连接串。

    Returns:
        为 PostgreSQL 方言返回 ``True``，否则 ``False``。
    """
    return _url_scheme(url).startswith(_PG_SCHEMES)


def _run_alembic_upgrade() -> int:
    """执行 ``alembic upgrade head`` 并返回其退出码（**不吞失败**）。

    Returns:
        ``alembic`` 子进程的退出码（原样透传）。
    """
    completed = subprocess.run(  # noqa: S603 - 固定 argv，未使用 shell
        ["alembic", "upgrade", "head"],
        check=False,
    )
    return completed.returncode


def _upgrade_with_advisory_lock(url: str) -> int:
    """PostgreSQL：持有会话级 advisory lock 后**串行化**执行迁移。

    持锁期间其它容器对同 key ``pg_advisory_lock`` 阻塞等待；迁移结束后（含失败）
    于 ``finally`` 中释放锁并透传退出码。

    Args:
        url: PostgreSQL 连接串（SQLAlchemy 格式，如 ``postgresql+psycopg://...``）。

    Returns:
        ``alembic upgrade head`` 的退出码。

    Raises:
        Exception: 连接 / 加锁失败时向上抛出（非静默），进程以非零码退出。
    """
    import sqlalchemy as sa  # 延迟导入：仅 PostgreSQL 路径需要 SQLAlchemy

    engine = sa.create_engine(url)
    try:
        # AUTOCOMMIT：advisory lock 为**会话级**，无需（亦避免）长事务；
        # 迁移由子进程以独立连接执行。
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(f"SELECT pg_advisory_lock({_ADVISORY_LOCK_KEY})").scalar()
            try:
                return _run_alembic_upgrade()
            finally:
                conn.exec_driver_sql(f"SELECT pg_advisory_unlock({_ADVISORY_LOCK_KEY})").scalar()
    finally:
        engine.dispose()


def main() -> int:
    """入口：按方言分支执行迁移，返回可透传的退出码。

    Returns:
        迁移退出码；``0`` 表示成功，非零表示失败。
    """
    url = os.environ.get("ASTRA_DATABASE_URL", "")
    if _is_postgres(url):
        print(
            "[astra] applying migrations (postgres advisory-lock serialized)...",
            flush=True,
        )
        return _upgrade_with_advisory_lock(url)
    print("[astra] applying database migrations (alembic upgrade head)...", flush=True)
    return _run_alembic_upgrade()


if __name__ == "__main__":
    sys.exit(main())
