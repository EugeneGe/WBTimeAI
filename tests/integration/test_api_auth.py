"""``/api/v1/auth`` 集成测试（T0-18 / §3-#12）。

覆盖：注册 / 登录 / 刷新 / 登出；**登出后旧 refresh → 401**；无 / 坏 token → 401。
"""

from __future__ import annotations

from typing import Any

_REGISTER = {
    "username": "alice",
    "email": "alice@example.com",
    "password": "secret123",
    "display_name": "Alice",
}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_tokens_and_profile(client: Any) -> None:
    response = client.post("/api/v1/auth/register", json=_REGISTER)
    assert response.status_code == 201, response.text
    body = response.json()["data"]
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"

    me = client.get("/api/v1/users/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200
    profile = me.json()["data"]
    assert profile["username"] == "alice"
    assert profile["email"] == "alice@example.com"
    assert profile["display_name"] == "Alice"


def test_login_success(client: Any) -> None:
    client.post("/api/v1/auth/register", json=_REGISTER)
    response = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "secret123"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["access_token"]


def test_login_wrong_password_returns_401(client: Any) -> None:
    client.post("/api/v1/auth/register", json=_REGISTER)
    response = client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_duplicate_registration_conflicts(client: Any) -> None:
    client.post("/api/v1/auth/register", json=_REGISTER)
    response = client.post("/api/v1/auth/register", json=_REGISTER)
    assert response.status_code == 409
    assert response.json()["code"] == "USER_ALREADY_EXISTS"


def test_logout_invalidates_refresh(client: Any) -> None:
    tokens = client.post("/api/v1/auth/register", json=_REGISTER).json()["data"]
    logout = client.post("/api/v1/auth/logout", headers=_bearer(tokens["access_token"]))
    assert logout.status_code == 200

    stale = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert stale.status_code == 401
    assert stale.json()["code"] == "AUTH_TOKEN_REVOKED"


def test_refresh_rotates_tokens(client: Any) -> None:
    tokens = client.post("/api/v1/auth/register", json=_REGISTER).json()["data"]
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()["data"]
    assert new_tokens["access_token"]
    # 旧 refresh 已随旋转失效 → 401
    stale = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert stale.status_code == 401


def test_missing_and_bad_token_return_401(client: Any) -> None:
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get("/api/v1/users/me", headers=_bearer("not-a-jwt")).status_code == 401
    assert (
        client.get("/api/v1/users/me", headers={"Authorization": "Basic abcdef"}).status_code == 401
    )
