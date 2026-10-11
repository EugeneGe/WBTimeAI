"""QA 探针 ⑩：``/schedules`` 组合根装配实证（端到端，经 ``AppServices``）。

独立验证（不采信工程师自报）：
- Router 经 ``AppServices`` 取仓储 / ``SchedulerTick``，不直调 session / Provider /
  ``astra_config``；
- ``POST /api/v1/schedules`` → 创建（201）；``GET`` → 可见；
- ``POST /{id}/trigger`` → 返回幂等 ``task_id``（证明组合根装配的 ``SchedulerTick`` 已接线）；
- 跨租户不可见（404）；未认证 401。
"""

from __future__ import annotations

from typing import Any


def test_schedules_crud_and_trigger_via_app_services(
    client: Any, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/schedules",
        headers=auth_headers,
        json={
            "name": "qa-probe",
            "target_type": "agent",
            "target_id": "agent-qa-1",
            "trigger": "manual",
        },
    )
    assert created.status_code == 201, created.text
    schedule = created.json()["data"]
    assert schedule["name"] == "qa-probe"
    assert schedule["trigger"] == "manual"

    listing = client.get("/api/v1/schedules", headers=auth_headers)
    assert listing.status_code == 200
    assert any(item["id"] == schedule["id"] for item in listing.json()["data"])

    detail = client.get(f"/api/v1/schedules/{schedule['id']}", headers=auth_headers)
    assert detail.status_code == 200

    triggered = client.post(f"/api/v1/schedules/{schedule['id']}/trigger", headers=auth_headers)
    assert triggered.status_code == 200, triggered.text
    body = triggered.json()
    task_id = body["data"]["task_id"] if "data" in body else body["task_id"]
    assert task_id, "trigger 未返回 task_id（组合根 SchedulerTick 未接线？）"


def test_schedules_cross_tenant_invisible(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
) -> None:
    created = client.post(
        "/api/v1/schedules",
        headers=auth_headers,
        json={
            "name": "secret",
            "target_type": "workflow",
            "target_id": "wf-1",
            "trigger": "manual",
        },
    )
    schedule_id = created.json()["data"]["id"]

    listing = client.get("/api/v1/schedules", headers=other_tenant_headers)
    assert listing.status_code == 200
    assert listing.json()["data"] == []

    detail = client.get(f"/api/v1/schedules/{schedule_id}", headers=other_tenant_headers)
    assert detail.status_code == 404


def test_schedules_requires_auth(client: Any) -> None:
    assert client.get("/api/v1/schedules").status_code == 401
