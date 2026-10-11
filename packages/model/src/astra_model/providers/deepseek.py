"""``DeepSeekProvider``（复用 OpenAI 兼容基类）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from ..types import Embedding
from .base import ProviderError
from .openai_compatible import OpenAICompatibleProvider

__all__ = ["DeepSeekProvider"]

_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek Provider（OpenAI 兼容协议）。

    DeepSeek 官方不提供 Embeddings 接口，故 ``supports_embeddings=False``。
    """

    provider_name = "deepseek"
    supports_embeddings = False

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _DEEPSEEK_BASE_URL,
        name: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 0,
        default_chat_model: str = "deepseek-chat",
        default_embedding_model: str = "",
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            name=name or self.provider_name,
            timeout=timeout,
            client=client,
            extra_headers=extra_headers,
            max_retries=max_retries,
            default_chat_model=default_chat_model,
            default_embedding_model=default_embedding_model,
        )

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Embedding]:
        """DeepSeek 无 Embeddings API（明确报错，不静默返回空）。"""
        raise ProviderError(
            "DeepSeek 不支持 Embeddings",
            retryable=False,
            data={"provider": self.name, "capability": "embeddings"},
        )
