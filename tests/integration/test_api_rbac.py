"""RBAC 集成测试（T0-18 / §3-#6）：无权限 → 403；``admin=*`` 放行。"""

from __future__ import annotations

from typing import Any


def test_admin_wildcard_allows_workspace_creation(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """注册用户自动成为 admin（``*`` 通配）→ 放行。"""
    response = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "allowed"})
    assert response.status_code == 201


def test_user_without_membership_gets_403(
    client: Any, permissionless_headers: dict[str, str]
) -> None:
    """无成员关系（无角色）的用户创建 → 403。"""
    response = client.post(
        "/api/v1/workspaces", headers=permissionless_headers, json={"name": "denied"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_user_without_membership_can_still_read_own_profile(
    client: Any, permissionless_headers: dict[str, str]
) -> None:
    """鉴权 ≠ 授权：无权限用户仍可读取本人信息（仅需认证）。"""
    response = client.get("/api/v1/users/me", headers=permissionless_headers)
    assert response.status_code == 200
    assert response.json()["data"]["username"] == "nobody"
