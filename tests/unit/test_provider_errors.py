"""Provider 错误归一化单测（T1-11）：429 / 5xx / timeout → 可重试标记。

使用 ``httpx.MockTransport`` 注入确定性响应，不触网。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from astra_model.providers import GeminiProvider, OpenAIProvider
from astra_model.providers.base import ProviderError
from astra_model.types import ChatMessage

_Handler = Callable[[httpx.Request], httpx.Response]

_MESSAGES = [ChatMessage(role="user", content="ping")]
_PLAINTEXT_KEY = "sk-supersecret-0123456789"
_GEMINI_KEY = "sk-CANARY-GEMINI-0123456789"


def _openai(handler: _Handler) -> OpenAIProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAIProvider(client=client, api_key=_PLAINTEXT_KEY)


def _status_handler(status: int) -> _Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"HTTP {status}"}})

    return handler


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_errors_are_retryable(status: int) -> None:
    provider = _openai(_status_handler(status))
    with pytest.raises(ProviderError) as excinfo:
        provider.chat(_MESSAGES)
    error = excinfo.value
    assert error.retryable is True
    assert error.http_status == status
    assert error.data["retryable"] is True


def test_client_error_is_not_retryable() -> None:
    provider = _openai(_status_handler(400))
    with pytest.raises(ProviderError) as excinfo:
        provider.chat(_MESSAGES)
    assert excinfo.value.retryable is False
    assert excinfo.value.http_status == 400


def test_timeout_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    provider = _openai(handler)
    with pytest.raises(ProviderError) as excinfo:
        provider.chat(_MESSAGES)
    assert excinfo.value.retryable is True


def test_error_never_leaks_api_key() -> None:
    provider = _openai(_status_handler(500))
    with pytest.raises(ProviderError) as excinfo:
        provider.chat(_MESSAGES)
    assert _PLAINTEXT_KEY not in str(excinfo.value)
    assert _PLAINTEXT_KEY not in repr(excinfo.value.data)


def test_count_tokens_is_local_and_deterministic() -> None:
    provider = _openai(_status_handler(500))
    first = provider.count_tokens("one two three four")
    assert first.model == "openai"
    assert first.count == provider.count_tokens("one two three four").count
    assert provider.count_tokens("").count == 0


# -- D1 回归：Gemini 密钥不经 URL（header 传递）+ URL 拼接无畸形 ------------------


def _gemini(handler: _Handler) -> GeminiProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiProvider(client=client, api_key=_GEMINI_KEY, base_url="http://mock.local")


def test_gemini_chat_url_has_no_key_and_is_wellformed() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hi"}]}}]})

    _gemini(handler).chat(_MESSAGES, model="gemini-1.5-pro")
    url = str(seen[0].url)
    assert _GEMINI_KEY not in url
    assert "key=" not in url
    assert "&key=" not in url
    assert url.endswith("/v1beta/models/gemini-1.5-pro:generateContent")
    assert seen[0].headers.get("x-goog-api-key") == _GEMINI_KEY


def test_gemini_stream_url_query_keeps_single_question_mark() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, text='data: {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}\n\n'
        )

    list(_gemini(handler).stream(_MESSAGES, model="gemini-1.5-pro"))
    url = str(seen[0].url)
    assert _GEMINI_KEY not in url
    assert url.endswith("/v1beta/models/gemini-1.5-pro:streamGenerateContent?alt=sse")


def test_gemini_embeddings_url_has_no_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"embedding": {"values": [0.1, 0.2]}})

    _gemini(handler).embeddings(["alpha"], model="text-embedding-004")
    url = str(seen[0].url)
    assert _GEMINI_KEY not in url
    assert "key=" not in url
    assert url.endswith("/v1beta/models/text-embedding-004:embedContent")


def test_gemini_error_logs_and_message_have_no_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _gemini(_status_handler(429))
    with caplog.at_level(logging.INFO, logger="httpx"):
        with pytest.raises(ProviderError) as excinfo:
            provider.chat(_MESSAGES, model="gemini-1.5-pro")
    assert _GEMINI_KEY not in str(excinfo.value)
    assert _GEMINI_KEY not in caplog.text
    assert excinfo.value.retryable is True


def test_gemini_headers_helper_exposes_no_key_in_url() -> None:
    """直接断言 ``_path`` 不含密钥、无畸形 query。"""
    provider: Any = _gemini(_status_handler(500))
    assert provider._path("m", "generateContent") == "/v1beta/models/m:generateContent"
    assert (
        provider._path("m", "streamGenerateContent", extra_query="?alt=sse")
        == "/v1beta/models/m:streamGenerateContent?alt=sse"
    )
    assert provider._path("m", "embedContent", extra_query="alt=sse").endswith("?alt=sse")
