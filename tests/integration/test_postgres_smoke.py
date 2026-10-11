"""双引擎（PostgreSQL）冒烟测试（T0-23 / §2U.1、§2U.3）。

**门控语义（防假绿，对齐 §2U.3 关键点 ④）**：

- 未设 ``ASTRA_TEST_PG_URL``：默认 ``pytest.skip``；**但当 ``ASTRA_TEST_REQUIRE_PG=1``
  时改为 ``pytest.fail``**——CI ``postgres-smoke`` job 必须真连 PG，不得静默跳过。
- 设了 ``ASTRA_TEST_PG_URL`` 但连不通：默认 ``pytest.skip``；同样在
  ``ASTRA_TEST_REQUIRE_PG=1`` 时 ``pytest.fail``。

覆盖：``create_engine_from_settings``（方言选择）→ ``Base.metadata.create_all``
（``GUID`` / ``JSONType`` 方言适配路径）→ 一次仓储读写往返 → 清理。

🔴 **往返用专用库（对齐 NFR ``P2-105``）**：往返用例对 schema 做 ``create_all … drop_all``，
若落在 ``ASTRA_TEST_PG_URL`` 指向的**共享库**上，会**摧毁迁移套件建好的 schema**，
并遗留 ``alembic_version``（表已空而版本仍指向某 revision）⇒ 后续 ``alembic check`` / ``downgrade``
**假漂移**（与 ``P2-105`` 同类缺陷）。故往返改在**专用库** ``<db>_smoke`` 上跑
（``CREATE DATABASE`` 幂等 + 容忍式 ``CREATE EXTENSION IF NOT EXISTS vector``——``vector``
是**每库**级别，新库不自带）；纯连通性用例仍用 ``ASTRA_TEST_PG_URL`` 原库。
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

_PG_URL = os.environ.get("ASTRA_TEST_PG_URL")
_REQUIRE_PG = os.environ.get("ASTRA_TEST_REQUIRE_PG") == "1"

#: 连接超时（秒）：避免 PG 不可达时 CI 长时间挂起（psycopg 经 libpq 接受该参数）。
_CONNECT_TIMEOUT_SECONDS = 10

#: 往返用例**专用库**名后缀（避免污染共享库的 schema 与 ``alembic_version``）。
_SMOKE_DB_SUFFIX = "_smoke"


def _with_connect_timeout(url: str) -> str:
    """为 PostgreSQL 连接串注入 ``connect_timeout``（幂等，防止探测阶段挂起）。"""
    if not url.startswith(("postgresql", "postgres")):
        return url
    if "connect_timeout" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}connect_timeout={_CONNECT_TIMEOUT_SECONDS}"


def _resolve_pg_url() -> str:
    """返回 PG 连接串；缺失时按门控语义 skip / fail。"""
    if not _PG_URL:
        if _REQUIRE_PG:
            pytest.fail(
                "ASTRA_TEST_REQUIRE_PG=1 但未设置 ASTRA_TEST_PG_URL —— "
                "PostgreSQL 冒烟不得被跳过（防假绿）。"
            )
        pytest.skip("未设置 ASTRA_TEST_PG_URL，跳过 PostgreSQL 冒烟。")
    return _PG_URL


def _ensure_vector_extension(engine: Engine) -> None:
    """容忍式 ``CREATE EXTENSION IF NOT EXISTS vector``（对齐 NFR ``P2-105`` 同款口径）。

    新建的专用库不带任何扩展（``vector`` 是**每库**级别的），而 ``embedding.vector`` 列在
    装了 ``pgvector`` Python 包时会渲染为原生 ``vector(1536)``（见 ``astra_database.types``）。

    容忍**不构成假绿**：若 ``pgvector`` 包在而扩展建不成，紧随其后的
    ``Base.metadata.create_all`` 会因类型不存在而**报错 → 用例失败**；
    若包不在，``VectorType`` 已退化为 ``JSON``，本就不需要扩展。
    """
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except SQLAlchemyError:  # pragma: no cover - 依 PG 权限 / 扩展文件而定
        pass


def _dedicated_pg_url(url: str) -> str:
    """派生往返用例**专用库**连接串（不存在则幂等 ``CREATE DATABASE``）。

    失败按模块门控语义 skip / fail（``_REQUIRE_PG=1`` 即 fail，防假绿）。

    Args:
        url: ``ASTRA_TEST_PG_URL`` 原库连接串。

    Returns:
        指向 ``<db>_smoke`` 的连接串（保留原库的账号 / 主机 / 端口）。
    """
    parsed = make_url(url)
    database = parsed.database or "postgres"
    target = f"{database}{_SMOKE_DB_SUFFIX}"
    try:
        admin = sa.create_engine(
            parsed.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True
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
    except SQLAlchemyError as exc:  # pragma: no cover - 依 PG 权限而定
        if _REQUIRE_PG:
            pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法创建专用库 {target}：{exc}")
        pytest.skip(f"无法创建专用库 {target}：{exc}")

    # 🔴 必须 ``render_as_string(hide_password=False)``：``str(URL)`` 默认把密码渲染为 ``***``。
    target_url = parsed.set(database=target).render_as_string(hide_password=False)
    dedicated = sa.create_engine(_with_connect_timeout(target_url), future=True)
    try:
        _ensure_vector_extension(dedicated)
    finally:
        dedicated.dispose()
    return _with_connect_timeout(target_url)


def _build_engine(url: str) -> Engine:
    """按 ``url`` 构造引擎并探测连通性；失败时按门控语义 skip / fail。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_config import Settings
    from astra_database import create_engine_from_settings

    settings = Settings(
        mode="server",
        database_url=_with_connect_timeout(url),
        secret_key="smoke-secret",
    )
    engine = create_engine_from_settings(settings)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except SQLAlchemyError as exc:  # pragma: no cover - 依 PG 可用性而定
        engine.dispose()
        if _REQUIRE_PG:
            pytest.fail(f"ASTRA_TEST_REQUIRE_PG=1 但无法连接 PostgreSQL：{exc}")
        pytest.skip(f"无法连接 PostgreSQL：{exc}")
    return engine


def test_postgres_smoke_configured() -> None:
    """最小连通性校验：门控生效 + ``SELECT 1`` 成功。"""
    url = _resolve_pg_url()
    engine = _build_engine(url)
    try:
        assert (
            engine.dialect.name == "postgresql"
        ), f"ASTRA_TEST_PG_URL 非 PostgreSQL 方言：{engine.dialect.name}"
    finally:
        engine.dispose()


def test_postgres_smoke_roundtrip() -> None:
    """建表 → 仓储读写往返（含 GUID 方言适配）→ 清理。

    🔴 落在**专用库**（``<db>_smoke``）而非共享 ``ASTRA_TEST_PG_URL`` 原库：本用例对 schema
    做 ``create_all … drop_all``，若在共享库上跑会摧毁迁移套件建的 schema 并遗留
    ``alembic_version`` ⇒ 后续 ``alembic check`` / ``downgrade`` 假漂移（``P2-105`` 同类）。
    """
    url = _dedicated_pg_url(_resolve_pg_url())
    engine = _build_engine(url)

    from astra_database import Base, create_session_factory
    from astra_identity import TenantService

    Base.metadata.create_all(engine)
    try:
        factory = create_session_factory(engine)
        created = TenantService(factory).ensure_tenant("smoke", "Smoke Tenant")
        fetched = TenantService(factory).get_by_slug("smoke")
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Smoke Tenant"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
