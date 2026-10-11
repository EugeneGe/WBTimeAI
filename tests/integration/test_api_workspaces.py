"""``/api/v1/workspaces`` 集成测试（T0-18）：创建 / 列表 / 详情 / 更新设置；跨租户不可见。"""

from __future__ import annotations

from typing import Any


def test_workspace_crud(client: Any, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "Team WS", "workspace_type": "team", "settings": {"a": 1}},
    )
    assert created.status_code == 201, created.text
    workspace = created.json()["data"]
    assert workspace["workspace_type"] == "team"
    assert workspace["name"] == "Team WS"
    assert workspace["settings"] == {"a": 1}

    listing = client.get("/api/v1/workspaces", headers=auth_headers)
    assert listing.status_code == 200
    assert any(item["id"] == workspace["id"] for item in listing.json()["data"])

    detail = client.get(f"/api/v1/workspaces/{workspace['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == workspace["id"]

    updated = client.put(
        f"/api/v1/workspaces/{workspace['id']}/settings",
        headers=auth_headers,
        json={"settings": {"b": 2}},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["settings"] == {"b": 2}


def test_workspace_invalid_type_rejected(client: Any, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "bad", "workspace_type": "shared"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_workspace_not_found(client: Any, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/workspaces/does-not-exist", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "WORKSPACE_NOT_FOUND"


def test_workspace_cross_tenant_invisible(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
) -> None:
    workspace = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "A"}).json()[
        "data"
    ]

    listing = client.get("/api/v1/workspaces", headers=other_tenant_headers)
    assert listing.status_code == 200
    assert listing.json()["data"] == []

    detail = client.get(f"/api/v1/workspaces/{workspace['id']}", headers=other_tenant_headers)
    assert detail.status_code == 404
    assert detail.json()["code"] == "WORKSPACE_NOT_FOUND"


def test_workspace_requires_auth(client: Any) -> None:
    assert client.get("/api/v1/workspaces").status_code == 401
