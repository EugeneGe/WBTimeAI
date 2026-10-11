"""契约套件共享支撑：已覆盖 Provider 清单 + 录制回放装配（不触网）。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from astra_model.providers import (
    AnthropicProvider,
    DeepSeekProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    QwenProvider,
)

#: 契约套件**显式覆盖**的 Provider 名（冻结清单）。
#: 🔴 新增 Provider 未纳入此清单 → ``test_registry_coverage`` 扫描断言失败。
CONTRACTED_PROVIDERS: tuple[str, ...] = (
    "openai",
    "openai_compatible",
    "ollama",
    "anthropic",
    "gemini",
    "deepseek",
    "qwen",
)

CASSETTES_DIR = Path(__file__).resolve().parent / "cassettes"

ProviderFactory = Callable[[httpx.Client], Any]


def _read(name: str, filename: str, fallback: str = "{}") -> str:
    path = CASSETTES_DIR / name / filename
    return path.read_text(encoding="utf-8") if path.is_file() else fallback


def make_handler(name: str) -> Callable[[httpx.Request], httpx.Response]:
    """构造 ``provider`` 专属录制回放 handler（按请求路由到 cassette）。"""
    chat = _read(name, "chat.json")
    stream = _read(name, "stream.txt", "")
    embeddings = _read(name, "embeddings.json")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.lower()
        try:
            body = json.loads(request.content or b"{}")
        except (json.JSONDecodeError, ValueError):
            body = {}
        if "embed" in path:
            return httpx.Response(
                200, text=embeddings, headers={"content-type": "application/json"}
            )
        streaming = bool(body.get("stream")) or "streamgeneratecontent" in path
        if streaming:
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, text=chat, headers={"content-type": "application/json"})

    return handler


_BUILDERS: dict[str, ProviderFactory] = {
    "openai": lambda client: OpenAIProvider(client=client, api_key="sk-contract"),
    "openai_compatible": lambda client: OpenAICompatibleProvider(
        client=client,
        base_url="http://mock.local/v1",
        api_key="sk-contract",
        default_chat_model="compat-chat",
        default_embedding_model="compat-embed",
    ),
    "ollama": lambda client: OllamaProvider(client=client, base_url="http://mock.local"),
    "anthropic": lambda client: AnthropicProvider(client=client, api_key="sk-contract"),
    "gemini": lambda client: GeminiProvider(client=client, api_key="sk-contract"),
    "deepseek": lambda client: DeepSeekProvider(client=client, api_key="sk-contract"),
    "qwen": lambda client: QwenProvider(client=client, api_key="sk-contract"),
}


def build_provider(name: str) -> Any:
    """构造带录制回放 HTTP 客户端的 Provider 实例。"""
    client = httpx.Client(transport=httpx.MockTransport(make_handler(name)))
    return _BUILDERS[name](client)
