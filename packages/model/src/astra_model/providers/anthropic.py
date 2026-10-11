"""``AnthropicProvider``——Claude（Messages API）。

Anthropic 无 Embeddings API；``supports_embeddings=False``，调用 ``embeddings()``
抛明确错误（契约套件按能力断言，不误判为「未实现」）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from ..types import ChatMessage, ChatResult, Embedding
from .base import HttpModelProvider, ProviderError, normalize_usage

__all__ = ["AnthropicProvider"]

_DEFAULT_BASE_URL = "https://api.anthropic.com"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 1024


class AnthropicProvider(HttpModelProvider):
    """Anthropic Claude Provider（``POST /v1/messages``）。"""

    provider_name = "anthropic"
    supports_embeddings = False

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        name: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 0,
        default_chat_model: str = "claude-3-5-sonnet",
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

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["anthropic-version"] = _ANTHROPIC_VERSION
        headers.setdefault("content-type", "application/json")
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _messages_payload(
        self, messages: Sequence[ChatMessage], options: dict[str, Any]
    ) -> dict[str, Any]:
        system_parts = [message.content for message in messages if message.role == "system"]
        conversation = [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": self._resolve_model(options, self.default_chat_model),
            "max_tokens": int(options.get("max_tokens") or _DEFAULT_MAX_TOKENS),
            "messages": conversation,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        for key in ("temperature", "top_p", "stop"):
            if options.get(key) is not None:
                payload[key] = options[key]
        return payload

    def chat(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        """执行一次对话补全（``POST /v1/messages``）。"""
        payload = self._messages_payload(messages, options)
        data = self._post_json("/v1/messages", payload)
        blocks = data.get("content") or []
        text = "".join(
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return ChatResult(
            content=text,
            model=str(data.get("model") or payload["model"]),
            finish_reason=data.get("stop_reason"),
            usage=normalize_usage(
                {
                    "prompt_tokens": (data.get("usage") or {}).get("input_tokens"),
                    "completion_tokens": (data.get("usage") or {}).get("output_tokens"),
                }
            ),
        )

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> Iterator[str]:
        """流式会话（SSE ``content_block_delta`` 分片）。"""
        payload = self._messages_payload(messages, options)
        payload["stream"] = True
        for line in self._iter_response_lines("/v1/messages", payload):
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            raw = stripped[len("data:") :].strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "content_block_delta":
                text = (event.get("delta") or {}).get("text")
                if text:
                    yield str(text)
            elif event.get("type") == "message_stop":
                break

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Embedding]:
        """Anthropic 无 Embeddings API（明确报错，不静默返回空）。"""
        raise ProviderError(
            "Anthropic 不支持 Embeddings",
            retryable=False,
            data={"provider": self.name, "capability": "embeddings"},
        )
