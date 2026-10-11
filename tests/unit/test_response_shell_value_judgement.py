"""统一响应壳「值判定」单测（W6 / T1-28；裁定 Q3/A27）。

W1 遗留缺陷（``OBS-QA-1``）：旧判据仅看**是否存在**四个顶层键，导致「业务 DTO 恰含
``{code, message, data, request_id}``」被误判为「已是响应壳」→ 缺失壳。

A27 收敛为**值判定**：仅当 ``code == 0 且 message == "ok" 且含 data 且含 request_id``
才视为已是壳。本文件断言：

- :func:`astra_api.middleware.response_shell._is_success_shell` 的真值表；
- 经真实中间件：非成功壳（值不符）的 JSON 被**套壳**；已成功壳**原样透传**。
"""

from __future__ import annotations

from typing import Any

from astra_api.middleware.response_shell import ResponseShellMiddleware, _is_success_shell
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

# -- 纯函数真值表 ------------------------------------------------------------


def test_exact_success_shell_is_recognised() -> None:
    """四字段且值符合成功语义 → 视为已是壳。"""
    assert _is_success_shell({"code": 0, "message": "ok", "data": {"x": 1}, "request_id": "abc"})


def test_business_dto_with_same_keys_but_nonzero_code_is_not_shell() -> None:
    """业务 DTO 顶层恰用四键但 ``code != 0`` → **不是**壳（须被套壳）。"""
    assert not _is_success_shell(
        {"code": 200, "message": "created", "data": {"x": 1}, "request_id": "abc"}
    )


def test_non_ok_message_is_not_shell() -> None:
    """``message != "ok"`` → 不是壳。"""
    assert not _is_success_shell({"code": 0, "message": "created", "data": {}, "request_id": "abc"})


def test_missing_data_or_request_id_is_not_shell() -> None:
    """缺 ``data`` 或 ``request_id`` → 不是壳。"""
    assert not _is_success_shell({"code": 0, "message": "ok", "request_id": "abc"})
    assert not _is_success_shell({"code": 0, "message": "ok", "data": {}})


def test_shell_ignores_extra_keys() -> None:
    """多出额外键不影响成功判定（仍视为壳）。"""
    assert _is_success_shell(
        {"code": 0, "message": "ok", "data": {}, "request_id": "r", "trace_id": "t"}
    )


# -- 经真实中间件 ------------------------------------------------------------


def _build_app() -> FastAPI:
    """构造一个仅含响应壳中间件的测试应用。"""
    app = FastAPI()
    app.add_middleware(ResponseShellMiddleware)

    @app.get("/business")
    def business() -> JSONResponse:
        # 业务 DTO 顶层恰用四键，但值不符合成功语义 → 必须被套壳。
        return JSONResponse(
            {"code": 200, "message": "created", "data": {"x": 1}, "request_id": "inner"}
        )

    @app.get("/shell")
    def shell() -> JSONResponse:
        # 已成功壳 → 原样透传（幂等，避免二次包裹）。
        return JSONResponse({"code": 0, "message": "ok", "data": {"x": 1}, "request_id": "r-1"})

    return app


def test_middleware_wraps_business_dto_with_shell_like_keys() -> None:
    """值不符的「类壳」业务 DTO 必被套壳（消解 OBS-QA-1）。"""
    with TestClient(_build_app()) as client:
        body: dict[str, Any] = client.get("/business").json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"] == {
        "code": 200,
        "message": "created",
        "data": {"x": 1},
        "request_id": "inner",
    }


def test_middleware_passes_through_existing_success_shell() -> None:
    """真正的成功壳原样返回（不被二次包裹 / 不丢字段）。"""
    with TestClient(_build_app()) as client:
        body: dict[str, Any] = client.get("/shell").json()
    assert body == {"code": 0, "message": "ok", "data": {"x": 1}, "request_id": "r-1"}
