"""M1 执行期 Provider 绑定测试（离线，**不联网 / 不碰 PG**）。

覆盖（对齐 M1 增量设计 §6.2 / 裁定 H4 / H6）：

- **正向**：租户 ``endpoint`` + 解密 ``api_key`` 正确注入，``chat()`` 命中 ``MockTransport``，
  请求头 ``Authorization: Bearer <secret>``；
- **负向**（全部 ``CONFIGURATION_ERROR``，非静默）：无租户行 / 需密钥未绑凭证 /
  endpoint 非法 / provider 未注册；
- **明文不回显**：错误 / ``repr`` / 日志不含密钥；
- ``stub`` 旁路回归（非 HTTP 原型不报错、**不查租户行**）；
- 解密审计动作 ``model.credential.decrypt`` 被写入；
- ``tenant_id is None`` ＝ Phase 1 行为（默认实例，不绑定）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import (
    MODEL_PROVIDER_STATUS_DISABLED,
    ModelConfig,
)
from astra_model import ChatMessage, ModelRegistry, ModelRouter, StubModelProvider
from astra_model.providers import OllamaProvider, OpenAIProvider
from astra_model.services import DECRYPT_AUDIT_ACTION, ProviderResolver, ProviderRuntime

from .fixtures.provider_binding import (
    FAKE_SECRET,
    FakeCredentialDecoder,
    FakeModelProviderRepository,
    RecordingHandler,
    build_recording_client,
    make_row,
)


def _router_for(
    prototype_name: str,
    prototype: object,
    rows: list[object],
    *,
    decoder: FakeCredentialDecoder | None = None,
) -> tuple[FakeModelProviderRepository, FakeCredentialDecoder, list[dict], ModelRouter]:
    """装配「内存仓储 + 伪解密 + ProviderResolver + ModelRouter」测试栈（离线）。"""
    repository = FakeModelProviderRepository(rows=list(rows))  # type: ignore[arg-type]
    actual_decoder = decoder or FakeCredentialDecoder()
    audit_records: list[dict] = []
    runtime = ProviderRuntime(
        provider_repository=repository,
        decoder=actual_decoder,
        audit=audit_records.append,
    )
    resolver = ProviderResolver(provider_repository=repository, provider_runtime=runtime)
    registry = ModelRegistry()
    registry.register(prototype_name, prototype)  # type: ignore[arg-type]
    router = ModelRouter(registry)
    router.bind_provider_resolver(resolver)
    return repository, actual_decoder, audit_records, router


# -- 正向 -------------------------------------------------------------------


def test_positive_binding_injects_endpoint_and_secret() -> None:
    handler = RecordingHandler(content="hi-from-model")
    prototype = OpenAIProvider(client=build_recording_client(handler), api_key=None)
    row = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://tenant.example/v1",
        credential_id="cred-1",
    )
    _, decoder, audit, router = _router_for("openai", prototype, [row])

    provider, model, params = router.resolve(
        ModelConfig(provider="openai", model="gpt-4o"), tenant_id="t1", run_id="run-1"
    )

    assert provider is not prototype  # 产出新实例
    assert provider.base_url == "https://tenant.example/v1"  # 租户 endpoint 生效
    assert model == "gpt-4o"
    assert params["temperature"] == 0.7
    # 原型**不被修改**（绑定仅内存）。
    assert prototype.base_url == "https://api.openai.com/v1"
    assert prototype._api_key is None

    result = provider.chat([ChatMessage(role="user", content="hi")])
    assert result.content == "hi-from-model"
    assert handler.requests[0].headers["authorization"] == f"Bearer {FAKE_SECRET}"
    assert decoder.decrypt_calls == ["cred-1"]


def test_positive_empty_endpoint_falls_back_to_prototype_default() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    row = make_row(tenant_id="t1", provider_type="openai", endpoint=None, credential_id="cred-1")
    _, _, _, router = _router_for("openai", prototype, [row])

    provider, _, _ = router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1")
    assert provider.base_url == "https://api.openai.com/v1"  # 沿用原型默认


def test_positive_ollama_without_credential_gets_none_key() -> None:
    prototype = OllamaProvider(client=build_recording_client(RecordingHandler()))
    row = make_row(
        tenant_id="t1",
        provider_type="ollama",
        endpoint="http://host.docker:11434",
        credential_id=None,
    )
    _, decoder, _, router = _router_for("ollama", prototype, [row])

    provider, _, _ = router.resolve(ModelConfig(provider="ollama", model="llama3"), tenant_id="t1")
    assert provider.base_url == "http://host.docker:11434"
    assert provider._api_key is None
    assert decoder.decrypt_calls == []  # 本地 Provider 无需解密


def test_multi_row_same_type_picks_oldest_active() -> None:
    older = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://old.example/v1",
        credential_id="c-old",
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    newer = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://new.example/v1",
        credential_id="c-new",
        created_at=datetime(2021, 1, 1, tzinfo=UTC),
    )
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    # 注入顺序故意「新在前」，验证按 (created_at, id) 而非插入顺序选取。
    _, decoder, _, router = _router_for("openai", prototype, [newer, older])

    provider, _, _ = router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1")
    assert provider.base_url == "https://old.example/v1"
    assert decoder.decrypt_calls == ["c-old"]


# -- 负向（CONFIGURATION_ERROR，非静默） ------------------------------------


def test_negative_missing_tenant_row() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    _, _, _, router = _router_for("openai", prototype, [])

    with pytest.raises(DomainError) as excinfo:
        router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t-empty")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert excinfo.value.data.get("provider") == "openai"


def test_negative_requires_key_without_credential() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    row = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://t.example/v1",
        credential_id=None,
    )
    _, _, _, router = _router_for("openai", prototype, [row])

    with pytest.raises(DomainError) as excinfo:
        router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert excinfo.value.data.get("field") == "credential_id"


def test_negative_invalid_endpoint() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    row = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="ftp://not-http/v1",
        credential_id="cred-1",
    )
    _, _, _, router = _router_for("openai", prototype, [row])

    with pytest.raises(DomainError) as excinfo:
        router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert excinfo.value.data.get("field") == "endpoint"


def test_negative_unregistered_provider() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    _, _, _, router = _router_for("openai", prototype, [])

    with pytest.raises(DomainError) as excinfo:
        router.resolve(ModelConfig(provider="ghost", model="m"), tenant_id="t1")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert excinfo.value.data.get("provider") == "ghost"


def test_negative_cross_tenant_row_not_used() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    row = make_row(
        tenant_id="other-tenant",
        provider_type="openai",
        endpoint="https://t.example/v1",
        credential_id="cred-1",
    )
    _, _, _, router = _router_for("openai", prototype, [row])

    with pytest.raises(DomainError) as excinfo:
        router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


def test_negative_disabled_row_filtered() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    row = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://t.example/v1",
        credential_id="cred-1",
        status=MODEL_PROVIDER_STATUS_DISABLED,
    )
    _, _, _, router = _router_for("openai", prototype, [row])

    with pytest.raises(DomainError) as excinfo:
        router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1")
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


# -- 明文不回显（H4 / C-07） -------------------------------------------------


def test_plaintext_not_echoed_anywhere(caplog: pytest.LogCaptureFixture) -> None:
    handler = RecordingHandler()
    prototype = OpenAIProvider(client=build_recording_client(handler), api_key=None)
    row = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://t.example/v1",
        credential_id="cred-1",
    )
    _, _, _, router = _router_for("openai", prototype, [row])

    with caplog.at_level(logging.DEBUG):
        provider, _, _ = router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1")
        provider.chat([ChatMessage(role="user", content="hi")])

    # repr / 日志均**不含**明文密钥。
    assert FAKE_SECRET not in repr(provider)
    assert all(FAKE_SECRET not in record.getMessage() for record in caplog.records)

    # 错误信息 / 错误 data 亦不含明文（即便同一租户行绑定过凭证）。
    bad_row = make_row(
        tenant_id="t2", provider_type="openai", endpoint="nope", credential_id="cred-1"
    )
    _, _, _, bad_router = _router_for("openai", prototype, [bad_row])
    with pytest.raises(DomainError) as excinfo:
        bad_router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t2")
    assert FAKE_SECRET not in excinfo.value.message
    assert FAKE_SECRET not in repr(excinfo.value.data)


# -- stub 旁路回归 / Phase 1 行为 -------------------------------------------


def test_stub_prototype_bypasses_binding() -> None:
    stub = StubModelProvider()
    repository, decoder, audit, router = _router_for("stub", stub, [])

    provider, model, params = router.resolve(
        ModelConfig(provider="stub", model="stub-model"), tenant_id="t1"
    )
    assert provider is stub  # 非 HttpModelProvider → 原样返回
    assert model == "stub-model"
    assert repository.list_by_tenant_calls == []  # 不查租户行
    assert decoder.decrypt_calls == []
    assert audit == []


def test_no_tenant_id_is_phase1_behavior() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    row = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://t.example/v1",
        credential_id="cred-1",
    )
    repository, decoder, _, router = _router_for("openai", prototype, [row])

    provider, _, _ = router.resolve(ModelConfig(provider="openai", model="m"))
    assert provider is prototype  # 缺省 tenant_id → 注册表默认实例
    assert repository.list_by_tenant_calls == []
    assert decoder.decrypt_calls == []


def test_unbound_router_without_resolver_keeps_default() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    registry = ModelRegistry()
    registry.register("openai", prototype)
    # 未装配 resolver：即便带 tenant_id 也返回默认实例（装配缺失不报错，向后兼容）。
    provider, _, _ = ModelRouter(registry).resolve(
        ModelConfig(provider="openai", model="m"), tenant_id="t1"
    )
    assert provider is prototype


# -- 解密审计 ---------------------------------------------------------------


def test_decrypt_audit_action_written() -> None:
    prototype = OpenAIProvider(client=build_recording_client(RecordingHandler()), api_key=None)
    row = make_row(
        tenant_id="t1",
        provider_type="openai",
        endpoint="https://t.example/v1",
        credential_id="cred-1",
    )
    _, _, audit, router = _router_for("openai", prototype, [row])

    router.resolve(ModelConfig(provider="openai", model="m"), tenant_id="t1", run_id="run-9")

    assert len(audit) == 1
    assert audit[0]["action"] == DECRYPT_AUDIT_ACTION
    assert audit[0]["tenant_id"] == "t1"
    assert audit[0]["run_id"] == "run-9"
    # 审计载荷**不含**明文密钥。
    assert FAKE_SECRET not in repr(audit[0])
