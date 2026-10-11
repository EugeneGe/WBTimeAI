"""模型 Provider 契约测试（以 Stub 跑通四方法）——设计 §3-#11。"""

from __future__ import annotations

from astra_model import ChatMessage, ModelProvider, StubModelProvider


def test_stub_satisfies_protocol() -> None:
    assert isinstance(StubModelProvider(), ModelProvider)


def test_chat_contract() -> None:
    provider = StubModelProvider()
    result = provider.chat([ChatMessage(role="user", content="ping")])
    assert result.content == "[stub] ping"
    assert result.model == "stub"
    assert result.finish_reason == "stop"


def test_stream_contract() -> None:
    provider = StubModelProvider()
    chunks = list(provider.stream([ChatMessage(role="user", content="hello world")]))
    assert len(chunks) == 3
    assert "".join(chunks).strip() == "[stub] hello world"


def test_embeddings_contract() -> None:
    provider = StubModelProvider(dimension=4)
    vectors = provider.embeddings(["a", "b"])
    assert len(vectors) == 2
    assert len(vectors[0].vector) == 4
    assert vectors[0].index == 0
    assert vectors[1].index == 1
    # 确定性：同输入同向量。
    assert provider.embeddings(["a"])[0].vector == vectors[0].vector


def test_count_tokens_contract() -> None:
    provider = StubModelProvider()
    assert provider.count_tokens("one two three").count == 3
    assert provider.count_tokens("").count == 0
