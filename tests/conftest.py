"""pytest 公共 fixture。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def docker_required() -> bool:
    """``ASTRA_TEST_REQUIRE_DOCKER=1`` 强开关（防假绿，总纲 §13.3）。

    为真时，若本机无 Docker 运行时，Docker 隔离测试**必须 fail**（不得静默 skip）。
    """
    return os.environ.get("ASTRA_TEST_REQUIRE_DOCKER") == "1"


@pytest.fixture()
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """隔离的配置环境：local 模式 + 临时 SQLite，并清空配置缓存。

    W3 起 API lifespan 会触发默认身份引导（需要表就位），故此处**预建 schema**
    （``Base.metadata.create_all``，测试基础设施，非迁移）。
    """
    db_file = tmp_path / "astra_test.db"
    monkeypatch.setenv("ASTRA_MODE", "local")
    monkeypatch.setenv("ASTRA_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("ASTRA_SECRET_KEY", "test-secret-key-0123456789abcdef-32bytes")
    monkeypatch.setenv("ASTRA_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("ASTRA_LOG_FORMAT", "console")
    monkeypatch.delenv("ASTRA_CONFIG_FILE", raising=False)

    from astra_config.loader import reset_settings_cache

    reset_settings_cache()

    # 预建 schema：注册全部 ORM 表并建表（幂等）。
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_config import get_settings
    from astra_database import Base, create_engine_from_settings

    engine = create_engine_from_settings(get_settings())
    Base.metadata.create_all(engine)
    engine.dispose()

    yield db_file
    reset_settings_cache()


@pytest.fixture()
def client(isolated_settings_env: Path) -> Iterator[object]:
    """基于隔离配置构造的 FastAPI TestClient。"""
    from astra_api.main import create_app
    from fastapi.testclient import TestClient

    application = create_app()
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def session_factory(isolated_settings_env: Path) -> Iterator[object]:
    """与 API 共享同一 SQLite 文件的会话工厂（供直接持久化断言）。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_config import get_settings
    from astra_database import Base, create_engine_from_settings, create_session_factory

    engine = create_engine_from_settings(get_settings())
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def auth_headers(client: object) -> dict[str, str]:
    """注册并登录一个用户，返回带 Bearer 的请求头。"""
    response = client.post(  # type: ignore[attr-defined]
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "secret123",
            "display_name": "Alice",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def workspace_id(client: object, auth_headers: dict[str, str]) -> str:
    """创建一个工作区并返回其 id。

    F-4 / Erratum ``R-R1R5-E1``：**新建会话**（``POST /agents/{id}/run`` 无 ``conversation_id``、
    ``POST /conversations``）的 ``workspace_id`` **必填**；既有用例经此 fixture 提供显式工作区。
    """
    created = client.post(  # type: ignore[attr-defined]
        "/api/v1/workspaces", headers=auth_headers, json={"name": "ws-f4"}
    )
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def _forge_access_token(
    session_factory: object, *, tenant_slug: str, username: str
) -> dict[str, str]:
    """为指定租户下的用户伪造 access token（同一密钥，供跨租户 / RBAC 用例）。"""
    from astra_config import get_settings
    from astra_identity import build_identity_services
    from astra_security import TokenService

    identity = build_identity_services(session_factory)  # type: ignore[arg-type]
    tenant = identity.tenants.ensure_tenant(tenant_slug, tenant_slug.title())
    user = identity.users.ensure_user(
        tenant_id=tenant.id,
        username=username,
        email=f"{username}@example.com",
        password_hash="x",
    )
    token = TokenService(get_settings().secret_key).create_access_token(
        user.id, tenant_id=tenant.id
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def other_tenant_headers(session_factory: object) -> dict[str, str]:
    """另一个租户（``acme``）用户的请求头（用于跨租户不可见断言）。"""
    return _forge_access_token(session_factory, tenant_slug="acme", username="bob")


@pytest.fixture()
def permissionless_headers(client: object, session_factory: object) -> dict[str, str]:
    """默认租户下**无成员关系**的用户请求头（无权限 → 403）。"""
    from astra_config import get_settings
    from astra_identity import build_identity_services
    from astra_security import TokenService

    identity = build_identity_services(session_factory)  # type: ignore[arg-type]
    tenant = identity.tenants.ensure_default()
    user = identity.users.ensure_user(
        tenant_id=tenant.id,
        username="nobody",
        email="nobody@example.com",
        password_hash="x",
    )
    token = TokenService(get_settings().secret_key).create_access_token(
        user.id, tenant_id=tenant.id
    )
    return {"Authorization": f"Bearer {token}"}
