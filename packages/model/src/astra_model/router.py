"""``ModelRouter``（起步级 · 显式路由；设计 §2.3.3 / §5 #2）。

把 ``agent_version.model_config``（``{provider, model, temperature, max_tokens, params}``）
解析为「已注册的 :class:`~astra_model.provider.ModelProvider` 实例 + 具体模型名 + 调用参数」，
供 Runtime Model Executor 使用。

🔴 **仅显式路由**：不做负载均衡 / Fallback / 配额 / 成本控制 / 自动选型（Phase 4 Gateway）；
   未配置 / 未注册 → ``DomainError(CONFIGURATION_ERROR)``，**不静默 fallback**。
"""

from __future__ import annotations

from typing import Any, NamedTuple

from astra_core import DomainError, ErrorCode
from astra_domain import ModelConfig

from .provider import ModelProvider
from .registry import ModelRegistry

__all__ = ["ModelRouter", "ResolvedModel", "build_model_router"]

_DEFAULT_TEMPERATURE = 0.7


class ResolvedModel(NamedTuple):
    """路由解析结果（可解构为 ``(provider, model, params)``）。"""

    provider: ModelProvider
    model: str
    params: dict[str, Any]


class ModelRouter:
    """显式 Model Router（按名解析已注册 Provider）。"""

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def resolve(self, model_config: ModelConfig | dict[str, Any]) -> ResolvedModel:
        """解析 ``model_config`` 为「Provider 实例 + 模型名 + 调用参数」。

        Args:
            model_config: :class:`~astra_domain.value_objects.agent.ModelConfig`
                或等价字典。

        Returns:
            :class:`ResolvedModel`。

        Raises:
            DomainError: ``provider`` / ``model`` 缺失或非法、Provider 未注册
                （``CONFIGURATION_ERROR``）；**不 fallback**。
        """
        provider_name, model_name, temperature, max_tokens, params = _extract(model_config)
        if not provider_name:
            raise _config_error("model_config 缺少 provider", field="provider")
        if not model_name:
            raise _config_error("model_config 缺少 model", field="model")
        if provider_name not in self._registry:
            raise DomainError(
                f"Provider 未注册：{provider_name}",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"provider": provider_name},
            )
        call_params: dict[str, Any] = dict(params)
        call_params["temperature"] = temperature
        if max_tokens is not None:
            call_params["max_tokens"] = max_tokens
        return ResolvedModel(
            provider=self._registry.get(provider_name),
            model=model_name,
            params=call_params,
        )


def _config_error(message: str, *, field: str) -> DomainError:
    return DomainError(message, code=ErrorCode.CONFIGURATION_ERROR, data={"field": field})


def _extract(
    model_config: ModelConfig | dict[str, Any],
) -> tuple[str, str, float, int | None, dict[str, Any]]:
    """归一化 ``model_config`` 为 ``(provider, model, temperature, max_tokens, params)``。"""
    if isinstance(model_config, ModelConfig):
        return (
            model_config.provider.strip(),
            model_config.model.strip(),
            float(model_config.temperature),
            model_config.max_tokens,
            dict(model_config.params),
        )
    if isinstance(model_config, dict):
        params = model_config.get("params")
        max_tokens = model_config.get("max_tokens")
        try:
            temperature = float(model_config.get("temperature", _DEFAULT_TEMPERATURE))
            parsed_max_tokens = int(max_tokens) if max_tokens is not None else None
        except (TypeError, ValueError) as exc:
            raise _config_error("model_config 采样参数非法", field="temperature") from exc
        return (
            str(model_config.get("provider", "")).strip(),
            str(model_config.get("model", "")).strip(),
            temperature,
            parsed_max_tokens,
            dict(params) if isinstance(params, dict) else {},
        )
    raise _config_error(
        "model_config 类型非法（需 ModelConfig 或 dict）",
        field="model_config",
    )


def build_model_router(settings: Any) -> ModelRouter:
    """装配起步级 :class:`ModelRouter`（config 装配入口；**无 mode 分支**）。

    由 ``astra_config.providers._build_optional(module="astra_model.router",
    factory="build_model_router")`` 单参调用装配进 ``providers.model_router``。

    内部使用与 :func:`astra_model.providers.build_model_providers` **同源**的
    ``register_builtin_providers`` 构造注册表（含 ``stub`` + 内置 Provider），
    两者内容一致；**运行时以 ``providers.model_router`` 的路由为准**
    （裁定 §6.2 Q-note-1）。

    🔴 **C-01**：本工厂**不含任何** ``if mode == ...``。

    Args:
        settings: 生效配置（本工厂未使用其字段；保留以对齐单参约定）。

    Returns:
        以内置注册表构造的 :class:`ModelRouter`。
    """
    from .providers import build_model_providers

    return ModelRouter(build_model_providers(settings))
