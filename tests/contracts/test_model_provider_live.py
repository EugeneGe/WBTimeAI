"""真实 Provider 联调契约（G3 收口）：``@pytest.mark.provider_live``，**默认不跑**。

本模块把 ``provider_live`` marker 从「有插槽没插头」变为**真能跑**：参数化覆盖全部已注册
Provider，对**真实端点**发起调用并断言 chat / stream / embeddings / count_tokens / 错误路径
契约。**未配置的 Provider 一律 ``pytest.skip``**，故 CI 永不因缺密钥而红。

配置约定（每个 Provider 一组环境变量；命名一致：``ASTRA_LIVE_<PROVIDER>_<FIELD>``）
--------------------------------------------------------------------------------
``<PROVIDER>`` 取 **provider 注册名的大写**：``OPENAI`` / ``OPENAI_COMPATIBLE`` / ``OLLAMA`` /
``ANTHROPIC`` / ``GEMINI`` / ``DEEPSEEK`` / ``QWEN``。

- ``ASTRA_LIVE_<PROVIDER>_CHAT_MODEL``：**总是必填**（缺则 skip）——chat 模型名。
- ``ASTRA_LIVE_<PROVIDER>_API_KEY``：**需密钥的 Provider 必填**（缺则 skip）——API Key。
- ``ASTRA_LIVE_<PROVIDER>_BASE_URL``：``openai_compatible`` 必填，其余可选——覆盖默认端点。
- ``ASTRA_LIVE_<PROVIDER>_EMBED_MODEL``：可选——embeddings 模型名（缺省用 Provider 默认值）。

需密钥的 Provider：``openai`` / ``anthropic`` / ``gemini`` / ``deepseek`` / ``qwen``（即
``requires_api_key=True``）；``ollama`` / ``openai_compatible`` 视为**免密钥**（本地 / 自建
可无鉴权）。

运行方式
--------------------------------------------------------------------------------
```bash
# 默认：live 用例不被收集（pyproject addopts 已含 -m "not provider_live"）
uv run pytest tests/contracts -q

# 显式收集并运行全部已配置 Provider 的真实联调
uv run pytest tests/contracts -m provider_live -q

# 仅运行某个 Provider（参数 id = provider 名）
uv run pytest tests/contracts -m provider_live -k deepseek -q
```

🔴 纪律
--------------------------------------------------------------------------------
- **绝不硬编任何密钥**；密钥只从环境变量读取，**不落盘 / 不落日志 / 不回显**（断言含泄漏守护）；
- 未配置 → ``skip``（不是 ``xfail`` / 不是假绿）；服务端「明确不支持」→ **如实**断言明确错误，
  绝不静默返回空结果。
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from astra_model.providers import (
    AnthropicProvider,
    DeepSeekProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    QwenProvider,
)
from astra_model.providers.base import ProviderError
from astra_model.types import ChatMessage

pytestmark = pytest.mark.provider_live

#: 环境变量统一前缀。
_ENV_PREFIX = "ASTRA_LIVE"

#: 错误路径用的哨兵密钥（**明显无效**；用于验证「不回显 / 不泄漏」）。
_SENTINEL_BAD_KEY = "astra-live-invalid-key-0000-do-not-use"

#: 确定性最小对话（``temperature=0``；要求极短输出，利于 chat 与 stream 语义比对）。
_MESSAGES = [
    ChatMessage(
        role="system",
        content="You are a terse assistant. Answer with a single short word.",
    ),
    ChatMessage(role="user", content="Reply with the single word: pong"),
]


def _env(name: str) -> str:
    """读取环境变量（去除首尾空白；缺失返回空串）。"""
    return os.environ.get(name, "").strip()


def _norm(text: str) -> str:
    """归一化文本（折叠空白），用于 chat 与 stream 语义比对。"""
    return " ".join(text.split())


@dataclass(frozen=True)
class LiveProviderSpec:
    """单个 Provider 的真实联调装配描述。

    Attributes:
        name: Provider 注册名（亦作参数 id，供 ``-k`` 筛选）。
        provider_cls: Provider 实现类。
        requires_api_key: 是否必须提供 ``API_KEY`` 才视为已配置。
        supports_embeddings: 类能力声明（决定 embeddings 断言分支）。
        env_prefix: 该 Provider 的环境变量前缀（``ASTRA_LIVE_<PROVIDER>``）。
        required_envs: 判定「已配置」所必需的环境变量名（缺一即 skip）。
    """

    name: str
    provider_cls: type
    requires_api_key: bool
    supports_embeddings: bool
    env_prefix: str
    required_envs: tuple[str, ...]

    @property
    def base_url(self) -> str | None:
        """``ASTRA_LIVE_<PROVIDER>_BASE_URL`` 的值（缺省 ``None`` → 用类默认端点）。"""
        return _env(f"{self.env_prefix}_BASE_URL") or None

    @property
    def api_key(self) -> str | None:
        """``ASTRA_LIVE_<PROVIDER>_API_KEY`` 的值（缺省 ``None``）。"""
        return _env(f"{self.env_prefix}_API_KEY") or None

    @property
    def chat_model(self) -> str:
        """``ASTRA_LIVE_<PROVIDER>_CHAT_MODEL`` 的值。"""
        return _env(f"{self.env_prefix}_CHAT_MODEL")

    @property
    def embed_model(self) -> str | None:
        """``ASTRA_LIVE_<PROVIDER>_EMBED_MODEL`` 的值（缺省 ``None`` → 用类默认值）。"""
        return _env(f"{self.env_prefix}_EMBED_MODEL") or None

    @property
    def missing(self) -> list[str]:
        """缺失的必需环境变量名列表（为空表示已配置）。"""
        return [name for name in self.required_envs if not _env(name)]

    def build(self, *, api_key: str | None = None) -> Any:
        """按本描述构造 Provider 实例（仅透传类 ``__init__`` 实际接受的参数）。

        Args:
            api_key: 覆盖密钥（``None`` → 用环境变量 / 类默认）。错误路径测试传哨兵密钥。

        Returns:
            真实 :class:`~astra_model.providers.base.HttpModelProvider` 实例。
        """
        candidates: dict[str, Any] = {
            "base_url": self.base_url,
            "api_key": self.api_key if api_key is None else api_key,
            "default_chat_model": self.chat_model,
            "default_embedding_model": self.embed_model,
        }
        accepted = inspect.signature(self.provider_cls.__init__).parameters
        kwargs = {
            key: value
            for key, value in candidates.items()
            if key in accepted and value not in (None, "")
        }
        return self.provider_cls(**kwargs)


def _spec(
    name: str,
    provider_cls: type,
    *,
    requires_api_key: bool,
    require_base_url: bool = False,
) -> LiveProviderSpec:
    """构造 Provider 联调描述（按命名约定推导必需环境变量）。"""
    env_prefix = f"{_ENV_PREFIX}_{name.upper()}"
    required = [f"{env_prefix}_CHAT_MODEL"]
    if requires_api_key:
        required.append(f"{env_prefix}_API_KEY")
    if require_base_url:
        required.append(f"{env_prefix}_BASE_URL")
    return LiveProviderSpec(
        name=name,
        provider_cls=provider_cls,
        requires_api_key=requires_api_key,
        supports_embeddings=bool(getattr(provider_cls, "supports_embeddings", True)),
        env_prefix=env_prefix,
        required_envs=tuple(required),
    )


#: 真实联调覆盖清单（与 :data:`tests.contracts.support.CONTRACTED_PROVIDERS` 同名同序）。
LIVE_PROVIDERS: tuple[LiveProviderSpec, ...] = (
    _spec("openai", OpenAIProvider, requires_api_key=True),
    _spec(
        "openai_compatible",
        OpenAICompatibleProvider,
        requires_api_key=False,
        require_base_url=True,
    ),
    _spec("ollama", OllamaProvider, requires_api_key=False),
    _spec("anthropic", AnthropicProvider, requires_api_key=True),
    _spec("gemini", GeminiProvider, requires_api_key=True),
    _spec("deepseek", DeepSeekProvider, requires_api_key=True),
    _spec("qwen", QwenProvider, requires_api_key=True),
)


@pytest.fixture(params=[pytest.param(spec, id=spec.name) for spec in LIVE_PROVIDERS])
def live_spec(request: pytest.FixtureRequest) -> LiveProviderSpec:
    """参数化：每个 Provider 的联调描述（未配置时由 ``live_provider`` skip）。"""
    return request.param


@pytest.fixture()
def live_provider(live_spec: LiveProviderSpec) -> Iterator[Any]:
    """构造**真实**（非 MockTransport）Provider 实例；未配置则 ``skip``。"""
    if live_spec.missing:
        pytest.skip(f"未配置 {live_spec.name}（缺：{', '.join(live_spec.missing)}）")
    instance = live_spec.build()
    try:
        yield instance
    finally:
        instance.close()


# -- chat / stream ---------------------------------------------------------------


def test_live_chat(live_provider: Any, live_spec: LiveProviderSpec) -> None:
    """``chat()`` 返回非空文本，且 ``model`` / ``finish_reason`` 合理。"""
    result = live_provider.chat(_MESSAGES, model=live_spec.chat_model, temperature=0)
    assert isinstance(result.content, str)
    assert result.content.strip(), "chat 返回空文本"
    assert result.model, "chat 未回填 model"
    # finish_reason 允许为 None（部分服务端不回填），但若存在须为非空字符串。
    assert result.finish_reason is None or str(result.finish_reason).strip()


def test_live_stream(live_provider: Any, live_spec: LiveProviderSpec) -> None:
    """``stream()`` 产出增量分片，且拼接结果与 ``chat()`` **语义一致**（归一化后互相包含）。"""
    chunks = list(live_provider.stream(_MESSAGES, model=live_spec.chat_model, temperature=0))
    assert chunks, "stream 未产出任何分片"
    joined = "".join(chunks)
    assert joined.strip(), "stream 拼接结果为空"

    chat_result = live_provider.chat(_MESSAGES, model=live_spec.chat_model, temperature=0)
    streamed = _norm(joined)
    chatted = _norm(chat_result.content)
    assert streamed and chatted, "chat / stream 归一化后不应为空"
    # 语义一致：逐字相等，或一次为另一次的子串（容忍服务端轻微非确定性）。
    assert (
        streamed == chatted or streamed in chatted or chatted in streamed
    ), f"stream 与 chat 语义不一致：stream={streamed!r} chat={chatted!r}"


# -- embeddings ------------------------------------------------------------------


def test_live_embeddings(live_provider: Any, live_spec: LiveProviderSpec) -> None:
    """``embeddings()``：支持则等长且非空；不支持则**如实**抛明确错误（不静默）。"""
    if not live_provider.supports_embeddings:
        # 能力声明为不支持 → 必须抛明确 ``ProviderError``，不得静默返回空结果。
        with pytest.raises(ProviderError):
            live_provider.embeddings(["alpha"], model=live_spec.embed_model or "unsupported")
        return

    embed_model = live_spec.embed_model or getattr(live_provider, "default_embedding_model", "")
    if not embed_model:
        pytest.skip(f"{live_spec.name} 未配置 embeddings 模型（该项可选）")

    texts = ["alpha", "beta gamma"]
    try:
        vectors = live_provider.embeddings(texts, model=embed_model)
    except ProviderError as exc:
        # 仅容忍「服务端**明确**不支持 embeddings」——归一化为**非可重试**的确定性错误
        # （如 ``MODEL_CAPABILITY_NOT_SUPPORTED`` → ``retryable=False``，如实标注、非静默）。
        # 🔴 瞬态错误（503 / 429 / timeout → ``retryable=True``）**必须冒泡**，
        # 不得误判为「不支持」——否则会把网络/服务端抖动伪装成假绿，或反之造成假红。
        if exc.retryable:
            raise
        return

    assert len(vectors) == len(texts), "embeddings 返回数量应与输入等长"
    dim = len(vectors[0].vector)
    assert dim > 0, "embeddings 向量不应为空"
    for index, embedding in enumerate(vectors):
        assert len(embedding.vector) == dim, "同批 embeddings 维度应一致"
        assert embedding.index == index


# -- count_tokens ----------------------------------------------------------------


def test_live_count_tokens_deterministic(live_provider: Any) -> None:
    """``count_tokens()`` 确定性（本地估算：同输入两次一致；空串为 0）。"""
    first = live_provider.count_tokens("one two three")
    second = live_provider.count_tokens("one two three")
    assert first.count == second.count >= 0
    assert first.model == live_provider.name
    assert live_provider.count_tokens("").count == 0


# -- 错误路径：错 key → 明确、非可重试、不泄漏 -----------------------------------


def test_live_error_bad_key(live_spec: LiveProviderSpec) -> None:
    """错密钥 → ``ProviderError.retryable=False`` 且**不回显**密钥。

    若端点未强制鉴权（返回成功），本用例同样通过（不误报）；核心断言是「不泄漏」。
    """
    if not live_spec.requires_api_key:
        pytest.skip(f"{live_spec.name} 视为免密钥，无错 key 路径")
    if live_spec.missing:
        pytest.skip(f"未配置 {live_spec.name}（缺：{', '.join(live_spec.missing)}）")

    provider = live_spec.build(api_key=_SENTINEL_BAD_KEY)
    try:
        try:
            provider.chat(_MESSAGES, model=live_spec.chat_model, temperature=0)
        except ProviderError as exc:
            assert exc.retryable is False, "鉴权失败应为非可重试"
            assert _SENTINEL_BAD_KEY not in str(exc), "错误信息不得回显密钥"
            assert _SENTINEL_BAD_KEY not in repr(exc.data), "错误 data 不得回显密钥"
    finally:
        provider.close()


# -- 错误归一化（确定性；无需真实网络） ------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_retryable"),
    [
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
    ],
)
def test_retryable_status_mapping(status: int, expected_retryable: bool) -> None:
    """HTTP 状态 → ``ProviderError.retryable`` 映射正确（429/5xx 可重试，其余不可）。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "synthetic"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        client=client,
        base_url="http://mock.local/v1",
        api_key="sk-contract",
        default_chat_model="mock-chat",
    )
    try:
        with pytest.raises(ProviderError) as excinfo:
            provider.chat(_MESSAGES, model="mock-chat")
        assert excinfo.value.http_status == status
        assert excinfo.value.retryable is expected_retryable
    finally:
        client.close()
