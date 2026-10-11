"""``/health`` 集成测试与未知路由结构断言。

自 T1-04 起，全部 JSON 响应（成功 + 失败）遵循总纲 §11.1 统一响应壳
``{code, message, data, request_id}``：``/health`` 载荷位于 ``data``。
"""

from __future__ import annotations

import re
from typing import Any

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

_SHELL_KEYS = {"code", "message", "data", "request_id"}


def test_health_returns_ok(client: Any) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    # 成功响应壳（§11.1）
    assert set(body.keys()) == _SHELL_KEYS
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == "astra-api"
    # 响应体 request_id == 响应头 X-Request-Id（同源 UUIDv7）
    assert body["request_id"] == response.headers["X-Request-Id"]
    assert _UUID_RE.match(body["request_id"])


def test_replaced_skeleton_route_returns_structured_404(client: Any) -> None:
    """W3：``/api/v1/auth`` 骨架已由真实子集替换，未定义方法路径 → 统一结构 404。"""
    response = client.get("/api/v1/auth")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert set(body.keys()) == _SHELL_KEYS
    assert body["request_id"] == response.headers["X-Request-Id"]


def test_unknown_route_returns_structured_404(client: Any) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert set(body.keys()) == _SHELL_KEYS
    assert body["request_id"] == response.headers["X-Request-Id"]
