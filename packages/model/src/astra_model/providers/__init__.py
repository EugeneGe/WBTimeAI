"""真实 Provider 汇总导出 + 内置注册入口（设计 §2.3.2 / §5 #1）。

首批清单（W3 开工前架构裁定已拍板）：

- **P0**：:class:`OpenAIProvider` / :class:`OpenAICompatibleProvider` / :class:`OllamaProvider`；
- **P1**：:class:`AnthropicProvider` / :class:`GeminiProvider` /
  :class:`DeepSeekProvider` / :class:`QwenProvider`（后二者复用 OpenAI 兼容基类）。

🔴 **未落地的 Provider 不得注册**（避免假绿）；真实密钥经 T1-30 收口。
"""

from __future__ import annotations

from typing import Any

from ..registry import ModelRegistry
from ..stub import StubModelProvider
from .anthropic import AnthropicProvider
from .base import ProviderError
from .deepseek import DeepSeekProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openai_compatible import OpenAICompatibleProvider
from .qwen import QwenProvider

__all__ = [
    "ProviderError",
    "OpenAIProvider",
    "OpenAICompatibleProvider",
    "OllamaProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "DeepSeekProvider",
    "QwenProvider",
    "BUILTIN_PROVIDER_NAMES",
    "register_builtin_providers",
    "build_model_providers",
]

#: 内置 Provider 的注册名（顺序稳定：P0 → P1）。
BUILTIN_PROVIDER_NAMES: tuple[str, ...] = (
    "openai",
    "openai_compatible",
    "ollama",
    "anthropic",
    "gemini",
    "deepseek",
    "qwen",
)


def register_builtin_providers(registry: ModelRegistry) -> ModelRegistry:
    """把内置 Provider（无凭证默认实例）注册进 ``registry`` 并返回。

    调用方（组合根 T1-31 / 契约套件）负责替换凭证 / 注入自定义 ``httpx.Client``。

    Args:
        registry: 目标 :class:`~astra_model.registry.ModelRegistry`。

    Returns:
        注册后的同一 ``registry``。
    """
    registry.register("openai", OpenAIProvider())
    registry.register("openai_compatible", OpenAICompatibleProvider())
    registry.register("ollama", OllamaProvider())
    registry.register("anthropic", AnthropicProvider())
    registry.register("gemini", GeminiProvider())
    registry.register("deepseek", DeepSeekProvider())
    registry.register("qwen", QwenProvider())
    return registry


def build_model_providers(settings: Any) -> ModelRegistry:
    """装配真实 Provider 注册表（config 装配入口；**两模式一致，无 mode 分支**）。

    由 ``astra_config.providers._build_optional(module="astra_model.providers",
    factory="build_model_providers")`` 单参调用装配进 ``providers.model_providers``。

    - 注册 ``stub``（确定性回显，供契约测试 / 默认）；
    - 注册内置真实 Provider（openai / openai_compatible / ollama / anthropic /
      gemini / deepseek / qwen），无凭证使用默认实例（真实密钥经 T1-30 收口）。

    🔴 **C-01**：本工厂**不含任何** ``if mode == ...``；mode 分流唯一在
       ``astra_config.providers``。

    Args:
        settings: 生效配置（本工厂未使用其字段；保留以对齐 ``_build_optional`` 单参约定）。

    Returns:
        已注册 stub + 内置 Provider 的 :class:`~astra_model.registry.ModelRegistry`。
    """
    registry = ModelRegistry()
    registry.register("stub", StubModelProvider())
    register_builtin_providers(registry)
    return registry
