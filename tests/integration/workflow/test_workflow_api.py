"""Workflow API + SSE 集成测试（W4 / T2-25；设计 §2.5 / §2.12 / §2.16）。

覆盖（W4 裁定 §5 T2-25 验收口径 + §7.1 风险）：

- ``/workflows`` CRUD（统一响应壳 ``{code, message, data, request_id}``）；
- ``/workflows/{id}/publish`` **一次发布 = 一个新 ``workflow_version``**，Workflow 置 ``ACTIVE``；
- ``/workflows/{id}/run`` + ``Accept: text/event-stream`` → **SSE**（``text/event-stream``，
  **不套壳**，下发 ``X-Request-Id`` / ``X-Trace-Id``），帧含 ``workflow.*`` 通道；
- ``/run`` 显式 ``Accept: application/json`` → 统一响应壳 + 终态运行（不 406）；
- 运行详情（重放快照，``I-P2-06``）与运行取消；
- 跨租户隔离（404）。

🔴 SSE 复用既有 ``sse/stream.py``（``stream_run`` + ``StreamDeps``）；``encoder.py`` 不改
   （``workflow.*`` / ``approval.*`` 通道随 T2-16 冻结）。
"""

from __future__ import annotations

from typing import Any

import pytest


def _data(response: Any) -> Any:
    """从统一响应壳取 ``data``。"""
    body = response.json()
    assert "data" in body, response.text
    return body["data"]


def _create_workflow(client: Any, headers: dict[str, str], name: str = "flow-1") -> str:
    """建一个 Workflow，返回 ``workflow_id``。"""
    created = client.post(
        "/api/v1/workflows",
        headers=headers,
        json={"name": name, "description": "demo"},
    )
    assert created.status_code == 201, created.text
    workflow = _data(created)
    assert workflow["name"] == name
    assert workflow["status"] == "DRAFT"
    return workflow["id"]


def _publish_end_only(
    client: Any, headers: dict[str, str], workflow_id: str, *, version: str | None = None
) -> dict[str, Any]:
    """发布一个仅含 ``END`` 节点的最小可运行版本（无外呼 / 无权限依赖）。"""
    payload: dict[str, Any] = {
        "nodes": [{"key": "end", "type": "END"}],
        "edges": [],
        "entry": "end",
    }
    if version is not None:
        payload["version"] = version
    published = client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers=headers,
        json=payload,
    )
    assert published.status_code == 201, published.text
    return _data(published)


# -- CRUD + 发布 -------------------------------------------------------------


def test_workflow_crud_and_publish(client: Any, auth_headers: dict[str, str]) -> None:
    """Workflow 创建 / 列表 / 详情 / 更新 / 删除 + 发布产生新版本。"""
    workflow_id = _create_workflow(client, auth_headers)

    listed = client.get("/api/v1/workflows", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == workflow_id for item in _data(listed))

    detail = client.get(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert _data(detail)["name"] == "flow-1"

    updated = client.put(
        f"/api/v1/workflows/{workflow_id}",
        headers=auth_headers,
        json={"name": "flow-1-renamed", "description": "updated"},
    )
    assert updated.status_code == 200, updated.text
    assert _data(updated)["name"] == "flow-1-renamed"

    # 首次发布 → 新版本 ``v1``（PUBLISHED），Workflow 置 ``ACTIVE`` 且挂当前版本。
    version = _publish_end_only(client, auth_headers, workflow_id)
    assert version["version"] == "v1"
    assert version["status"] == "PUBLISHED"
    assert version["definition"]["entry"] == "end"

    versions = client.get(f"/api/v1/workflows/{workflow_id}/versions", headers=auth_headers)
    assert versions.status_code == 200
    assert len(_data(versions)) == 1

    refreshed = _data(client.get(f"/api/v1/workflows/{workflow_id}", headers=auth_headers))
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["current_version_id"] == version["id"]

    # 二次发布 → 新版本 ``v2``（一次发布 = 一个新版本）。
    second = _publish_end_only(client, auth_headers, workflow_id)
    assert second["version"] == "v2"
    listed_versions = client.get(f"/api/v1/workflows/{workflow_id}/versions", headers=auth_headers)
    assert len(_data(listed_versions)) == 2

    deleted = client.delete(f"/api/v1/workflows/{workflow_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/workflows/{workflow_id}", headers=auth_headers).status_code == 404


def test_workflow_response_uses_unified_shell(client: Any, auth_headers: dict[str, str]) -> None:
    """CRUD 走**统一响应壳**（``{code, message, data, request_id}``）。"""
    created = client.post("/api/v1/workflows", headers=auth_headers, json={"name": "shell-flow"})
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"code", "message", "data", "request_id"}
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["name"] == "shell-flow"


def test_workflow_cross_tenant_returns_404(
    client: Any, auth_headers: dict[str, str], other_tenant_headers: dict[str, str]
) -> None:
    """跨租户访问 Workflow → 404（隔离不变量）。"""
    workflow_id = _create_workflow(client, auth_headers, name="private-flow")
    forbidden = client.get(f"/api/v1/workflows/{workflow_id}", headers=other_tenant_headers)
    assert forbidden.status_code == 404, forbidden.text


# -- 运行（SSE / JSON） ------------------------------------------------------


def test_run_workflow_streams_sse_frames(client: Any, auth_headers: dict[str, str]) -> None:
    """``Accept: text/event-stream`` → SSE（``text/event-stream`` + 反缓冲头 + 请求头）。"""
    workflow_id = _create_workflow(client, auth_headers, name="sse-flow")
    _publish_end_only(client, auth_headers, workflow_id)
    headers = {**auth_headers, "Accept": "text/event-stream"}

    with client.stream(
        "POST",
        f"/api/v1/workflows/{workflow_id}/run",
        headers=headers,
        json={"execution_mode": "INLINE", "input": {"q": "hello"}},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers.get("x-accel-buffering") == "no"
        assert response.headers.get("cache-control") == "no-cache"
        # 验收 ②：SSE 建连响应下发 ``X-Request-Id`` / ``X-Trace-Id``（不套统一响应壳）。
        assert response.headers.get("x-request-id")
        assert response.headers.get("x-trace-id")
        raw = "".join(response.iter_text())

    frames = [frame for frame in raw.split("\n\n") if frame.strip()]
    assert frames, "未收到任何 SSE 帧"

    events = [
        line[len("event: ") :]
        for frame in frames
        for line in frame.splitlines()
        if line.startswith("event: ")
    ]
    # 复用既有 ``workflow.*`` 通道（encoder.py 不改）。
    assert "workflow.started" in events
    assert "workflow.completed" in events

    # 数据帧均为 ``id:`` / ``event:`` / ``data:`` 三行。
    for frame in frames:
        lines = frame.splitlines()
        assert any(line.startswith("id: ") for line in lines)
        assert any(line.startswith("event: ") for line in lines)
        assert any(line.startswith("data: ") for line in lines)
    # SSE 帧**不套**统一响应壳：不得出现壳四键。
    assert '"request_id"' not in raw


def test_run_workflow_json_degrade(client: Any, auth_headers: dict[str, str]) -> None:
    """显式 ``Accept: application/json`` → 统一响应壳 + 终态运行（不 406）。"""
    workflow_id = _create_workflow(client, auth_headers, name="json-flow")
    _publish_end_only(client, auth_headers, workflow_id)
    headers = {**auth_headers, "Accept": "application/json"}

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers=headers,
        json={"execution_mode": "INLINE"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"code", "message", "data", "request_id"}
    assert body["data"]["run_id"]
    assert body["data"]["status"] == "SUCCEEDED"


def test_run_workflow_without_publish_is_not_found(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """未发布版本的 Workflow 运行 → 校验失败（不静默执行）。"""
    workflow_id = _create_workflow(client, auth_headers, name="unpublished-flow")
    response = client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers={**auth_headers, "Accept": "application/json"},
        json={"execution_mode": "INLINE"},
    )
    assert response.status_code >= 400, response.text


# -- 运行详情（重放）/ 取消 --------------------------------------------------


def test_run_detail_replay_snapshot(client: Any, auth_headers: dict[str, str]) -> None:
    """运行详情返回**重放快照**（``workflow_run`` + ``workflow_node_run``，``I-P2-06``）。"""
    workflow_id = _create_workflow(client, auth_headers, name="replay-flow")
    version = _publish_end_only(client, auth_headers, workflow_id)
    run_id = _data(
        client.post(
            f"/api/v1/workflows/{workflow_id}/run",
            headers={**auth_headers, "Accept": "application/json"},
            json={"execution_mode": "INLINE", "trigger": "api"},
        )
    )["run_id"]

    detail = client.get(f"/api/v1/workflows/{workflow_id}/runs/{run_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    replay = _data(detail)
    assert replay["run_id"] == run_id
    # 可重建不变量：**固定引用**版本（恒定）。
    assert replay["workflow_version_id"] == version["id"]
    assert replay["workflow_version_id"] != ""
    assert replay["status"] == "SUCCEEDED"
    assert replay["trigger"] == "api"


def test_cancel_workflow_run(client: Any, auth_headers: dict[str, str]) -> None:
    """取消一次**入队中**（``QUEUED`` → ``PENDING``）的运行（``→ CANCELLED``）。"""
    workflow_id = _create_workflow(client, auth_headers, name="cancel-flow")
    _publish_end_only(client, auth_headers, workflow_id)
    run_id = _data(
        client.post(
            f"/api/v1/workflows/{workflow_id}/run",
            headers={**auth_headers, "Accept": "application/json"},
            json={"execution_mode": "QUEUED"},
        )
    )["run_id"]

    cancelled = client.post(
        f"/api/v1/workflows/{workflow_id}/runs/{run_id}/cancel", headers=auth_headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert _data(cancelled)["status"] == "CANCELLED"


# -- 分层（Router 只经 AppServices，无 ORM / Runtime 直调） -------------------


def test_workflow_router_has_no_orm_or_runtime_import() -> None:
    """``routers/v1/workflows.py`` 不 import ORM / Runtime / 能力包（N-8）。"""
    from pathlib import Path

    router_path = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "api"
        / "src"
        / "astra_api"
        / "routers"
        / "v1"
        / "workflows.py"
    )
    assert router_path.is_file()
    text = router_path.read_text(encoding="utf-8")
    forbidden = [
        "import sqlalchemy",
        "from sqlalchemy",
        "astra_database",
        "import astra_runtime",
        "from astra_runtime",
        "import astra_workflow",
        "from astra_workflow",
    ]
    offenders = [token for token in forbidden if token in text]
    assert not offenders, f"Workflow Router 越界导入：{offenders}"


@pytest.mark.parametrize("dummy", [1])
def test_workflow_service_is_wired_in_app_services(dummy: int) -> None:
    """``WorkflowService`` 已登记于 ``AppServices``（组合根装配）。"""
    from astra_api.dependencies.services import AppServices
    from astra_application import WorkflowService

    assert "workflow" in {field.name for field in AppServices.__dataclass_fields__.values()}
    assert WorkflowService is not None
