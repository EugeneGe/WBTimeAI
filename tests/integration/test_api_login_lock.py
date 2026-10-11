"""登录爆破防护集成测试（T0-18 / §3-#12）：连续失败达阈值 → 423。"""

from __future__ import annotations

from typing import Any

_REGISTER = {
    "username": "alice",
    "email": "alice@example.com",
    "password": "secret123",
}
_WRONG = {"username": "alice", "password": "wrong-password"}


def test_consecutive_failures_lock_account(client: Any) -> None:
    client.post("/api/v1/auth/register", json=_REGISTER)
    for _ in range(5):  # 默认 ASTRA_LOGIN_MAX_ATTEMPTS=5
        response = client.post("/api/v1/auth/login", json=_WRONG)
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"

    locked = client.post("/api/v1/auth/login", json=_WRONG)
    assert locked.status_code == 423
    assert locked.json()["code"] == "AUTH_ACCOUNT_LOCKED"


def test_correct_password_after_lock_still_423(client: Any) -> None:
    client.post("/api/v1/auth/register", json=_REGISTER)
    for _ in range(5):
        client.post("/api/v1/auth/login", json=_WRONG)

    response = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "secret123"}
    )
    assert response.status_code == 423
    assert response.json()["code"] == "AUTH_ACCOUNT_LOCKED"
