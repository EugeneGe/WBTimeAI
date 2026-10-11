"""幂等（``Idempotency-Key``）集成测试（W6 / T1-29；设计 §2.13.1；裁定 Q4/A28）。

覆盖：

- **同键同体** → 复用首次 Run（**相同 ``run_id``**，不重复执行 / 不重复建 Run）；
- **同键不同体** → ``409`` + ``code=IDEMPOTENCY_KEY_REUSE``；
- 键作用域 ``(tenant_id, idempotency_key)``（``0006`` 已建唯一索引，**无需迁移**）。
"""

from __future__ import annotations

from typing import Any

from astra_conversation import SqlAgentRunRepository


def _agent_with_stub_version(client: Any, headers: dict[str, str]) -> str:
    """建一个已发布 stub 版本的 Agent。"""
    agent_id = client.post("/api/v1/agents", headers=headers, json={"name": "Idem Agent"}).json()[
        "data"
    ]["id"]
    published = client.post(
        f"/api/v1/agents/{agent_id}/publish",
        headers=headers,
        json={
            "system_prompt": "stub",
            "model_config": {"provider": "stub", "model": "stub-1"},
            "runtime_config": {"max_iterations": 1},
        },
    )
    assert published.status_code == 201, published.text
    return agent_id


def test_same_key_same_body_reuses_first_run(
    client: Any,
    auth_headers: dict[str, str],
    session_factory: Any,
    workspace_id: str,
) -> None:
    """同键同体：第二次请求复用首次 Run（相同 ``run_id``），库中仅一条 Run。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    headers = {**auth_headers, "Accept": "application/json", "Idempotency-Key": "idem-same"}
    body = {"message": "hello", "workspace_id": workspace_id}

    first = client.post(f"/api/v1/agents/{agent_id}/run", headers=headers, json=body)
    assert first.status_code == 200, first.text
    run_id = first.json()["data"]["run_id"]

    second = client.post(f"/api/v1/agents/{agent_id}/run", headers=headers, json=body)
    assert second.status_code == 200, second.text
    assert second.json()["data"]["run_id"] == run_id

    runs = SqlAgentRunRepository(session_factory).list(agent_id=agent_id)
    assert len(runs) == 1, "同键同体不应重复建 Run"


def test_same_key_different_body_conflicts(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """同键不同体：第二次请求 → 409 + ``IDEMPOTENCY_KEY_REUSE``。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    headers = {**auth_headers, "Accept": "application/json", "Idempotency-Key": "idem-diff"}

    first = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"message": "a", "workspace_id": workspace_id},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"message": "b", "workspace_id": workspace_id},
    )
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_without_key_creates_distinct_runs(
    client: Any,
    auth_headers: dict[str, str],
    session_factory: Any,
    workspace_id: str,
) -> None:
    """无 ``Idempotency-Key``：每次请求各建一条 Run（不启用幂等）。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    headers = {**auth_headers, "Accept": "application/json"}
    first = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"message": "x", "workspace_id": workspace_id},
    )
    second = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"message": "x", "workspace_id": workspace_id},
    )
    assert first.json()["data"]["run_id"] != second.json()["data"]["run_id"]
    assert len(SqlAgentRunRepository(session_factory).list(agent_id=agent_id)) == 2
