"""SSE 契约集成测试（W6 / T1-28；设计 §2.9；裁定 Q2/A26）。

覆盖：

- 编码器：通道映射表（既有 9 + T2-16 新增 10）/ 帧格式（``id:`` / ``event:`` / ``data:`` +
  空行）/ ``agent.message`` 的 ``content`` → ``delta`` 投影 / 未映射类型跳过 /
  心跳帧不带 ``id:``；
- 端到端：``POST /agents/{id}/run`` + ``Accept: text/event-stream`` → 200，
  ``content-type: text/event-stream``，反缓冲头 ``X-Accel-Buffering: no``，
  帧序列含 ``agent.started`` / ``message.delta`` / ``agent.completed``；
- ``Accept`` 协商：显式 JSON → 统一响应壳 + 终态 Run（**不** 406）。
"""

from __future__ import annotations

from typing import Any

from astra_api.sse.encoder import (
    SSE_CHANNEL_BY_DOMAIN_TYPE,
    channel_for,
    encode_data_frame,
    encode_heartbeat,
)

# -- 编码器（纯映射） --------------------------------------------------------


def test_channel_mapping_table_entries() -> None:
    """通道映射表逐条正确：既有 9（§2.1）+ T2-16 新增 10（裁定 §6.2，仅追加）。"""
    assert SSE_CHANNEL_BY_DOMAIN_TYPE == {
        # 既有 9（§2.1，**逐字不变**）
        "agent.started": "agent.started",
        "agent.thinking": "agent.thinking",
        "agent.message": "message.delta",
        "tool_call.started": "tool.started",
        "tool_call.completed": "tool.completed",
        "mcp_call.started": "mcp.started",
        "mcp_call.completed": "mcp.completed",
        "agent.completed": "agent.completed",
        "agent.failed": "agent.error",
        # T2-16 新增 10（仅追加）
        "skill.resolved": "skill.resolved",
        "workflow.started": "workflow.started",
        "workflow.node.started": "workflow.node.started",
        "workflow.node.completed": "workflow.node.completed",
        "workflow.completed": "workflow.completed",
        "workflow.failed": "workflow.failed",
        "knowledge.indexed": "knowledge.indexed",
        "memory.written": "memory.written",
        "approval.requested": "approval.requested",
        "approval.decided": "approval.decided",
    }
    assert channel_for("agent.message") == "message.delta"
    assert channel_for("mcp_call.completed") == "mcp.completed"
    assert channel_for("not.mapped") is None


def test_encode_data_frame_format_and_message_projection() -> None:
    """数据帧三行 + 空行；``agent.message`` 的 ``content`` 投影为 ``delta``。"""
    frame = encode_data_frame(
        seq=3,
        domain_type="agent.message",
        payload={"run_id": "r1", "message_id": "m1", "role": "assistant", "content": "hi"},
    )
    assert frame is not None
    assert frame.startswith("id: 3\nevent: message.delta\ndata: ")
    assert frame.endswith("\n\n")
    assert '"delta":"hi"' in frame
    assert '"content"' not in frame  # 原字段被投影改名


def test_encode_data_frame_skips_unmapped_type() -> None:
    """未映射领域类型 → 不产帧（``None``）。"""
    assert encode_data_frame(seq=1, domain_type="something.else", payload={}) is None


def test_heartbeat_frame_has_no_id() -> None:
    """心跳为注释帧且**不带** ``id:``（不污染 ``Last-Event-ID``）。"""
    frame = encode_heartbeat(now_ms=1234567890)
    assert frame == ": hb 1234567890\n\n"
    assert "id:" not in frame


# -- 端到端（TestClient 流式） -----------------------------------------------


def _create_agent_with_stub_version(client: Any, headers: dict[str, str]) -> str:
    """建一个已发布 stub 版本的 Agent，返回 agent_id。"""
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "SSE Agent", "type": "PRIMARY"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["data"]["id"]
    published = client.post(
        f"/api/v1/agents/{agent_id}/publish",
        headers=headers,
        json={
            "system_prompt": "You are a stub.",
            "model_config": {"provider": "stub", "model": "stub-1"},
            "runtime_config": {"max_iterations": 2},
        },
    )
    assert published.status_code == 201, published.text
    return agent_id


def test_run_agent_streams_sse_frames(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """``Accept: text/event-stream`` → SSE 帧序列 + 反缓冲头（端到端）。"""
    agent_id = _create_agent_with_stub_version(client, auth_headers)
    headers = {**auth_headers, "Accept": "text/event-stream"}

    with client.stream(
        "POST",
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"message": "hello world", "workspace_id": workspace_id},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers.get("x-accel-buffering") == "no"
        assert response.headers.get("cache-control") == "no-cache"
        raw = "".join(response.iter_text())

    frames = [frame for frame in raw.split("\n\n") if frame.strip()]
    assert frames, "未收到任何 SSE 帧"

    events = [
        line[len("event: ") :]
        for frame in frames
        for line in frame.splitlines()
        if line.startswith("event: ")
    ]
    assert "agent.started" in events
    assert "agent.thinking" in events
    assert "message.delta" in events
    assert "agent.completed" in events

    # 每个数据帧均含 id / event / data 三行。
    for frame in frames:
        lines = frame.splitlines()
        assert any(line.startswith("id: ") for line in lines)
        assert any(line.startswith("event: ") for line in lines)
        assert any(line.startswith("data: ") for line in lines)

    delta_frame = next(frame for frame in frames if "event: message.delta" in frame)
    assert '"delta"' in delta_frame

    # W6 修复回归：SSE ``id:`` 必须 == 真实 ``agent_event.seq``（逐帧 1..N，无错位）。
    ids = [
        int(line[len("id: ") :])
        for frame in frames
        for line in frame.splitlines()
        if line.startswith("id: ")
    ]
    assert ids == list(range(1, len(ids) + 1)), f"SSE id 应与真实 seq 逐帧一致：{ids}"


def test_run_agent_json_degrade(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """显式 ``Accept: application/json`` → 统一响应壳 + 终态 Run（不 406）。"""
    agent_id = _create_agent_with_stub_version(client, auth_headers)
    headers = {**auth_headers, "Accept": "application/json"}

    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"message": "hello", "workspace_id": workspace_id},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"code", "message", "data", "request_id"}
    assert body["data"]["run_id"]
    assert body["data"]["status"] in {"SUCCESS", "FAILED", "CANCELLED", "RUNNING"}


def test_run_agent_unknown_accept_does_not_406(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """任意 ``Accept``（非 SSE 且非显式排除）→ 仍返回 200（不 406）。"""
    agent_id = _create_agent_with_stub_version(client, auth_headers)
    headers = {**auth_headers, "Accept": "text/html"}
    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers=headers,
        json={"message": "hi", "workspace_id": workspace_id},
    )
    assert response.status_code == 200, response.text


def test_list_run_events_json_replay(
    client: Any, auth_headers: dict[str, str], workspace_id: str
) -> None:
    """``GET /runs/{id}/events``（JSON）回放持久化事件（``seq`` 升序）。"""
    agent_id = _create_agent_with_stub_version(client, auth_headers)
    run = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers={**auth_headers, "Accept": "application/json"},
        json={"message": "hello", "workspace_id": workspace_id},
    ).json()["data"]["run_id"]

    events = client.get(
        f"/api/v1/runs/{run}/events",
        headers={**auth_headers, "Accept": "application/json"},
    )
    assert events.status_code == 200
    data = events.json()["data"]
    assert isinstance(data, list) and data, "未回放到事件"
    seqs = [item["seq"] for item in data]
    assert seqs == sorted(seqs)
    assert any(item["type"] == "agent.started" for item in data)
