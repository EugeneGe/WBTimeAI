"""``OpenAICompatibleProvider``——OpenAI 兼容端点（自定义 ``base_url``）。

覆盖 vLLM / 中转 / 自建，以及复用 OpenAI 协议族（DeepSeek / Qwen）的厂商。
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from ..types import ChatMessage, ChatResult, Embedding
from .base import HttpModelProvider, messages_to_dicts, normalize_usage

__all__ = ["OpenAICompatibleProvider"]

_DEFAULT_BASE_URL = "http://localhost:8000/v1"


class OpenAICompatibleProvider(HttpModelProvider):
    """OpenAI 兼容协议 Provider（``/chat/completions`` + ``/embeddings``）。"""

    provider_name = "openai_compatible"
    supports_chat = True
    supports_stream = True
    supports_embeddings = True

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        api_key: str | None = None,
        name: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 0,
        default_chat_model: str = "",
        default_embedding_model: str = "",
    ) -> None:
        super().__init__(
            name=name or self.provider_name,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            client=client,
            extra_headers=extra_headers,
            max_retries=max_retries,
        )
        self.default_chat_model = default_chat_model
        self.default_embedding_model = default_embedding_model

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # -- Chat ----------------------------------------------------------------

    def chat(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        """执行一次对话补全（``POST /chat/completions``）。"""
        model = self._resolve_model(options, self.default_chat_model)
        payload: dict[str, Any] = {"model": model, "messages": messages_to_dicts(messages)}
        self._apply_sampling(payload, options)
        data = self._post_json("/chat/completions", payload)
        choices = data.get("choices") or [{}]
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}
        return ChatResult(
            content=str(message.get("content") or ""),
            model=str(data.get("model") or model),
            finish_reason=choice.get("finish_reason"),
            usage=normalize_usage(data.get("usage")),
        )

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> Iterator[str]:
        """流式会话（SSE ``data:`` 分片）。"""
        model = self._resolve_model(options, self.default_chat_model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "stream": True,
        }
        self._apply_sampling(payload, options)
        for line in self._iter_response_lines("/chat/completions", payload):
            chunk = _sse_payload(line)
            if chunk is None:
                continue
            delta = (chunk.get("choices") or [{}])[0]
            if not isinstance(delta, dict):
                continue
            delta_content = (delta.get("delta") or {}).get("content")
            if delta_content:
                yield str(delta_content)

    # -- Embeddings ----------------------------------------------------------

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Embedding]:
        """计算文本嵌入（``POST /embeddings``）。"""
        model = self._resolve_model(options, self.default_embedding_model)
        data = self._post_json("/embeddings", {"model": model, "input": list(texts)})
        items = data.get("data") or []
        return [
            Embedding(
                vector=[float(value) for value in (item.get("embedding") or [])],
                model=str(data.get("model") or model),
                index=int(item.get("index", position)),
            )
            for position, item in enumerate(items)
            if isinstance(item, dict)
        ]


def _sse_payload(line: str) -> dict[str, Any] | None:
    """解析 SSE ``data:`` 行为 JSON；``[DONE]`` 或非 data 行返回 ``None``。"""
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("data:"):
        stripped = stripped[len("data:") :].strip()
    if not stripped or stripped == "[DONE]":
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
