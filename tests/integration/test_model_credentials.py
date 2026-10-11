"""模型凭证复用集成测试（W6 / T1-30；设计 §2.3.5；裁定 Q8/A32；C-07）。

覆盖：

- 凭证加密落库、对外**仅掩码**；
- Provider **仅存引用**（``credential_id``），不复制密文；
- 解密经 ``ProviderRuntime`` **显式且可审计**（写 ``audit_log``，明文仅内存）；
- **不建** ``model_credential`` 表（复用 ``credential`` 表）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, select

#: 具辨识度的明文（确保不与掩码 / 日志偶然重合）。
_PLAINTEXT = "sk-live-MODELCRED-0123456789abcdef-ZYX"


def _save_credential(client: Any, headers: dict[str, str], provider: str) -> str:
    response = client.post(
        "/api/v1/models/credentials",
        headers=headers,
        json={"provider": provider, "key_type": "api_key", "value": _PLAINTEXT},
    )
    assert response.status_code == 201, response.text
    assert _PLAINTEXT not in response.text
    return response.json()["data"]["id"]


def _register_provider(client: Any, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/api/v1/models/providers",
        headers=headers,
        json={"name": "openai", "provider_type": "openai"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_no_model_credential_table(client: Any, auth_headers: dict[str, str]) -> None:
    """**不建** ``model_credential`` 表（复用 ``credential``，A32）。"""
    engine = client.app.state.services.providers.database.engine
    assert "model_credential" not in inspect(engine).get_table_names()


def test_bind_stores_reference_only_and_masks(client: Any, auth_headers: dict[str, str]) -> None:
    """绑定仅写 ``credential_id`` 引用；凭证列表仅掩码。"""
    provider = _register_provider(client, auth_headers)
    credential_id = _save_credential(client, auth_headers, "openai")

    bound = client.post(
        f"/api/v1/models/providers/{provider['id']}/credential",
        headers=auth_headers,
        json={"credential_id": credential_id},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["data"]["credential_id"] == credential_id
    assert _PLAINTEXT not in bound.text

    listed = client.get("/api/v1/models/credentials", headers=auth_headers)
    assert listed.status_code == 200
    assert _PLAINTEXT not in listed.text
    assert listed.json()["data"][0]["masked_value"]


def test_resolve_secret_is_explicit_and_audited(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``ProviderRuntime.resolve_secret`` 解密为明文（仅内存）并写解密审计。"""
    services = client.app.state.services
    provider = _register_provider(client, auth_headers)
    credential_id = _save_credential(client, auth_headers, "openai")
    client.post(
        f"/api/v1/models/providers/{provider['id']}/credential",
        headers=auth_headers,
        json={"credential_id": credential_id},
    )

    secret = services.provider_runtime.resolve_secret(
        provider["id"], tenant_id=provider["tenant_id"]
    )
    assert secret == _PLAINTEXT

    from astra_database import session_scope
    from astra_database.models.audit import AuditLog as OrmAuditLog

    with session_scope(session_factory) as session:
        rows = session.execute(select(OrmAuditLog)).scalars().all()
    assert any(row.action == "model.credential.decrypt" for row in rows), "未写解密审计"


def test_resolve_secret_without_binding_raises(client: Any, auth_headers: dict[str, str]) -> None:
    """未绑定凭证 → ``CONFIGURATION_ERROR``。"""
    from astra_core import DomainError, ErrorCode

    services = client.app.state.services
    provider = _register_provider(client, auth_headers)
    try:
        services.provider_runtime.resolve_secret(provider["id"], tenant_id=provider["tenant_id"])
    except DomainError as exc:
        assert exc.code == ErrorCode.CONFIGURATION_ERROR
    else:  # pragma: no cover - 需显式抛错
        raise AssertionError("未绑定凭证时应抛 DomainError")
