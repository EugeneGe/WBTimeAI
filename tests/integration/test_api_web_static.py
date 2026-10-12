"""M2 · WS2：API 托管前端静态 + SPA 回退（发行形态 A：单容器打开即完整 UI）。

覆盖（**hermetic**：产物目录由 ``tmp_path`` 构造，不依赖本机是否已构建）：

- ``GET /`` → ``200`` ``index.html``（前端入口）；
- 未命中前端深链（如 ``/projects/123``）→ ``200`` 回退 ``index.html``（可刷新）；
- 命中的静态资源原样返回（含正确 ``content-type``）；
- **保留前缀不遮蔽**：``/health``（含非 ``GET`` → 405）、``/api/v1/*`` 未知 → 404、
  ``/openapi.json`` / ``/docs`` 正常；
- 缺失的**带扩展名**资源 → 404（不误回退为页面）；
- **仅当 dist 存在时启用**：目录缺失 / 开关关闭 → ``/`` 回到 404（零回归）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_INDEX_FILE = "index.html"
_INDEX_MARKER = "astra-spa-root"


def _reset_settings() -> None:
    """清空进程级配置单例缓存，使后续 ``create_app`` 读取最新 ENV。"""
    from astra_config.loader import reset_settings_cache

    reset_settings_cache()


@pytest.fixture()
def web_dist(tmp_path: Path) -> Path:
    """构造一个最小前端产物目录（``index.html`` + ``assets/app.js``）。"""
    dist = tmp_path / "web-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / _INDEX_FILE).write_text(
        f'<!doctype html><html><body><div id="{_INDEX_MARKER}"></div></body></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log('astra');", encoding="utf-8")
    return dist


@pytest.fixture()
def static_client(
    isolated_settings_env: Path, web_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """启用静态托管的 TestClient（``ASTRA_WEB_DIST`` 指向临时产物目录）。"""
    monkeypatch.setenv("ASTRA_WEB_DIST", str(web_dist))
    _reset_settings()

    from astra_api.main import create_app

    with TestClient(create_app()) as client:
        yield client


# -- 解析逻辑（单元） --------------------------------------------------------


def test_package_relative_web_dist_points_to_apps_web_dist() -> None:
    """包相对路径解析指向 ``apps/web/dist``（不硬编码绝对路径）。"""
    from astra_api.web_static import _package_relative_web_dist

    resolved = _package_relative_web_dist()
    assert resolved.name == "dist"
    assert resolved.parent.name == "web"
    assert resolved.parent.parent.name == "apps"


def test_resolve_web_dist_respects_flag_and_existence(web_dist: Path, tmp_path: Path) -> None:
    """开关关闭 / 目录缺失 / 入口缺失 → ``None``；有效目录 → 原样返回。"""
    from astra_api.web_static import resolve_web_dist
    from astra_config import Settings

    assert resolve_web_dist(Settings(web_static_enabled=False, web_dist=str(web_dist))) is None
    missing = Settings(web_static_enabled=True, web_dist=str(tmp_path / "nope"))
    assert resolve_web_dist(missing) is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert resolve_web_dist(Settings(web_static_enabled=True, web_dist=str(empty))) is None
    assert resolve_web_dist(Settings(web_static_enabled=True, web_dist=str(web_dist))) == web_dist


# -- 静态托管行为（集成） ----------------------------------------------------


def test_root_serves_index_html(static_client: Any) -> None:
    """``GET /`` → 200 ``index.html``。"""
    response = static_client.get("/")
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    assert _INDEX_MARKER in response.text


def test_spa_deep_link_falls_back_to_index(static_client: Any) -> None:
    """未命中的前端深链 → 200 回退 ``index.html``（前端路由可刷新）。"""
    response = static_client.get("/projects/123")
    assert response.status_code == 200, response.text
    assert _INDEX_MARKER in response.text


def test_existing_asset_is_served(static_client: Any) -> None:
    """命中的静态资源原样返回。"""
    response = static_client.get("/assets/app.js")
    assert response.status_code == 200, response.text
    assert "astra" in response.text


def test_missing_asset_returns_404(static_client: Any) -> None:
    """带扩展名的缺失资源 → 404（不误回退为页面）。"""
    response = static_client.get("/assets/missing.js")
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND"


def test_health_not_shadowed(static_client: Any) -> None:
    """``/health`` 仍走原逻辑（响应壳）。"""
    response = static_client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "ok"


def test_health_non_get_still_405(static_client: Any) -> None:
    """``/health`` 非 GET → 405（未被 SPA 回退遮蔽）。"""
    response = static_client.post("/health")
    assert response.status_code == 405, response.text
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"


def test_unknown_api_route_not_shadowed(static_client: Any) -> None:
    """``/api/v1/*`` 未知路径 → 404 结构化响应（未被 SPA 回退遮蔽）。"""
    response = static_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND"


def test_unknown_nonreserved_post_is_404_not_shadowed(static_client: Any) -> None:
    """非保留前缀的未知 **POST** → 404（非 405、非页面回退），保持既有语义。"""
    response = static_client.post("/projects/123")
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND"


def test_openapi_and_docs_not_shadowed(static_client: Any) -> None:
    """框架端点 ``/openapi.json`` / ``/docs`` 仍正常。"""
    openapi = static_client.get("/openapi.json")
    assert openapi.status_code == 200, openapi.text
    assert openapi.json()["openapi"].startswith("3.")

    docs = static_client.get("/docs")
    assert docs.status_code == 200, docs.text
    assert "text/html" in docs.headers["content-type"]


def test_response_shell_middleware_still_applies(static_client: Any) -> None:
    """静态托管不干扰响应壳中间件：HTML 透传，同时带请求上下文响应头。"""
    response = static_client.get("/")
    assert response.headers.get("X-Request-Id")
    # HTML 非 JSON → 不套壳（原样透传）。
    assert not response.text.lstrip().startswith("{")


# -- 零回归：dist 缺失 / 开关关闭 --------------------------------------------


def test_disabled_when_dist_missing(
    isolated_settings_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """产物目录缺失 → 不启用静态托管，``GET /`` 回到 404。"""
    monkeypatch.setenv("ASTRA_WEB_DIST", str(tmp_path / "does-not-exist"))
    _reset_settings()

    from astra_api.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND"


def test_disabled_by_flag(
    isolated_settings_env: Path, web_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关置 ``false`` → 即便目录存在也不启用，``GET /`` 回到 404。"""
    monkeypatch.setenv("ASTRA_WEB_DIST", str(web_dist))
    monkeypatch.setenv("ASTRA_WEB_STATIC_ENABLED", "false")
    _reset_settings()

    from astra_api.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND"
