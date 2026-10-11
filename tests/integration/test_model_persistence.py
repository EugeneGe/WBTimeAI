"""Model Provider / Model 持久化往返集成测试（T1-10，SQLite）。

构造 ``astra_database`` 的 SQL 仓储 → **注入** ``ModelCatalogService``；
覆盖 Provider / Model 往返、租户隔离、``credential_id`` 仅存引用、状态语义。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from astra_core import DomainError, ErrorCode
from astra_database import (
    Base,
    SqlModelProviderRepository,
    SqlModelRepository,
    create_session_factory,
)
from astra_model import ModelCatalogService, build_model_catalog_service
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

TENANT_A = "tenant-aaaa"
TENANT_B = "tenant-bbbb"


@pytest.fixture()
def model_session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    engine = create_engine(f"sqlite:///{(tmp_path / 'model.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def service(model_session_factory: sessionmaker[Session]) -> ModelCatalogService:
    return build_model_catalog_service(
        provider_repository=SqlModelProviderRepository(model_session_factory),
        model_repository=SqlModelRepository(model_session_factory),
    )


def test_repositories_satisfy_domain_protocols(
    model_session_factory: sessionmaker[Session],
) -> None:
    from astra_domain import ModelProviderRepository, ModelRepository

    assert isinstance(SqlModelProviderRepository(model_session_factory), ModelProviderRepository)
    assert isinstance(SqlModelRepository(model_session_factory), ModelRepository)


def test_provider_roundtrip_and_tenant_isolation(service: ModelCatalogService) -> None:
    created = service.register_provider(
        tenant_id=TENANT_A,
        name="OpenAI",
        provider_type="openai",
        endpoint="https://api.openai.com/v1",
        credential_id="cred-1234",
        config={"organization": "org-1"},
    )
    fetched = service.get_provider(created.id, tenant_id=TENANT_A)
    assert fetched.name == "OpenAI"
    assert fetched.type == "openai"
    assert fetched.endpoint == "https://api.openai.com/v1"
    assert fetched.credential_id == "cred-1234"
    assert fetched.config == {"organization": "org-1"}

    service.register_provider(tenant_id=TENANT_B, name="B", provider_type="ollama")
    assert [item.tenant_id for item in service.list_providers(TENANT_A)] == [TENANT_A]

    with pytest.raises(DomainError) as excinfo:
        service.get_provider(created.id, tenant_id=TENANT_B)
    assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_provider_disable_persists(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="x", provider_type="openai")
    service.disable_provider(provider.id, tenant_id=TENANT_A)
    assert service.get_provider(provider.id, tenant_id=TENANT_A).status == "DISABLED"


def test_model_roundtrip(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="x", provider_type="openai")
    created = service.register_model(
        tenant_id=TENANT_A,
        provider_id=provider.id,
        name="gpt-4o",
        context_window=128000,
        capabilities={"vision": True},
    )
    fetched = service.get_model(created.id, tenant_id=TENANT_A)
    assert fetched.name == "gpt-4o"
    assert fetched.provider_id == provider.id
    assert fetched.context_window == 128000
    assert fetched.capabilities == {"vision": True}

    listed = service.list_models(provider.id, tenant_id=TENANT_A)
    assert [item.id for item in listed] == [created.id]

    service.disable_model(created.id, tenant_id=TENANT_A)
    assert service.get_model(created.id, tenant_id=TENANT_A).status == "DISABLED"


def test_model_tenant_isolation(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="x", provider_type="openai")
    model = service.register_model(tenant_id=TENANT_A, provider_id=provider.id, name="m")
    with pytest.raises(DomainError) as excinfo:
        service.get_model(model.id, tenant_id=TENANT_B)
    assert excinfo.value.code is ErrorCode.NOT_FOUND
