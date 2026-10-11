"""统一 Provider 契约断言（T1-14）：chat / stream / embeddings / count_tokens。

参数化覆盖**全部已注册 Provider**（:data:`tests.contracts.support.CONTRACTED_PROVIDERS`），
以录制回放离线运行，不依赖真实网络。
"""

from __future__ import annotations

import pytest
from astra_model import ModelProvider
from astra_model.providers.base import ProviderError
from astra_model.types import ChatMessage

pytestmark = pytest.mark.contracts

_MESSAGES = [
    ChatMessage(role="system", content="You are concise."),
    ChatMessage(role="user", content="Say hello"),
]


def test_provider_satisfies_protocol(provider: object) -> None:
    assert isinstance(provider, ModelProvider)


def test_chat_contract(provider: object) -> None:
    result = provider.chat(_MESSAGES, model="contract-model")  # type: ignore[attr-defined]
    assert result.content == "Hello!"
    assert result.model
    assert result.finish_reason


def test_stream_contract(provider: object) -> None:
    chunks = list(provider.stream(_MESSAGES, model="contract-model"))  # type: ignore[attr-defined]
    assert chunks
    assert "".join(chunks) == "Hello!"


def test_count_tokens_contract(provider: object) -> None:
    token_count = provider.count_tokens("one two three")  # type: ignore[attr-defined]
    assert token_count.count >= 0
    assert token_count.model == provider.name  # type: ignore[attr-defined]


def test_embeddings_contract(provider: object) -> None:
    if not provider.supports_embeddings:  # type: ignore[attr-defined]
        with pytest.raises(ProviderError):
            provider.embeddings(["alpha"], model="contract-embed")  # type: ignore[attr-defined]
        return
    vectors = provider.embeddings(["alpha"], model="contract-embed")  # type: ignore[attr-defined]
    assert len(vectors) == 1
    assert vectors[0].vector
    assert vectors[0].index == 0
