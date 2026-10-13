"""M2 · WS2 独立验收边界用例（QA 严过关独立构造，非复跑工程师用例）。

目的：**独立**验证「API 同源托管前端静态 + SPA 回退」是否对既有语义**零回归**，
重点证伪工程师自报的偏差修复点（用 ``SPAStaticFiles`` 在 ``router.default`` 兜底，
而非根挂载）。

覆盖：
- ``GET /`` → 200 ``text/html`` 含 ``id="root"``；深链 ``GET /projects/123`` → 200 HTML；
- **不遮蔽**：``GET``/``POST`` ``/api/v1/不存在`` → 404；``POST /health`` → 405；
  ``/openapi.json`` / ``/docs`` → 200；
- **缺失资源**：``GET /assets/不存在.js`` → 404（不误回退）；``/assets/index-*.js`` → 200 JS；
- **尾斜杠**：``/health`` vs ``/health/`` 行为与未启用静态时**一致**；
- **开关**：关闭 / 目录缺失 → 不装配（``/`` 回 404）；
- **等价性**：静态开 vs 关，对一组 API/文档端点状态码与响应体**逐字一致**（零回归证据）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_INDEX_HTML = '<!doctype html><html><body><div id="root"></div></body></html>'

#: 响应壳中每请求唯一、与静态托管无关的字段（比对前须归一化）。
_VOLATILE = re.compile(r'"request_id":"[0-9a-f\-]{36}"')


def _normalize(text: str) -> str:
    """归一化响应体中的易变字段（``request_id``），使「静态开 vs 关」可逐字比对。"""
    return _VOLATILE.sub('"request_id":"<VOLATILE>"', text)


def _reset_settings() -> None:
    from astra_config.loader import reset_settings_cache

    reset_settings_cache()


def make_web_dist(tmp_path: Path, *, name: str = "web-dist-qa") -> Path:
    """构造最小前端产物目录（含 ``id="root"`` 的 ``index.html`` + 带哈希的 JS/CSS）。"""
    dist = tmp_path / name
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log('astra');", encoding="utf-8")
    (dist / "assets" / "index-abc123.css").write_text("body{}", encoding="utf-8")
    return dist


def _client(
    isolated_settings_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dist: Path | None,
    enabled: bool = True,
) -> TestClient:
    """按给定 dist / 开关装配并返回 TestClient。"""
    if dist is not None:
        monkeypatch.setenv("ASTRA_WEB_DIST", str(dist))
    else:
        monkeypatch.setenv("ASTRA_WEB_DIST", str(isolated_settings_env.parent / "no-such-dist"))
    monkeypatch.setenv("ASTRA_WEB_STATIC_ENABLED", "true" if enabled else "false")
    _reset_settings()

    from astra_api.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def static_client(
    isolated_settings_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    with _client(isolated_settings_env, monkeypatch, dist=make_web_dist(tmp_path)) as client:
        yield client


@pytest.fixture()
def plain_client(
    isolated_settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """未启用静态托管的对照客户端（dist 指向不存在目录）。"""
    with _client(isolated_settings_env, monkeypatch, dist=None) as client:
        yield client


# -- 1. 命中与 SPA 回退 ------------------------------------------------------


def test_root_serves_html_with_root_div(static_client: TestClient) -> None:
    resp = static_client.get("/")
    assert resp.status_code == 200, resp.text
    assert "text/html" in resp.headers["content-type"]
    assert 'id="root"' in resp.text


def test_deep_link_falls_back_to_index(static_client: TestClient) -> None:
    for path in ("/projects/123", "/settings/profile", "/a/b/c/d"):
        resp = static_client.get(path)
        assert resp.status_code == 200, f"{path}: {resp.text}"
        assert 'id="root"' in resp.text, path


def test_hash_asset_served_with_js_type(static_client: TestClient) -> None:
    resp = static_client.get("/assets/index-abc123.js")
    assert resp.status_code == 200, resp.text
    assert "javascript" in resp.headers["content-type"].lower()


# -- 2. 不遮蔽（保留前缀） ---------------------------------------------------


def test_unknown_api_get_is_404_json(static_client: TestClient) -> None:
    resp = static_client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def test_unknown_api_post_is_404_not_405_not_html(static_client: TestClient) -> None:
    # 🔴 关键：验证偏差修复点——非 GET 的未知 API 路径须 404（非 405、非 HTML）。
    resp = static_client.post("/api/v1/does-not-exist")
    assert resp.status_code == 404, resp.text
    assert "text/html" not in resp.headers.get("content-type", "")
    assert resp.json()["code"] == "NOT_FOUND"


def test_health_post_is_405(static_client: TestClient) -> None:
    resp = static_client.post("/health")
    assert resp.status_code == 405, resp.text
    assert resp.json()["code"] == "METHOD_NOT_ALLOWED"


def test_health_get_ok(static_client: TestClient) -> None:
    resp = static_client.get("/health")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "ok"


def test_openapi_and_docs_ok(static_client: TestClient) -> None:
    oa = static_client.get("/openapi.json")
    assert oa.status_code == 200 and oa.json()["openapi"].startswith("3."), oa.text
    docs = static_client.get("/docs")
    assert docs.status_code == 200 and "text/html" in docs.headers["content-type"], docs.text
    redoc = static_client.get("/redoc")
    assert redoc.status_code == 200, redoc.text


def test_nonreserved_unknown_put_is_404_not_405(static_client: TestClient) -> None:
    # 未注册路径的非 GET 方法：既有语义 404（根挂载会导致 405）→ 证伪偏差修复点。
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        resp = static_client.request(method, "/projects/123")
        assert resp.status_code == 404, f"{method}: {resp.status_code} {resp.text}"
        assert "text/html" not in resp.headers.get("content-type", ""), method


# -- 3. 缺失资源 -------------------------------------------------------------


def test_missing_asset_is_404_not_html(static_client: TestClient) -> None:
    for path in ("/assets/missing.js", "/assets/index-deadbeef.css", "/favicon.ico"):
        resp = static_client.get(path)
        assert resp.status_code == 404, f"{path}: {resp.status_code} {resp.text}"
        assert "text/html" not in resp.headers.get("content-type", ""), path


# -- 4. 尾斜杠重定向一致性 ---------------------------------------------------


def test_trailing_slash_consistent_with_plain(
    static_client: TestClient, plain_client: TestClient
) -> None:
    # 注册路由 /health：/health/ 应一致重定向（307）；未启用静态时行为相同。
    for client in (static_client, plain_client):
        a = client.get("/health/", follow_redirects=False)
        b = client.get("/health", follow_redirects=False)
        assert a.status_code in (307, 308), a.text
        assert b.status_code == 200, b.text


# -- 5. 开关 / 目录缺失 ------------------------------------------------------


def test_disabled_by_flag_returns_404(
    isolated_settings_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _client(
        isolated_settings_env, monkeypatch, dist=make_web_dist(tmp_path, name="d1"), enabled=False
    ) as client:
        resp = client.get("/")
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def test_missing_dist_dir_gracefully_disabled(
    isolated_settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _client(isolated_settings_env, monkeypatch, dist=None, enabled=True) as client:
        root = client.get("/")
        deep = client.get("/projects/123")
    assert root.status_code == 404, root.text
    assert deep.status_code == 404, deep.text


def test_empty_dist_without_index_disabled(
    isolated_settings_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty-dist"
    empty.mkdir()
    with _client(isolated_settings_env, monkeypatch, dist=empty, enabled=True) as client:
        resp = client.get("/")
    assert resp.status_code == 404, resp.text


# -- 6. 等价性（静态开 vs 关，零回归的强证据） -------------------------------


_EQUIV_PROBES: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/health", {}),
    ("POST", "/health", {}),
    ("GET", "/openapi.json", {}),
    ("GET", "/docs", {}),
    ("GET", "/redoc", {}),
    ("GET", "/api/v1/does-not-exist", {}),
    ("GET", "/api/v1/runs/00000000-0000-0000-0000-000000000000/events", {}),
    (
        "GET",
        "/api/v1/runs/00000000-0000-0000-0000-000000000000/events",
        {"headers": {"accept": "text/event-stream"}},
    ),
    ("POST", "/api/v1/does-not-exist", {}),
    ("GET", "/metrics", {}),
]


def test_equivalence_static_on_vs_off(
    isolated_settings_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对一组 API/文档端点，静态开 vs 关的**状态码与（归一化后）响应体逐字一致**。

    归一化 ``request_id``（每请求唯一、与静态托管无关）；本组**不含** ``GET /``
    ——该路径本就是「静态开 → 200 HTML」的**预期新增行为**，不属于「既有语义」。
    """
    with (
        _client(isolated_settings_env, monkeypatch, dist=make_web_dist(tmp_path, name="on")) as on,
        _client(isolated_settings_env, monkeypatch, dist=None) as off,
    ):
        diffs: list[str] = []
        for method, path, kw in _EQUIV_PROBES:
            r_on = on.request(method, path, **kw)
            r_off = off.request(method, path, **kw)
            if (r_on.status_code, _normalize(r_on.text)) != (
                r_off.status_code,
                _normalize(r_off.text),
            ):
                diffs.append(
                    f"{method} {path}: on=({r_on.status_code}) off=({r_off.status_code})\n"
                    f"  ON: {_normalize(r_on.text)[:160]}\n  OFF: {_normalize(r_off.text)[:160]}"
                )
        assert not diffs, "静态开/关存在差异（回归）:\n" + "\n".join(diffs)
