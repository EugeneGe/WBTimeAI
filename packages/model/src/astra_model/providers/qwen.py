"""``QwenProvider``（复用 OpenAI 兼容基类）。"""

from __future__ import annotations

import httpx

from .openai_compatible import OpenAICompatibleProvider

__all__ = ["QwenProvider"]

_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenProvider(OpenAICompatibleProvider):
    """通义千问 Provider（DashScope OpenAI 兼容协议）。"""

    provider_name = "qwen"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _QWEN_BASE_URL,
        name: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 0,
        default_chat_model: str = "qwen-plus",
        default_embedding_model: str = "text-embedding-v3",
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
