"""F-4 回归：新建会话 ``workspace_id`` 必填（Erratum ``R-R1R5-E1`` / 台账 ``P2-110``）。

背景：``conversation.workspace_id`` 自 ``0006`` 起 **NOT NULL + FK**（域从不允许无工作区会话）；
旧实现将缺失 ``workspace_id`` 静默 coercion 为 ``""`` → **PG 500**（``invalid input syntax for
type uuid: ""``），SQLite ``CHAR(36)`` 掩盖。**唯一守卫点** =
``ConversationService.create_conversation``（空 / ``None`` → ``DomainError(VALIDATION_ERROR)``
→ **HTTP 422**）。

覆盖：

- ``POST /agents/{id}/run`` **新建会话**（无 ``conversation_id``）缺 ``workspace_id`` → **422**；
- 同上**带** ``workspace_id`` → **200**；
- **续聊**（带 ``conversation_id``）省略 ``workspace_id`` → **200**（服务端自既有会话派生）；
- ``POST /conversations`` 缺 ``workspace_id`` → **422**。
"""

from __future__ import annotations

from typing import Any


def _agent_with_stub_version(client: Any, headers: dict[str, str]) -> str:
    """建一个已发布 stub 版本的 Agent（避免依赖真实 Model Provider）。"""
    agent_id = client.post("/api/v1/agents", headers=headers, json={"name": "F4 Agent"}).json()[
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


def _json_headers(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Accept": "application/json"}


def test_run_new_conversation_without_workspace_is_422(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """新建会话缺 ``workspace_id`` → 422 ``VALIDATION_ERROR``（不再 PG 500）。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=_json_headers(auth_headers),
        json={"message": "hi"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_run_new_conversation_with_workspace_is_200(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """新建会话带显式 ``workspace_id`` → 200。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=_json_headers(auth_headers),
        json={"message": "hi", "workspace_id": workspace_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["conversation_id"]


def test_run_continuation_without_workspace_derives(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """续聊省略 ``workspace_id`` → 自既有会话派生 → 200。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    first = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=_json_headers(auth_headers),
        json={"message": "hi", "workspace_id": workspace_id},
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["data"]["conversation_id"]

    second = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=_json_headers(auth_headers),
        json={"message": "again", "conversation_id": conversation_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["conversation_id"] == conversation_id


def test_create_conversation_without_workspace_is_422(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """``POST /conversations`` 缺 ``workspace_id`` → 422 ``VALIDATION_ERROR``。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    response = client.post(
        "/api/v1/conversations",
        headers=auth_headers,
        json={"agent_id": agent_id, "title": "t"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_create_conversation_with_workspace_is_201(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """``POST /conversations`` 带 ``workspace_id`` → 201。"""
    agent_id = _agent_with_stub_version(client, auth_headers)
    response = client.post(
        "/api/v1/conversations",
        headers=auth_headers,
        json={"agent_id": agent_id, "title": "t", "workspace_id": workspace_id},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["workspace_id"] == workspace_id
