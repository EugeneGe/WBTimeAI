"""统一异常映射集成测试（返修 1 / T1-04 四字段响应壳）。

覆盖：
- 纯 ``DomainError``（非 ``AstraError`` 子类）→ 统一四字段壳 + 携带自身 code + 状态码映射；
- 未知路由 → 404 ``NOT_FOUND``；
- 方法不允许 → 405 ``METHOD_NOT_ALLOWED``；
- 失败响应体 ``request_id`` == 响应头 ``X-Request-Id``（同源 UUIDv7，总纲 §11.1）。
"""

from __future__ import annotations

import re
from typing import Any

from astra_core import ErrorCode
from astra_core.error import DomainError
from fastapi import FastAPI
from fastapi.testclient import TestClient

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

_SHELL_KEYS = {"code", "message", "data", "request_id"}


def test_pure_domain_error_maps_with_own_code(isolated_settings_env: Any) -> None:
    from astra_api.main import create_app

    app: FastAPI = create_app()

    @app.get("/_test/domain-error")
    async def _raise_domain_error() -> None:
        raise DomainError("boom-detail", code=ErrorCode.CONFLICT)

    with TestClient(app) as test_client:
        response = test_client.get("/_test/domain-error")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONFLICT"
    assert body["message"] == "boom-detail"
    assert body["data"] == {}
    assert set(body.keys()) == _SHELL_KEYS
    assert body["request_id"] == response.headers["X-Request-Id"]
    assert _UUID_RE.match(body["request_id"])


def test_unknown_route_maps_to_not_found(client: Any) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert set(body) == _SHELL_KEYS
    assert body["request_id"] == response.headers["X-Request-Id"]


def test_method_not_allowed_maps_to_405(client: Any) -> None:
    response = client.post("/health")
    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert set(body) == _SHELL_KEYS
    assert body["request_id"] == response.headers["X-Request-Id"]
