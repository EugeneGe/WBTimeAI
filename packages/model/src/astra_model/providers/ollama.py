"""``OllamaProvider``——本地推理（``localhost:11434``，社区零成本首选）。

使用 Ollama 原生 HTTP 协议（``/api/chat`` + ``/api/embeddings``）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from ..types import ChatMessage, ChatResult, Embedding
from .base import HttpModelProvider, messages_to_dicts, normalize_usage

__all__ = ["OllamaProvider"]

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(HttpModelProvider):
    """Ollama 本地推理 Provider。"""

    provider_name = "ollama"
    #: 本地推理**无需** API Key（M1：执行期绑定对 ``requires_api_key=False`` 不强制凭证）。
    requires_api_key = False

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
        default_chat_model: str = "llama3",
        default_embedding_model: str = "nomic-embed-text",
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

    def chat(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        """执行一次对话补全（``POST /api/chat``，``stream=false``）。"""
        model = self._resolve_model(options, self.default_chat_model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "stream": False,
        }
        ollama_options = _ollama_options(options)
        if ollama_options:
            payload["options"] = ollama_options
        data = self._post_json("/api/chat", payload)
        message = data.get("message") or {}
        usage = normalize_usage(
            {
                "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count"),
            }
        )
        return ChatResult(
            content=str(message.get("content") or ""),
            model=str(data.get("model") or model),
            finish_reason=data.get("done_reason") or ("stop" if data.get("done") else None),
            usage=usage,
        )

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> Iterator[str]:
        """流式会话（JSONL 分片：``{"message": {"content": ...}, "done": ...}``）。"""
        model = self._resolve_model(options, self.default_chat_model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "stream": True,
        }
        ollama_options = _ollama_options(options)
        if ollama_options:
            payload["options"] = ollama_options
        for line in self._iter_response_lines("/api/chat", payload):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                chunk = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue
            content = (chunk.get("message") or {}).get("content")
            if content:
                yield str(content)
            if chunk.get("done"):
                break

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Embedding]:
        """计算文本嵌入（``POST /api/embeddings``，逐条）。"""
        model = self._resolve_model(options, self.default_embedding_model)
        embeddings: list[Embedding] = []
        for index, text in enumerate(texts):
            data = self._post_json("/api/embeddings", {"model": model, "prompt": text})
            vector = data.get("embedding") or []
            embeddings.append(
                Embedding(
                    vector=[float(value) for value in vector],
                    model=str(data.get("model") or model),
                    index=index,
                )
            )
        return embeddings


def _ollama_options(options: dict[str, Any]) -> dict[str, Any]:
    """把采样参数映射为 Ollama ``options`` 段。"""
    mapping = {"temperature": "temperature", "max_tokens": "num_predict", "top_p": "top_p"}
    return {target: options[key] for key, target in mapping.items() if options.get(key) is not None}
