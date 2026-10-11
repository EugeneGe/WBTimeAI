"""``ModelRouter`` 单测（T1-12）：显式路由 + 未配置 / 未注册 → ``CONFIGURATION_ERROR``。

并覆盖 ``ModelRegistry`` 运行时 ``register`` / ``unregister``（总纲 §12 RP-15，向后兼容）。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import ModelConfig
from astra_model import ModelRegistry, ModelRouter, StubModelProvider


def _registry() -> ModelRegistry:
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider())
    return registry


def test_resolve_with_model_config() -> None:
    registry = _registry()
    provider, model_name, params = ModelRouter(registry).resolve(
        ModelConfig(provider="stub", model="stub-model", temperature=0.3, max_tokens=128)
    )
    assert provider is registry.get("stub")
    assert model_name == "stub-model"
    assert params["temperature"] == 0.3
    assert params["max_tokens"] == 128


def test_resolve_with_dict_and_custom_params() -> None:
    provider, model_name, params = ModelRouter(_registry()).resolve(
        {"provider": "stub", "model": "m", "temperature": 0.1, "params": {"top_p": 0.9}}
    )
    assert model_name == "m"
    assert params == {"top_p": 0.9, "temperature": 0.1}
    assert provider is not None


def test_unregistered_provider_raises_configuration_error() -> None:
    with pytest.raises(DomainError) as excinfo:
        ModelRouter(_registry()).resolve(ModelConfig(provider="missing", model="m"))
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_missing_provider_raises_configuration_error() -> None:
    with pytest.raises(DomainError) as excinfo:
        ModelRouter(_registry()).resolve({"model": "m"})
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_missing_model_raises_configuration_error() -> None:
    with pytest.raises(DomainError) as excinfo:
        ModelRouter(_registry()).resolve({"provider": "stub"})
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_invalid_model_config_type() -> None:
    with pytest.raises(DomainError) as excinfo:
        ModelRouter(_registry()).resolve("stub")  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_registry_runtime_register_and_unregister() -> None:
    registry = ModelRegistry()
    provider = StubModelProvider()
    registry.register("stub", provider)
    assert "stub" in registry
    registry.unregister("stub")
    assert "stub" not in registry
    assert registry.names() == []
    # 幂等：重复注销不抛错（向后兼容）。
    registry.unregister("stub")
