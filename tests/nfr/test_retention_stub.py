"""NFR 数据保留与清理预留（W8 / T1-38；设计 §3.1 N6 · ``N-P1-06``）。

验收口径（设计 §3.1 N6 / §2.18）：

> 本阶段给默认值「**全量落库 + 清理任务预留**」；Phase 2 起由 ``retention_policy``
> 参数化 + fake clock 快进断言。

本模块以**真实 Run**驱动，断言两件事：

1. **全量落库**：一次 Run 会**完整**持久化其生命周期记录——
   ``agent_run``（终态）/ ``message``（user·assistant·tool）/ ``tool_call``（全量输出）/
   ``agent_event``（``seq`` 连续、生命周期事件齐全）；**无静默丢弃**。
2. **清理任务预留**：Phase 1 **默认全量保留、无自动清理**——``retention_policy`` 表为
   Phase 2 预留（当前**不存在**），且历史数据在任意「年龄」下**不被清除**。

> 说明：``sandbox_session`` 的落库不在 Run 路径（由 W4 沙箱会话生命周期管理），本模块不
> 对其断言；审计 ``audit_log`` 的可写不丢由 ``I-P1-04`` / T1-09 覆盖。
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from astra_conversation import (
    SqlAgentEventRepository,
    SqlAgentRunRepository,
    SqlMessageRepository,
    SqlToolCallRepository,
)
from sqlalchemy.orm import Session, sessionmaker

from tests.e2e.fixtures.fake_sandbox import FakeSandboxProvider
from tests.e2e.fixtures.stub_provider_script import tool_call_content
from tests.e2e.fixtures.wiring import install_scripted_runtime, seed_builtin_tool

#: 生命周期事件类型（7 类产出 + 终态）；用于断言「事件齐全」。
_LIFECYCLE_TYPES = {
    "agent.started",
    "agent.thinking",
    "agent.message",
    "tool_call.started",
    "tool_call.completed",
    "agent.completed",
}


# -- 编排辅助（最小内联，避免依赖 e2e 测试模块） ------------------------------


def _create_workspace(client: Any, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "NFR Workspace", "workspace_type": "personal"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _publish_agent(
    client: Any,
    headers: dict[str, str],
    *,
    workspace_id: str,
    model_config: dict[str, Any],
    tool_name: str,
) -> str:
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "NFR Agent", "type": "PRIMARY", "workspace_id": workspace_id},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["data"]["id"]
    published = client.post(
        f"/api/v1/agents/{agent_id}/publish",
        headers=headers,
        json={
            "system_prompt": "You are a helpful agent.",
            "model_config": dict(model_config),
            "runtime_config": {"max_iterations": 3},
            "tools": [{"tool_id": tool_name, "permission_scope": {}, "enabled": True}],
        },
    )
    assert published.status_code == 201, published.text
    return agent_id


def _selected_tool(client: Any, headers: dict[str, str]) -> str:
    listing = client.get("/api/v1/tools", headers=headers)
    assert listing.status_code == 200, listing.text
    names = {item["name"] for item in listing.json()["data"]}
    assert "shell" in names, sorted(names)
    return "shell"


def _run_once(
    client: Any, headers: dict[str, str], agent_id: str, workspace_id: str, message: str
) -> tuple[str, str]:
    """跑一次 Run（JSON 模式），返回 ``(run_id, conversation_id)``。

    F-4 / Erratum ``R-R1R5-E1``：新建会话须带显式 ``workspace_id``。
    """
    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers={**headers, "Accept": "application/json"},
        json={"message": message, "workspace_id": workspace_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "SUCCESS", data
    return data["run_id"], data["conversation_id"]


def _complete_run(client: Any, headers: dict[str, str]) -> tuple[str, str]:
    """驱动一次带工具调用的完整 Run，返回 ``(run_id, conversation_id)``。"""
    scripted = install_scripted_runtime(
        client,
        [tool_call_content("shell", {"command": "echo nfr"}), "done"],
        sandbox=FakeSandboxProvider(stdout="nfr\n"),
    )
    workspace_id = _create_workspace(client, headers)
    agent_id = _publish_agent(
        client,
        headers,
        workspace_id=workspace_id,
        model_config=scripted.model_config,
        tool_name=_selected_tool(client, headers),
    )
    # W8 / A36：经真实 API 授予 shell EXECUTE ALLOW（先落 tool 行满足 FK）。
    tool_id = seed_builtin_tool(client.app.state.services, name="shell")
    granted = client.post(
        "/api/v1/tools/permissions",
        headers=headers,
        json={"tool_id": tool_id, "action": "EXECUTE", "effect": "ALLOW", "agent_id": agent_id},
    )
    assert granted.status_code == 201, granted.text
    return _run_once(client, headers, agent_id, workspace_id, "run nfr")


# -- 用例 1：全量落库 ---------------------------------------------------------


def test_run_persists_all_conversation_records(
    client: Any, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    """一次完整 Run → ``agent_run`` / ``message`` / ``tool_call`` / ``agent_event`` 全量落库。"""
    run_id, conversation_id = _complete_run(client, auth_headers)

    # agent_run 终态落库。
    run = SqlAgentRunRepository(session_factory).get(run_id)
    assert run is not None
    assert run.status == "SUCCESS"
    assert run.conversation_id == conversation_id

    # message 全量（user → assistant(工具调用) → tool → assistant(终答)）。
    messages = SqlMessageRepository(session_factory).list_by_conversation(conversation_id)
    roles = [message.role for message in messages]
    assert roles == ["user", "assistant", "tool", "assistant"], roles

    # tool_call 全量落库（含输出）。
    tool_calls = SqlToolCallRepository(session_factory).list_by_run(run_id)
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "shell"
    assert tool_calls[0].output, "tool_call.output 应全量落库"

    # agent_event 全量 + seq 连续唯一 + 生命周期事件齐全。
    events = SqlAgentEventRepository(session_factory).list_by_run(run_id)
    seqs = [event.seq for event in events]
    assert seqs == list(range(1, len(events) + 1)), seqs
    types = {event.type for event in events}
    missing = _LIFECYCLE_TYPES - types
    assert not missing, f"生命周期事件缺失：{missing}（实际 {sorted(types)}）"


# -- 用例 2：清理任务预留（Phase 1 默认全量保留，无自动清理） ------------------


def _table_names(session_factory: sessionmaker[Session]) -> set[str]:
    with session_factory() as session:
        return set(sa.inspect(session.get_bind()).get_table_names())


def test_retention_policy_table_is_reserved_for_phase2(
    client: Any, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    """``retention_policy`` 为 Phase 2 预留：Phase 1 **不建表**（清理任务仅「预留」）。"""
    _complete_run(client, auth_headers)
    tables = _table_names(session_factory)
    assert "retention_policy" not in tables, "Phase 1 不得实现 retention_policy（属 Phase 2）"


def test_default_retention_never_purges_history(
    client: Any, auth_headers: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    """把会话记录**回拨到久远过去**后仍在库——Phase 1 无自动清理（全量保留）。"""
    run_id, conversation_id = _complete_run(client, auth_headers)

    before = (
        len(SqlAgentEventRepository(session_factory).list_by_run(run_id)),
        len(SqlMessageRepository(session_factory).list_by_conversation(conversation_id)),
        len(SqlToolCallRepository(session_factory).list_by_run(run_id)),
    )
    assert all(count > 0 for count in before), before

    # 回拨时间戳（模拟「超出任何假定 TTL」的历史数据）。
    # 说明：``agent_run`` 无 ``created_at``（用 ``started_at``）；其余表用 ``created_at``。
    stale = "2000-01-01 00:00:00"
    with session_factory() as session:
        session.execute(sa.text("UPDATE agent_run SET started_at = :stale"), {"stale": stale})
        for table in ("conversation", "message", "tool_call", "agent_event"):
            session.execute(sa.text(f"UPDATE {table} SET created_at = :stale"), {"stale": stale})
        session.commit()

    # 无清理任务 → 记录原样保留（无丢失）。
    after = (
        len(SqlAgentEventRepository(session_factory).list_by_run(run_id)),
        len(SqlMessageRepository(session_factory).list_by_conversation(conversation_id)),
        len(SqlToolCallRepository(session_factory).list_by_run(run_id)),
    )
    assert after == before, f"历史数据被自动清理（预期全量保留）：{before} -> {after}"
