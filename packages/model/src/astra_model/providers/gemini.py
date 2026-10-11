"""``GeminiProvider``——Google Gemini（Generative Language API）。"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from ..types import ChatMessage, ChatResult, Embedding
from .base import HttpModelProvider, normalize_usage

__all__ = ["GeminiProvider"]

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


class GeminiProvider(HttpModelProvider):
    """Google Gemini Provider。"""

    provider_name = "gemini"

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
        default_chat_model: str = "gemini-1.5-pro",
        default_embedding_model: str = "text-embedding-004",
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
        """密钥经 ``x-goog-api-key`` 请求头传递（**不拼入 URL**，避免明文入日志）。"""
        headers = super()._headers()
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key
        return headers

    def _path(self, model: str, method: str, *, extra_query: str = "") -> str:
        """构造路径（密钥不经 URL；query 拼接无畸形 ``?``/``&``）。"""
        base = f"/v1beta/models/{model}:{method}"
        query = extra_query.strip()
        if not query:
            return base
        if not query.startswith("?"):
            query = f"?{query}"
        return f"{base}{query}"

    def _contents(self, messages: Sequence[ChatMessage]) -> tuple[list[dict[str, Any]], str | None]:
        contents: list[dict[str, Any]] = []
        system_parts: list[str] = []
        for message in messages:
            if message.role == "system":
                system_parts.append(message.content)
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        system = "\n\n".join(system_parts) if system_parts else None
        return contents, system

    def chat(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        """执行一次对话补全（``:generateContent``）。"""
        model = self._resolve_model(options, self.default_chat_model)
        contents, system = self._contents(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        generation = _generation_config(options)
        if generation:
            payload["generationConfig"] = generation
        data = self._post_json(self._path(model, "generateContent"), payload)
        candidate = (data.get("candidates") or [{}])[0]
        text = _first_text(candidate)
        metadata = data.get("usageMetadata") or {}
        return ChatResult(
            content=text,
            model=str(data.get("modelVersion") or model),
            finish_reason=candidate.get("finishReason") if isinstance(candidate, dict) else None,
            usage=normalize_usage(
                {
                    "prompt_tokens": metadata.get("promptTokenCount"),
                    "completion_tokens": metadata.get("candidatesTokenCount"),
                }
            ),
        )

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> Iterator[str]:
        """流式会话（``:streamGenerateContent?alt=sse``）。"""
        model = self._resolve_model(options, self.default_chat_model)
        contents, system = self._contents(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        generation = _generation_config(options)
        if generation:
            payload["generationConfig"] = generation
        path = self._path(model, "streamGenerateContent", extra_query="?alt=sse")
        for line in self._iter_response_lines(path, payload):
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            raw = stripped[len("data:") :].strip()
            if not raw:
                continue
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue
            for candidate in chunk.get("candidates") or []:
                text = _first_text(candidate)
                if text:
                    yield text

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Embedding]:
        """计算文本嵌入（``:embedContent``，逐条）。"""
        model = self._resolve_model(options, self.default_embedding_model)
        embeddings: list[Embedding] = []
        for index, text in enumerate(texts):
            data = self._post_json(
                self._path(model, "embedContent"),
                {"content": {"parts": [{"text": text}]}},
            )
            values = (data.get("embedding") or {}).get("values") or []
            embeddings.append(
                Embedding(
                    vector=[float(value) for value in values],
                    model=model,
                    index=index,
                )
            )
        return embeddings


def _first_text(candidate: Any) -> str:
    """提取候选答案中的首段文本。"""
    if not isinstance(candidate, dict):
        return ""
    parts = (candidate.get("content") or {}).get("parts") or []
    return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))


def _generation_config(options: dict[str, Any]) -> dict[str, Any]:
    """映射采样参数到 ``generationConfig``。"""
    mapping = {"temperature": "temperature", "max_tokens": "maxOutputTokens", "top_p": "topP"}
    return {target: options[key] for key, target in mapping.items() if options.get(key) is not None}
