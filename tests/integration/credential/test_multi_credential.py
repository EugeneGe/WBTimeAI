"""多凭证集成测试（W3 / T2-15；设计 §2.15.1 / §5 #16（A-10）；裁定 R5 / Erratum-H）。

覆盖（验收 §5.3 / §5.4）：

- ``credential`` 补列 + ``create`` 落库（仅密文；``name`` / ``metadata`` 不含明文）；
- 关联表 ``model_provider_credential`` 绑定 / 解绑；
- **加权轮询**：仅 ``status=="ACTIVE"`` 且 ``weight>0`` 参与，权重占比 ``weight/Σweight``；
- **移除关联不删除共享 Credential**（``unbind`` 仅删关联行）；
- ``mark_used`` 更新 ``last_used_at``；
- C-07 明文纪律（``create`` 拒绝明文出现在 ``name`` / ``metadata``；DB 无明文落库）。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from sqlalchemy import select

#: 具辨识度的明文（确保不与掩码 / 密文偶然重合）。
_P1 = "sk-live-MULTICRED-1111111111-AAAA"
_P2 = "sk-live-MULTICRED-2222222222-BBBB"
_P3 = "sk-live-MULTICRED-3333333333-CCCC"
_P4 = "sk-live-MULTICRED-4444444444-DDDD"


def _register_provider(
    client: Any, headers: dict[str, str], name: str = "openai"
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/models/providers",
        headers=headers,
        json={"name": name, "provider_type": "openai"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _service(client: Any) -> Any:
    return client.app.state.services.credentials


def test_create_persists_only_ciphertext_and_safe_metadata(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``create`` 仅落密文；``name`` / ``metadata`` 可读但**不含明文**；对外仅掩码。"""
    provider = _register_provider(client, auth_headers)
    svc = _service(client)
    masked = svc.create(
        tenant_id=provider["tenant_id"],
        provider="openai",
        key_type="api_key",
        plaintext=_P1,
        name="primary-key",
        metadata={"env": "prod", "region": "us"},
    )

    # 对外视图仅掩码。
    assert _P1 not in masked.masked_value
    assert masked.masked_value.startswith("sk-l")
    assert masked.name == "primary-key"
    assert masked.status == "ACTIVE"

    # 落库为密文，且明文不出现于任何列。
    from astra_database import session_scope
    from astra_database.models.credential import Credential as OrmCredential

    with session_scope(session_factory) as session:
        row = session.execute(
            select(OrmCredential).where(OrmCredential.id == masked.id)
        ).scalar_one()
        assert row.encrypted_value and row.encrypted_value != _P1
        assert _P1 not in row.encrypted_value
        assert row.status == "ACTIVE"
        assert row.metadata_ == {"env": "prod", "region": "us"}
        assert row.last_used_at is None


def test_create_rejects_plaintext_in_name_or_metadata(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """C-07：``name`` / ``metadata`` 含明文 → ``VALIDATION_ERROR``（不落库）。"""
    provider = _register_provider(client, auth_headers)
    svc = _service(client)

    for kwargs in (
        {"name": f"leak {_P1}"},
        {"metadata": {"note": _P1}},
    ):
        try:
            svc.create(
                tenant_id=provider["tenant_id"],
                provider="openai",
                key_type="api_key",
                plaintext=_P1,
                **kwargs,
            )
        except DomainError as exc:
            assert exc.code == ErrorCode.VALIDATION_ERROR
        else:  # pragma: no cover - 需显式抛错
            raise AssertionError("name / metadata 含明文时应抛 DomainError")


def test_weighted_round_robin_only_active_positive_weight(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """加权轮询：仅 ``ACTIVE`` 且 ``weight>0`` 参与；占比 ``weight/Σweight``。"""
    provider = _register_provider(client, auth_headers)
    svc = _service(client)
    tenant_id = provider["tenant_id"]

    c1 = svc.create(tenant_id=tenant_id, provider="openai", key_type="api_key", plaintext=_P1)
    c2 = svc.create(tenant_id=tenant_id, provider="openai", key_type="api_key", plaintext=_P2)
    c3 = svc.create(tenant_id=tenant_id, provider="openai", key_type="api_key", plaintext=_P3)
    c4 = svc.create(tenant_id=tenant_id, provider="openai", key_type="api_key", plaintext=_P4)

    svc.bind_to_provider(provider_id=provider["id"], credential_id=c1.id, weight=2)
    svc.bind_to_provider(provider_id=provider["id"], credential_id=c2.id, weight=1)
    svc.bind_to_provider(
        provider_id=provider["id"], credential_id=c3.id, weight=5, status="DISABLED"
    )
    svc.bind_to_provider(provider_id=provider["id"], credential_id=c4.id, weight=0)

    picked = [svc.select_for_provider(provider["id"]).credential_id for _ in range(6)]
    assert c3.id not in picked, "DISABLED 关联不得参与"
    assert c4.id not in picked, "weight<=0 关联不得参与"
    assert picked.count(c1.id) == 4 and picked.count(c2.id) == 2, picked
    # 顺序稳定（平滑加权轮询）：c1,c2,c1,c1,c2,c1
    assert picked == [c1.id, c2.id, c1.id, c1.id, c2.id, c1.id]


def test_select_for_provider_without_active_raises(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """无可用关联 → ``CONFIGURATION_ERROR``。"""
    provider = _register_provider(client, auth_headers)
    svc = _service(client)
    try:
        svc.select_for_provider(provider["id"])
    except DomainError as exc:
        assert exc.code == ErrorCode.CONFIGURATION_ERROR
    else:  # pragma: no cover - 需显式抛错
        raise AssertionError("无可用关联时应抛 DomainError")


def test_unbind_keeps_shared_credential(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``unbind`` 仅删关联行，**不删除共享 Credential**。"""
    provider = _register_provider(client, auth_headers)
    svc = _service(client)
    c1 = svc.create(
        tenant_id=provider["tenant_id"], provider="openai", key_type="api_key", plaintext=_P1
    )
    svc.bind_to_provider(provider_id=provider["id"], credential_id=c1.id, weight=1)

    assert len(svc.credentials_for_provider(provider["id"])) == 1
    svc.unbind_from_provider(provider_id=provider["id"], credential_id=c1.id)
    assert svc.credentials_for_provider(provider["id"]) == []

    # 凭证本体仍在（共享；未随关联删除）。
    assert svc.get(c1.id) is not None


def test_credentials_for_provider_masks_and_bind_idempotent(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """``credentials_for_provider`` 仅掩码；重复 ``bind_to_provider`` 幂等（唯一键）。"""
    provider = _register_provider(client, auth_headers)
    svc = _service(client)
    c1 = svc.create(
        tenant_id=provider["tenant_id"], provider="openai", key_type="api_key", plaintext=_P1
    )
    svc.bind_to_provider(provider_id=provider["id"], credential_id=c1.id, weight=1)
    svc.bind_to_provider(provider_id=provider["id"], credential_id=c1.id, weight=3)

    views = svc.credentials_for_provider(provider["id"])
    assert len(views) == 1, "重复绑定应幂等（唯一键）"
    assert views[0].weight == 3, "重复绑定应更新权重"
    assert _P1 not in views[0].masked_value


def test_mark_used_updates_last_used_at(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``mark_used`` 更新 ``last_used_at``。"""
    provider = _register_provider(client, auth_headers)
    svc = _service(client)
    c1 = svc.create(
        tenant_id=provider["tenant_id"], provider="openai", key_type="api_key", plaintext=_P1
    )
    assert svc.get(c1.id).last_used_at is None  # type: ignore[union-attr]
    svc.mark_used(c1.id)
    assert svc.get(c1.id).last_used_at is not None  # type: ignore[union-attr]
