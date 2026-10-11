"""``OpenAIProvider``——官方 OpenAI（Chat / Embeddings）。

复用 :class:`~astra_model.providers.openai_compatible.OpenAICompatibleProvider` 的
OpenAI 协议实现，仅覆盖默认端点与默认模型。
"""

from __future__ import annotations

import httpx

from .openai_compatible import OpenAICompatibleProvider

__all__ = ["OpenAIProvider"]

_OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(OpenAICompatibleProvider):
    """官方 OpenAI Provider。"""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _OPENAI_BASE_URL,
        name: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 0,
        default_chat_model: str = "gpt-4o",
        default_embedding_model: str = "text-embedding-3-small",
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
