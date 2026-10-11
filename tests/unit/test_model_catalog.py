"""``ModelCatalogService`` 领域单测（内存 fake 仓储，纯单测）。

覆盖 T1-10 验收口径：Provider / Model CRUD + 目录查询 + 租户隔离 +
状态语义（``ACTIVE`` / ``DISABLED``）+ ``ModelRegistry`` 接线。
"""

from __future__ import annotations

from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import (
    MODEL_PROVIDER_STATUS_DISABLED,
    MODEL_STATUS_DISABLED,
    Model,
    ModelProvider,
    ModelProviderRepository,
    ModelRepository,
)
from astra_model import ModelCatalogService, ModelRegistry, StubModelProvider

TENANT_A = "tenant-aaaa"
TENANT_B = "tenant-bbbb"


class FakeProviderRepository:
    """内存 Provider 仓储（结构型满足领域 Protocol）。"""

    def __init__(self) -> None:
        self._rows: dict[str, ModelProvider] = {}

    def add(self, entity: ModelProvider) -> ModelProvider:
        self._rows[entity.id] = entity
        return entity

    def get(self, entity_id: str) -> ModelProvider | None:
        return self._rows.get(entity_id)

    def list(self, **filters: Any) -> list[ModelProvider]:
        return [
            row
            for row in self._rows.values()
            if all(getattr(row, field) == value for field, value in filters.items())
        ]

    def list_by_tenant(self, tenant_id: str) -> list[ModelProvider]:
        return [row for row in self._rows.values() if row.tenant_id == tenant_id]

    def update(self, entity: ModelProvider) -> ModelProvider:
        self._rows[entity.id] = entity
        return entity

    def delete(self, entity: ModelProvider) -> None:
        self._rows.pop(entity.id, None)


class FakeModelRepository:
    """内存 Model 仓储（结构型满足领域 Protocol）。"""

    def __init__(self) -> None:
        self._rows: dict[str, Model] = {}

    def add(self, entity: Model) -> Model:
        self._rows[entity.id] = entity
        return entity

    def get(self, entity_id: str) -> Model | None:
        return self._rows.get(entity_id)

    def list(self, **filters: Any) -> list[Model]:
        return [
            row
            for row in self._rows.values()
            if all(getattr(row, field) == value for field, value in filters.items())
        ]

    def list_by_provider(self, provider_id: str) -> list[Model]:
        return [row for row in self._rows.values() if row.provider_id == provider_id]

    def update(self, entity: Model) -> Model:
        self._rows[entity.id] = entity
        return entity

    def delete(self, entity: Model) -> None:
        self._rows.pop(entity.id, None)


@pytest.fixture()
def service() -> ModelCatalogService:
    return ModelCatalogService(
        provider_repository=FakeProviderRepository(),
        model_repository=FakeModelRepository(),
        registry=ModelRegistry(),
    )


def test_fakes_satisfy_domain_protocols() -> None:
    assert isinstance(FakeProviderRepository(), ModelProviderRepository)
    assert isinstance(FakeModelRepository(), ModelRepository)


def test_register_and_list_providers(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="OpenAI", provider_type="openai")
    listed = service.list_providers(TENANT_A)
    assert [item.id for item in listed] == [provider.id]
    assert listed[0].status == "ACTIVE"


def test_provider_tenant_isolation(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="A", provider_type="ollama")
    service.register_provider(tenant_id=TENANT_B, name="B", provider_type="ollama")
    assert len(service.list_providers(TENANT_A)) == 1
    with pytest.raises(DomainError) as excinfo:
        service.get_provider(provider.id, tenant_id=TENANT_B)
    assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_invalid_provider_name_and_type(service: ModelCatalogService) -> None:
    with pytest.raises(DomainError) as excinfo:
        service.register_provider(tenant_id=TENANT_A, name="  ", provider_type="openai")
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR
    with pytest.raises(DomainError) as excinfo:
        service.register_provider(tenant_id=TENANT_A, name="x", provider_type="unknown")
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_disable_provider(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="x", provider_type="openai")
    disabled = service.disable_provider(provider.id, tenant_id=TENANT_A)
    assert disabled.status == MODEL_PROVIDER_STATUS_DISABLED


def test_register_and_list_models(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="x", provider_type="openai")
    model = service.register_model(
        tenant_id=TENANT_A, provider_id=provider.id, name="gpt-4o", context_window=128000
    )
    listed = service.list_models(provider.id, tenant_id=TENANT_A)
    assert [item.id for item in listed] == [model.id]
    assert listed[0].context_window == 128000
    assert listed[0].type == "CHAT"


def test_register_model_requires_provider(service: ModelCatalogService) -> None:
    with pytest.raises(DomainError) as excinfo:
        service.register_model(tenant_id=TENANT_A, provider_id="missing", name="m")
    assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_model_tenant_isolation_and_disable(service: ModelCatalogService) -> None:
    provider = service.register_provider(tenant_id=TENANT_A, name="x", provider_type="openai")
    model = service.register_model(tenant_id=TENANT_A, provider_id=provider.id, name="m")
    with pytest.raises(DomainError):
        service.get_model(model.id, tenant_id=TENANT_B)
    disabled = service.disable_model(model.id, tenant_id=TENANT_A)
    assert disabled.status == MODEL_STATUS_DISABLED


def test_register_runtime_provider_into_registry() -> None:
    registry = ModelRegistry()
    service = ModelCatalogService(
        provider_repository=FakeProviderRepository(),
        model_repository=FakeModelRepository(),
        registry=registry,
    )
    stub = StubModelProvider(name="stub")
    service.register_runtime_provider("stub", stub)
    assert "stub" in registry
    assert registry.get("stub") is stub


def test_register_runtime_provider_without_registry() -> None:
    service = ModelCatalogService(
        provider_repository=FakeProviderRepository(),
        model_repository=FakeModelRepository(),
    )
    with pytest.raises(DomainError) as excinfo:
        service.register_runtime_provider("stub", StubModelProvider())
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
