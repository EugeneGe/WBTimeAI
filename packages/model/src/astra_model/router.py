"""``ModelRouter``（起步级 · 显式路由；设计 §2.3.3 / §5 #2）。

把 ``agent_version.model_config``（``{provider, model, temperature, max_tokens, params}``）
解析为「已注册的 :class:`~astra_model.provider.ModelProvider` 实例 + 具体模型名 + 调用参数」，
供 Runtime Model Executor 使用。

🔴 **仅显式路由**：不做负载均衡 / Fallback / 配额 / 成本控制 / 自动选型（Phase 4 Gateway）；
   未配置 / 未注册 → ``DomainError(CONFIGURATION_ERROR)``，**不静默 fallback**。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from astra_core import DomainError, ErrorCode
from astra_domain import ModelConfig

from .provider import ModelProvider
from .registry import ModelRegistry

if TYPE_CHECKING:
    from .services.provider_resolver import ProviderResolver

__all__ = ["ModelRouter", "ResolvedModel", "build_model_router"]

_DEFAULT_TEMPERATURE = 0.7


class ResolvedModel(NamedTuple):
    """路由解析结果（可解构为 ``(provider, model, params)``）。"""

    provider: ModelProvider
    model: str
    params: dict[str, Any]


class ModelRouter:
    """显式 Model Router（按名解析已注册 Provider）。

    **执行期绑定（M1）**：可选注入 :class:`~astra_model.services.ProviderResolver`；当
    :meth:`resolve` 收到非空 ``tenant_id`` 时，把注册表**原型**绑定为「租户 endpoint +
    解密凭证」的具体实例；``tenant_id`` 缺省（``None``）或未装配 resolver → 完全退回
    Phase 1 行为（返回注册表默认实例，逐字节一致）。
    """

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        provider_resolver: ProviderResolver | None = None,
    ) -> None:
        self._registry = registry
        self._provider_resolver = provider_resolver

    def bind_provider_resolver(self, resolver: ProviderResolver) -> None:
        """装配执行期绑定器（组合根调用；H5 装配唯一出口）。

        以 ``reference`` 语义挂在 **router 对象**上——构建 Router 时（如
        :func:`build_model_router` 经 ``astra_config``）无需知晓 resolver；
        组合根在构造 :class:`~astra_model.services.ProviderResolver` 后回填即可，
        Runtime / Application **零感知**（``AgentRuntime.build`` 无需改签名）。

        Args:
            resolver: 执行期绑定器（非空）。
        """
        self._provider_resolver = resolver

    def resolve(
        self,
        model_config: ModelConfig | dict[str, Any],
        *,
        tenant_id: str | None = None,
        run_id: str | None = None,
    ) -> ResolvedModel:
        """解析 ``model_config`` 为「Provider 实例 + 模型名 + 调用参数」。

        ``tenant_id`` 非空且已装配 ``provider_resolver`` 时，把按名解析出的**原型**经
        :meth:`ProviderResolver.resolve` 绑定为具体实例（携带租户 endpoint + 解密密钥）；
        否则（``tenant_id is None`` 或未装配）返回注册表默认实例（Phase 1 行为）。

        Args:
            model_config: :class:`~astra_domain.value_objects.agent.ModelConfig`
                或等价字典。
            tenant_id: 租户标识（可选；缺省 ＝ Phase 1 行为，不绑定）。
            run_id: 关联 Run 标识（可选；透传供绑定 / 审计）。

        Returns:
            :class:`ResolvedModel`（仍为 ``(provider, model, params)`` 三元组）。

        Raises:
            DomainError: ``provider`` / ``model`` 缺失或非法、Provider 未注册、
                或执行期绑定失败（无租户行 / endpoint 非法 / 需密钥未绑）
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
        prototype = self._registry.get(provider_name)
        # 执行期绑定：仅在携带租户上下文且已装配 resolver 时生效；否则 Phase 1 行为（逐字节一致）。
        provider: ModelProvider = prototype
        if tenant_id is not None and self._provider_resolver is not None:
            provider = self._provider_resolver.resolve(
                provider_name,
                prototype=prototype,
                tenant_id=tenant_id,
                run_id=run_id,
            )
        return ResolvedModel(
            provider=provider,
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
