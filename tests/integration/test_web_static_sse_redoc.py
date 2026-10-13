"""G-2（V0.4.1）：静态托管下 SSE 与 ``/redoc`` 语义固化（常规回归用例）。

来源：``docs/施工方案/发行形态/QA-M2-WS3-验收.md`` §3 / §7——QA 独立探针补齐了
「``renderer-server`` 反代前缀含 ``/redoc``」「SSE 条件化头（``no-cache`` +
``x-accel-buffering``）」两项，并建议**固化进回归**。本文件把 **API 侧**的等价语义
固化进常规回归套件（TS 侧等价固化见
``apps/desktop/src/main/__tests__/renderer-server.test.ts``）。

固化点（与「QA 探针」逐项对应）：

- 🔴 **保留前缀不被 SPA 兜底遮蔽**：R ``SPA 静态托管开启``时，``/redoc``（及
  :data:`astra_api.web_static._RESERVED_PREFIXES` 的**其余成员**）仍命中框架既有
  语义，**不**被前端 ``index.html``（含 ``id="root"``）兜底吞掉——断言**直接对齐**
  源码常量，避免「探针口径」与「实现口径」漂移。
- 🔴 **SSE 语义不被静态托管干扰**：``Accept: text/event-stream`` 的事件端点返回
  ``text/event-stream``（200）并携带「禁缓存 / 禁缓冲」头；且「静态开 vs 关」
  状态码 / 内容类型 / 响应体**逐字一致**（零回归强证据）。

本用例**独立构造**（不复跑既有 ``test_api_web_static_qa_verify.py`` 的断言集合），
覆盖目标是 G-2 指定的两个语义面。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

#: 前端产物入口（含 ``id="root"``）——SPA 兜底的判据标记。
_INDEX_HTML = '<!doctype html><html><body><div id="root"></div></body></html>'

#: SPA 兜底被命中时的响应体特征（用于证伪「保留前缀被遮蔽」）。
_SPA_MARKER = 'id="root"'

#: 响应壳中每请求唯一、与静态托管无关的字段（比对前须归一化）。
_VOLATILE = re.compile(r'"request_id":"[0-9a-f\-]{36}"')

#: 一个「不存在」的 Run id（SSE 端点回放为空 + 状态为 None → 立即结束，body 为空）。
_ABSENT_RUN_ID = "00000000-0000-0000-0000-000000000000"

#: 期望的保留前缀集合（与 ``web_static._RESERVED_PREFIXES`` 对齐；契约锁）。
_EXPECTED_RESERVED_PREFIXES = frozenset(
    {"api", "health", "docs", "redoc", "openapi.json", "metrics"}
)


# -- 构造 / 归一化辅助（对齐 ``test_api_web_static_qa_verify.py`` 的 fixture 构造） --


def _normalize(text: str) -> str:
    """归一化响应体中的易变字段（``request_id``），使「静态开 vs 关」可逐字比对。"""
    return _VOLATILE.sub('"request_id":"<VOLATILE>"', text)


def _reset_settings() -> None:
    from astra_config.loader import reset_settings_cache

    reset_settings_cache()


def make_web_dist(tmp_path: Path, *, name: str = "web-dist-g2") -> Path:
    """构造最小前端产物目录（含 ``id="root"`` 的 ``index.html``）。"""
    dist = tmp_path / name
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "index-g2hash.js").write_text("console.log('astra');", encoding="utf-8")
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


def _register(client: TestClient, *, username: str = "g2user") -> dict[str, str]:
    """注册并登录一个用户，返回带 Bearer 的请求头（供受保护的 SSE 端点）。

    ``username`` 可指定：等价性用例中「静态开 / 关」两客户端**共享同一 SQLite**
    （同一 ``isolated_settings_env``），须以不同用户名注册以规避 ``USER_ALREADY_EXISTS``。
    """
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "secret123",
            "display_name": "G2 User",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def static_client(
    isolated_settings_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """SPA 静态托管**开启**（dist 就位）的客户端。"""
    with _client(isolated_settings_env, monkeypatch, dist=make_web_dist(tmp_path)) as client:
        yield client


@pytest.fixture()
def plain_client(
    isolated_settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """未启用静态托管的对照客户端（dist 指向不存在目录）。"""
    with _client(isolated_settings_env, monkeypatch, dist=None) as client:
        yield client


def _is_spa_fallback(response: Response) -> bool:
    """响应是否为 SPA 兜底（200 + 含 ``id="root"`` 的前端入口）。"""
    return response.status_code == 200 and _SPA_MARKER in response.text


# -- 0. 契约锁：保留前缀集合与源码常量对齐 -----------------------------------


def test_reserved_prefixes_contract_alignment() -> None:
    """保留前缀集合**直接对齐** ``web_static._RESERVED_PREFIXES``（防口径漂移）。"""
    from astra_api import web_static

    assert (
        web_static._RESERVED_PREFIXES == _EXPECTED_RESERVED_PREFIXES
    ), "保留前缀集合发生变化；G-2 断言与 web_static.py 口径需同步更新"
    assert "redoc" in web_static._RESERVED_PREFIXES


# -- 1. /redoc（及保留前缀）不被 SPA 兜底遮蔽 --------------------------------


def test_redoc_not_shadowed_by_spa(static_client: TestClient) -> None:
    """静态托管开启时 ``/redoc`` 命中框架文档页，**不**被 SPA 兜底遮蔽。"""
    resp = static_client.get("/redoc")
    assert resp.status_code == 200, resp.text
    assert "text/html" in resp.headers["content-type"], resp.headers["content-type"]
    # 关键：body 不是前端入口（redoc 页不含 ``id="root"``）。
    assert not _is_spa_fallback(resp), "/redoc 被 SPA 兜底遮蔽"


def test_docs_and_openapi_not_shadowed_by_spa(static_client: TestClient) -> None:
    """``/docs`` / ``/openapi.json`` 同样命中框架语义（非 SPA 兜底）。"""
    docs = static_client.get("/docs")
    assert docs.status_code == 200 and "text/html" in docs.headers["content-type"], docs.text
    assert not _is_spa_fallback(docs), "/docs 被 SPA 兜底遮蔽"

    openapi = static_client.get("/openapi.json")
    assert openapi.status_code == 200, openapi.text
    assert openapi.json()["openapi"].startswith("3."), openapi.text
    assert not _is_spa_fallback(openapi), "/openapi.json 被 SPA 兜底遮蔽"


def test_every_reserved_prefix_avoids_spa_fallback(static_client: TestClient) -> None:
    """遍历 ``_RESERVED_PREFIXES``：其下**未知子路径**一律**不**回落 SPA 兜底。

    直接以源码常量为遍历源 → 断言与实现**严格对齐**；新增保留前缀会自动纳入本断言。
    """
    from astra_api import web_static

    shadowed: list[str] = []
    for prefix in sorted(web_static._RESERVED_PREFIXES):
        # 保留段（根）与其下未知子路径均不得被 SPA 兜底接管。
        for path in (f"/{prefix}", f"/{prefix}/__g2_probe__"):
            resp = static_client.get(path)
            if _is_spa_fallback(resp):
                shadowed.append(f"{path} -> 200 SPA(index.html)")
    assert not shadowed, "保留前缀被 SPA 兜底遮蔽:\n" + "\n".join(shadowed)


def test_unknown_api_path_still_404_json(static_client: TestClient) -> None:
    """保留前缀 ``/api`` 下未知路径保持既有 404 JSON 语义（非 HTML）。"""
    for method in ("GET", "POST"):
        resp = static_client.request(method, "/api/v1/__g2_absent__")
        assert resp.status_code == 404, f"{method}: {resp.status_code} {resp.text}"
        assert "text/html" not in resp.headers.get("content-type", ""), method
        assert resp.json()["code"] == "NOT_FOUND", resp.text


# -- 2. SSE 语义不被静态托管干扰 ---------------------------------------------


def _sse_request(client: TestClient, headers: dict[str, str]) -> Response:
    """对事件端点发 ``Accept: text/event-stream`` 请求（携带鉴权）。"""
    return client.get(
        f"/api/v1/runs/{_ABSENT_RUN_ID}/events",
        headers={**headers, "accept": "text/event-stream"},
    )


def test_sse_endpoint_returns_event_stream_with_anti_buffer_headers(
    static_client: TestClient,
) -> None:
    """静态托管开启时，SSE 端点返回 ``text/event-stream`` + 禁缓存 / 禁缓冲头。"""
    headers = _register(static_client)
    resp = _sse_request(static_client, headers)
    assert resp.status_code == 200, resp.text
    content_type = resp.headers["content-type"]
    assert content_type.startswith("text/event-stream"), content_type
    # 与 renderer-server 反代侧「条件化头」同口径（API 侧直接登记）。
    assert resp.headers.get("cache-control") == "no-cache", resp.headers.get("cache-control")
    assert resp.headers.get("x-accel-buffering") == "no", resp.headers.get("x-accel-buffering")
    assert not _is_spa_fallback(resp), "SSE 端点被 SPA 兜底遮蔽"


def test_sse_json_negotiation_not_disturbed(static_client: TestClient) -> None:
    """未声明 SSE（``Accept: application/json``）时端点回落 JSON 列表。"""
    headers = _register(static_client)
    resp = static_client.get(
        f"/api/v1/runs/{_ABSENT_RUN_ID}/events",
        headers={**headers, "accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert "application/json" in resp.headers["content-type"], resp.headers["content-type"]
    assert not _is_spa_fallback(resp), "JSON 事件端点被 SPA 兜底遮蔽"


def test_sse_equivalence_static_on_vs_off(
    isolated_settings_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE 请求在「静态开 vs 关」下状态码 / 内容类型 / 响应体逐字一致（零回归）。"""
    with (
        _client(isolated_settings_env, monkeypatch, dist=make_web_dist(tmp_path, name="on")) as on,
        _client(isolated_settings_env, monkeypatch, dist=None) as off,
    ):
        on_headers = _register(on, username="g2on")
        off_headers = _register(off, username="g2off")

        r_on = _sse_request(on, on_headers)
        r_off = _sse_request(off, off_headers)

        assert r_on.status_code == r_off.status_code == 200, (r_on.text, r_off.text)
        assert r_on.headers["content-type"] == r_off.headers["content-type"]
        assert r_on.headers.get("cache-control") == "no-cache"
        assert r_off.headers.get("cache-control") == "no-cache"
        assert r_on.headers.get("x-accel-buffering") == "no"
        assert r_off.headers.get("x-accel-buffering") == "no"
        assert _normalize(r_on.text) == _normalize(r_off.text)
