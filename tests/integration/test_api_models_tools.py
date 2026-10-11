"""模型目录 / Tool 浏览器与权限 v1 路由集成测试（W6 / T1-29；设计 §2.3 / §2.5 / §2.13）。

覆盖：

- ``/models/providers``：注册 / 列表 / 详情 / 禁用（软删除）；
- ``/models/providers/{id}/models``：模型目录 / 注册；
- ``/models/providers/{id}/credential``：凭证**绑定 / 解绑**（仅存引用，无明文）；
- ``/tools``：内置工具浏览器（首批 5 个）；
- ``/tools/permissions``：授予 / 列表 / 撤销。
"""

from __future__ import annotations

from typing import Any


def _register_provider(client: Any, headers: dict[str, str], name: str = "openai") -> str:
    response = client.post(
        "/api/v1/models/providers",
        headers=headers,
        json={"name": name, "provider_type": "openai", "endpoint": "https://api.example.com"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


# -- 模型提供方 --------------------------------------------------------------


def test_provider_crud_and_disable(client: Any, auth_headers: dict[str, str]) -> None:
    """注册 → 列表 → 详情 → 禁用（``status=DISABLED``）。"""
    provider_id = _register_provider(client, auth_headers)

    listed = client.get("/api/v1/models/providers", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == provider_id for item in listed.json()["data"])

    detail = client.get(f"/api/v1/models/providers/{provider_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "ACTIVE"
    assert "credential" not in detail.json()["data"]  # 无密文 / 明文

    disabled = client.delete(f"/api/v1/models/providers/{provider_id}", headers=auth_headers)
    assert disabled.status_code == 200
    assert disabled.json()["data"]["status"] == "DISABLED"


def test_register_and_list_models(client: Any, auth_headers: dict[str, str]) -> None:
    """在某提供方下注册模型 → 列表可见。"""
    provider_id = _register_provider(client, auth_headers, name="anthropic")
    created = client.post(
        f"/api/v1/models/providers/{provider_id}/models",
        headers=auth_headers,
        json={"name": "claude-x", "model_type": "CHAT", "context_window": 200000},
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["provider_id"] == provider_id

    models = client.get(f"/api/v1/models/providers/{provider_id}/models", headers=auth_headers)
    assert models.status_code == 200
    assert [item["name"] for item in models.json()["data"]] == ["claude-x"]


def test_bind_and_unbind_credential_stores_reference_only(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """绑定凭证 → ``credential_id`` 仅引用；响应不含明文 / 密文。"""
    provider_id = _register_provider(client, auth_headers, name="openai-bind")
    credential = client.post(
        "/api/v1/models/credentials",
        headers=auth_headers,
        json={"provider": "openai", "key_type": "api_key", "value": "sk-live-SECRET-abcdef123456"},
    )
    assert credential.status_code == 201, credential.text
    credential_id = credential.json()["data"]["id"]

    bound = client.post(
        f"/api/v1/models/providers/{provider_id}/credential",
        headers=auth_headers,
        json={"credential_id": credential_id},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["data"]["credential_id"] == credential_id
    assert "SECRET" not in bound.text

    unbound = client.delete(
        f"/api/v1/models/providers/{provider_id}/credential", headers=auth_headers
    )
    assert unbound.status_code == 200
    assert unbound.json()["data"]["credential_id"] is None


# -- Tool 浏览器 / 权限 ------------------------------------------------------


def test_list_builtin_tools(client: Any, auth_headers: dict[str, str]) -> None:
    """内置工具浏览器返回首批 5 个工具（``filesystem``/``shell``/``git``/``http``/``python``）。"""
    response = client.get("/api/v1/tools", headers=auth_headers)
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["data"]}
    assert {"filesystem", "shell", "git", "http", "python"} <= names
    for item in response.json()["data"]:
        assert "input_schema" in item


def test_tool_permission_grant_list_revoke(client: Any, auth_headers: dict[str, str]) -> None:
    """授予 → 列表 → 撤销（走真实 Agent 以满足外键）。"""
    agent = client.post("/api/v1/agents", headers=auth_headers, json={"name": "Perm Agent"}).json()[
        "data"
    ]["id"]

    granted = client.post(
        "/api/v1/tools/permissions",
        headers=auth_headers,
        json={"tool_id": "filesystem", "action": "EXECUTE", "effect": "ALLOW", "agent_id": agent},
    )
    assert granted.status_code == 201, granted.text
    permission_id = granted.json()["data"]["id"]
    assert granted.json()["data"]["effect"] == "ALLOW"

    listed = client.get(
        "/api/v1/tools/permissions", headers=auth_headers, params={"agent_id": agent}
    )
    assert listed.status_code == 200
    assert any(item["id"] == permission_id for item in listed.json()["data"])

    revoked = client.delete(f"/api/v1/tools/permissions/{permission_id}", headers=auth_headers)
    assert revoked.status_code == 204

    after = client.get(
        "/api/v1/tools/permissions", headers=auth_headers, params={"agent_id": agent}
    )
    assert all(item["id"] != permission_id for item in after.json()["data"])
