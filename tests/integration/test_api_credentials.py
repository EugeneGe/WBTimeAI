"""API Key 安全集成测试（T0-18 / §3-#10）。

断言：响应无明文 + 库中仅密文 + 日志无明文；``GET`` 仅掩码。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

#: 具辨识度的明文（确保不会与掩码 / 日志偶然重合）。
_PLAINTEXT = "sk-live-SUPERSECRET-0123456789abcdef-XYZ"


def test_save_credential_never_exposes_plaintext(
    client: Any, auth_headers: dict[str, str], session_factory: Any, caplog: Any
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/v1/settings/credentials",
            headers=auth_headers,
            json={"provider": "openai", "key_type": "api_key", "value": _PLAINTEXT},
        )
    assert response.status_code == 201, response.text
    body = response.json()["data"]

    # 1) 响应体无明文；仅掩码
    assert _PLAINTEXT not in response.text
    assert body["masked_value"]
    assert _PLAINTEXT != body["masked_value"]

    # 2) 库中仅密文（明文不出现在 encrypted_value 列）
    import astra_database.models  # noqa: F401
    from astra_database import session_scope
    from astra_database.models.credential import Credential as OrmCredential

    with session_scope(session_factory) as session:
        row = session.execute(select(OrmCredential)).scalars().one()
    assert row.encrypted_value
    assert _PLAINTEXT not in row.encrypted_value
    assert row.encrypted_value != _PLAINTEXT

    # 3) 密文可解密回明文（证明加密正确，且密文 ≠ 明文）
    from astra_config import get_settings
    from astra_security import AesGcmCipher

    cipher = AesGcmCipher.from_secret(get_settings().secret_key)
    assert cipher.decrypt(row.encrypted_value) == _PLAINTEXT

    # 4) 日志无明文
    assert _PLAINTEXT not in caplog.text


def test_list_credentials_returns_only_masked(client: Any, auth_headers: dict[str, str]) -> None:
    client.post(
        "/api/v1/settings/credentials",
        headers=auth_headers,
        json={"provider": "anthropic", "key_type": "api_key", "value": _PLAINTEXT},
    )
    response = client.get("/api/v1/settings/credentials", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()["data"]
    assert len(items) == 1
    assert items[0]["provider"] == "anthropic"
    assert items[0]["masked_value"]
    assert _PLAINTEXT not in response.text


def test_empty_credential_rejected(client: Any, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/settings/credentials",
        headers=auth_headers,
        json={"provider": "openai", "key_type": "api_key", "value": ""},
    )
    assert response.status_code == 422
