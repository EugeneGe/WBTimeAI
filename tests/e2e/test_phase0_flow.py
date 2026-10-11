"""Phase 0 端到端流程（§3-#1）。

注册 → 登录 → 创建 Workspace → 保存 API Key → 读取本人信息。
"""

from __future__ import annotations

from typing import Any


def test_phase0_end_to_end_flow(client: Any) -> None:
    # 1) 注册
    register = client.post(
        "/api/v1/auth/register",
        json={
            "username": "founder",
            "email": "founder@example.com",
            "password": "secret123",
            "display_name": "Founder",
        },
    )
    assert register.status_code == 201, register.text

    # 2) 登录
    login = client.post("/api/v1/auth/login", json={"username": "founder", "password": "secret123"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3) 创建 Workspace
    workspace = client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "My First Workspace", "workspace_type": "personal"},
    )
    assert workspace.status_code == 201, workspace.text
    workspace_id = workspace.json()["data"]["id"]

    # 4) 配置 API Key
    credential = client.post(
        "/api/v1/settings/credentials",
        headers=headers,
        json={
            "provider": "openai",
            "key_type": "api_key",
            "value": "sk-phase0-e2e-secret-value",
            "workspace_id": workspace_id,
        },
    )
    assert credential.status_code == 201, credential.text
    assert credential.json()["data"]["masked_value"]
    assert "sk-phase0-e2e-secret-value" not in credential.text

    # 5) 读取本人信息
    me = client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["username"] == "founder"

    # 6) 进入：确认工作区可列出
    listing = client.get("/api/v1/workspaces", headers=headers)
    assert listing.status_code == 200
    assert any(item["id"] == workspace_id for item in listing.json()["data"])
