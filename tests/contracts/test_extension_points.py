"""8 个 ExtensionPoint 契约测试（W1b 裁定 §6.1；``pytest.mark.contracts``）。

断言：

1. 每点 ``@runtime_checkable`` 且参考实现 ``isinstance(fake, Protocol)`` 成立（结构化契合）；
2. 每点 ``EXTENSION_POINT_VERSION`` 格式 ``^<point>/v\\d+$``；``SUPPORTED_EXTENSION_POINTS`` 一致；
3. 异常语义：认证失败抛 ``DomainError(UNAUTHORIZED)``；``audit_sink.write`` 抛错 →
   降级 ``AuditRepository`` 落盘（**不静默**）；
4. ``is_compatible_point("auth_provider", "auth_provider/v2") is False``；
5. ``tests/contracts/**`` **无** ``import astra_security``（保抽象纪律）。

🔴 全部 fake 为开源参考实现 / 内联实现，**零商业依赖**。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import (
    AuditEvent,
    AuditLog,
    AuthCredential,
    ExtensionContext,
    Principal,
    SinkHealth,
)
from astra_plugin.extension_points import (
    SUPPORTED_EXTENSION_POINTS,
    AuditSink,
    AuthProvider,
    Connector,
    ModelGateway,
    ModelProviderFactory,
    PolicyEngine,
    SecretProvider,
    UIExtension,
    is_compatible_point,
)
from astra_plugin.extension_points import (
    audit_sink as ep_audit_sink,
)
from astra_plugin.extension_points import (
    auth_provider as ep_auth_provider,
)
from astra_plugin.extension_points import (
    connector as ep_connector,
)
from astra_plugin.extension_points import (
    model_gateway as ep_model_gateway,
)
from astra_plugin.extension_points import (
    model_provider as ep_model_provider,
)
from astra_plugin.extension_points import (
    policy_engine as ep_policy_engine,
)
from astra_plugin.extension_points import (
    secret_provider as ep_secret_provider,
)
from astra_plugin.extension_points import (
    ui_extension as ep_ui_extension,
)
from astra_plugin.reference import (
    AllowAllAuthProvider,
    EchoModelProviderFactory,
    EmptyUIExtension,
    FallbackAuditSink,
    LocalSecretProvider,
    NoopAuditSink,
    NoopConnector,
    NoopModelGateway,
    NoopPolicyEngine,
)

pytestmark = pytest.mark.contracts

_CONTRACTS_DIR = Path(__file__).resolve().parent


# -- 内联 fake（异常语义专用） ------------------------------------------------


class _FailingAuthProvider:
    """认证必失败的提供者（验证 ``DomainError(UNAUTHORIZED)`` 语义）。"""

    def supports(self, scheme: str) -> bool:
        return True

    def authenticate(self, credential: AuthCredential, ctx: ExtensionContext) -> Principal:
        raise DomainError("凭证无效", code=ErrorCode.UNAUTHORIZED)

    def logout(self, principal: Principal) -> None:
        return None


class _FailingAuditSink:
    """写入必失败的落点（验证降级路径）。"""

    def write(self, event: AuditEvent) -> None:
        raise RuntimeError("外部审计落点不可达")

    def flush(self) -> None:
        return None

    def health(self) -> SinkHealth:
        return SinkHealth(ok=False, message="down")


class _RecordingAuditRepository:
    """记录落盘事件的降级仓储（结构契合 ``AuditRepository``）。"""

    def __init__(self) -> None:
        self.records: list[AuditEvent] = []

    def add(self, record: AuditEvent) -> AuditEvent:
        self.records.append(record)
        return record

    def exists_request_id(self, request_id: str) -> bool:
        return any(record.request_id == request_id for record in self.records)

    def list_by_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditEvent]:
        return list(self.records)[:limit]


# -- 1 / 2：结构化契合 + 版本常量 --------------------------------------------


def _fake_instances() -> dict[str, tuple[Any, Any]]:
    """点 → (Protocol, 参考 fake 实例)。"""
    return {
        "auth_provider": (AuthProvider, AllowAllAuthProvider()),
        "policy_engine": (PolicyEngine, NoopPolicyEngine()),
        "audit_sink": (AuditSink, NoopAuditSink()),
        "secret_provider": (SecretProvider, LocalSecretProvider(b"master-key")),
        "model_gateway": (ModelGateway, NoopModelGateway()),
        "model_provider": (ModelProviderFactory, EchoModelProviderFactory()),
        "connector": (Connector, NoopConnector()),
        "ui_extension": (UIExtension, EmptyUIExtension()),
    }


def test_eight_points_are_structurally_satisfied() -> None:
    fakes = _fake_instances()
    assert set(fakes) == set(SUPPORTED_EXTENSION_POINTS)
    for point, (protocol, fake) in fakes.items():
        assert isinstance(fake, protocol), f"{point} 参考实现不符合 Protocol"


def test_extension_point_versions_are_well_formed_and_consistent() -> None:
    modules = {
        "auth_provider": ep_auth_provider,
        "policy_engine": ep_policy_engine,
        "audit_sink": ep_audit_sink,
        "secret_provider": ep_secret_provider,
        "model_gateway": ep_model_gateway,
        "model_provider": ep_model_provider,
        "connector": ep_connector,
        "ui_extension": ep_ui_extension,
    }
    for point, module in modules.items():
        version = module.EXTENSION_POINT_VERSION
        assert re.fullmatch(rf"{point}/v\d+", version), f"{point} 版本格式非法：{version}"
        assert SUPPORTED_EXTENSION_POINTS[point] == version


# -- 3：异常 / 降级语义 ------------------------------------------------------


def test_auth_provider_failure_raises_unauthorized() -> None:
    provider = _FailingAuthProvider()
    assert isinstance(provider, AuthProvider)
    with pytest.raises(DomainError) as excinfo:
        provider.authenticate(AuthCredential(scheme="local"), ExtensionContext(tenant_id="t1"))
    assert excinfo.value.code is ErrorCode.UNAUTHORIZED


def test_audit_sink_write_failure_degrades_to_repository() -> None:
    repository = _RecordingAuditRepository()
    alerts: list[tuple[AuditEvent, Exception]] = []
    sink = FallbackAuditSink(
        _FailingAuditSink(), repository, on_error=lambda event, exc: alerts.append((event, exc))
    )
    event = AuditLog(action="test.action", request_id="req-1")
    sink.write(event)
    # 不静默：降级本地落盘 + 告警。
    assert repository.records == [event]
    assert len(alerts) == 1


# -- 4：兼容判定 --------------------------------------------------------------


def test_incompatible_major_is_rejected() -> None:
    assert is_compatible_point("auth_provider", "auth_provider/v1") is True
    assert is_compatible_point("auth_provider", "auth_provider/v2") is False


def test_unknown_point_is_incompatible() -> None:
    assert is_compatible_point("nope", "nope/v1") is False


# -- 5：抽象纪律 --------------------------------------------------------------


def test_contracts_suite_has_no_security_import() -> None:
    pattern = re.compile(r"^\s*(?:from|import)\s+astra_security\b", re.MULTILINE)
    offenders: list[str] = []
    for path in _CONTRACTS_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert not offenders, f"tests/contracts/** 违规 import astra_security：{offenders}"
