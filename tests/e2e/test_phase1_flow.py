"""Phase 1 全链路端到端（W8 / T1-36；设计 §2.17 / §3-#1 ``E-P1-01``）。

覆盖完成标准全链路：

    创建 Coding Agent → 选模型 → 配 Prompt → 选 Tool → 绑 Workspace →
    聊天（SSE）→ 自主调 Tool → Sandbox 执行 → 返回结果

驱动方式：**脚本化** ``ScriptedModelProvider`` + ``FakeSandboxProvider``（确定性替身），
走**真实** HTTP / ``TestClient`` / 路由 / SSE 编码路径。断言：

1. SSE 帧序列（通道 + 关键 payload + ``seq`` 顺序）== golden 列表（规范化易变字段后）；
2. 连续 20 轮对话不崩溃、消息 / 事件可预期；
3. 单次 100KB 工具输出不崩溃：工具输出**全量落库**、喂模型副本按上下文窗口**截断**。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.e2e.fixtures.fake_sandbox import FakeSandboxProvider
from tests.e2e.fixtures.stub_provider_script import tool_call_content
from tests.e2e.fixtures.wiring import install_scripted_runtime, seed_builtin_tool

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "phase1_sse_frames.json"

#: golden 中已知的**易变字段** → 占位符（比对前规范化，规避 flaky）。
_VOLATILE_KEYS: dict[str, str] = {
    "run_id": "<RUN_ID>",
    "agent_id": "<AGENT_ID>",
    "agent_version_id": "<VERSION_ID>",
    "conversation_id": "<CONVERSATION_ID>",
    "message_id": "<MESSAGE_ID>",
    "tool_call_id": "<TOOL_CALL_ID>",
    "duration_ms": "<MS>",
}

#: 100KB 工具输出的字节数（验证截断 / 落库边界）。
BIG_OUTPUT_CHARS = 100_000

#: 上下文窗口中工具输出喂模型的字符上限（``DEFAULT_TOOL_OUTPUT_MAX_CHARS``）。
TOOL_OUTPUT_MAX_CHARS = 8_000


# -- SSE 帧解析 / 规范化 ------------------------------------------------------


def _parse_data_frames(raw: str) -> list[dict[str, Any]]:
    """把原始 SSE 文本解析为数据帧列表（丢弃心跳 / 注释帧）。"""
    frames: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or lines[0].startswith(":"):
            continue  # 心跳 / 注释帧（``: hb <ms>``）不计入数据帧序列
        frame: dict[str, Any] = {}
        for line in lines:
            if line.startswith("id: "):
                frame["id"] = int(line[len("id: ") :])
            elif line.startswith("event: "):
                frame["event"] = line[len("event: ") :]
            elif line.startswith("data: "):
                frame["data"] = json.loads(line[len("data: ") :])
        if "event" in frame:
            frames.append(frame)
    return frames


def _normalize_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """规范化一帧：易变字段（id / 时间戳）替换为占位符，键集与顺序稳定。"""
    data = dict(frame.get("data") or {})
    for key, placeholder in _VOLATILE_KEYS.items():
        if key in data:
            data[key] = placeholder
    return {"id": frame["id"], "event": frame["event"], "data": data}


def _load_golden() -> list[dict[str, Any]]:
    """读取 golden 帧序列。"""
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return payload["frames"]


# -- 全链路编排辅助 -----------------------------------------------------------


def _create_workspace(client: Any, headers: dict[str, str]) -> str:
    """创建 Workspace，返回 id。"""
    response = client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "E2E Workspace", "workspace_type": "personal"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _select_model(client: Any, headers: dict[str, str], workspace_id: str) -> str:
    """注册模型提供方 + 模型（「选模型」步），返回模型名。"""
    provider = client.post(
        "/api/v1/models/providers",
        headers=headers,
        json={
            "name": "e2e-openai",
            "provider_type": "openai",
            "endpoint": "https://api.openai.com/v1",
            "workspace_id": workspace_id,
        },
    )
    assert provider.status_code == 201, provider.text
    provider_id = provider.json()["data"]["id"]
    model = client.post(
        f"/api/v1/models/providers/{provider_id}/models",
        headers=headers,
        json={"name": "gpt-e2e", "model_type": "CHAT", "context_window": 128000},
    )
    assert model.status_code == 201, model.text
    return model.json()["data"]["name"]


def _select_tool(client: Any, headers: dict[str, str]) -> str:
    """浏览内置工具（「选 Tool」步），返回所选工具名。"""
    listing = client.get("/api/v1/tools", headers=headers)
    assert listing.status_code == 200, listing.text
    names = {item["name"] for item in listing.json()["data"]}
    assert "shell" in names, f"内置工具表应含 shell：{sorted(names)}"
    return "shell"


def _grant_tool_permission(
    client: Any,
    headers: dict[str, str],
    *,
    agent_id: str,
    tool_name: str = "shell",
    action: str = "EXECUTE",
    effect: str = "ALLOW",
) -> str:
    """经**真实 API** 授予 ``(agent_id, tool, action, effect)``，返回真实 ``tool_id``。

    内置工具仅注册在内存注册表、**未持久化** ``tool`` 表，而 ``tool_permission.tool_id`` 为
    FK → ``tool.id``；故先落一条 ``tool`` 行（{func}`seed_builtin_tool`）并以**真实 id** 授权
    （W8 / A36 裁定 §5.3）——保证 SQLite 与 Postgres 双引擎下 FK 合法。
    """
    tool_id = seed_builtin_tool(client.app.state.services, name=tool_name)
    response = client.post(
        "/api/v1/tools/permissions",
        headers=headers,
        json={
            "tool_id": tool_id,
            "action": action,
            "effect": effect,
            "agent_id": agent_id,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["tool_id"] == tool_id
    return tool_id


def _publish_coding_agent(
    client: Any,
    headers: dict[str, str],
    *,
    workspace_id: str,
    model_config: dict[str, Any],
    tool_name: str,
) -> str:
    """创建 Coding Agent + 发布版本（配 Prompt / 选模型 / 绑 Tool / 绑 Workspace）。

    Returns:
        ``agent_id``。
    """
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "E2E Coding Agent",
            "type": "PRIMARY",
            "workspace_id": workspace_id,
            "description": "端到端全链路 Agent",
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["data"]["id"]

    published = client.post(
        f"/api/v1/agents/{agent_id}/publish",
        headers=headers,
        json={
            "system_prompt": "You are a helpful coding agent.",
            "model_config": dict(model_config),
            "runtime_config": {"max_iterations": 3},
            "tools": [{"tool_id": tool_name, "permission_scope": {}, "enabled": True}],
        },
    )
    assert published.status_code == 201, published.text
    return agent_id


def _run_sse(
    client: Any,
    headers: dict[str, str],
    agent_id: str,
    *,
    workspace_id: str,
    message: str,
    conversation_id: str | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """以 SSE 运行一次 Agent，返回 ``(run_id, raw_frames, normalized_frames)``。

    F-4 / Erratum ``R-R1R5-E1``：**新建会话**须带显式 ``workspace_id``。
    """
    payload: dict[str, Any] = {"message": message, "workspace_id": workspace_id}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    with client.stream(
        "POST",
        f"/api/v1/agents/{agent_id}/run",
        headers={**headers, "Accept": "text/event-stream"},
        json=payload,
    ) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers.get("x-accel-buffering") == "no"
        raw = "".join(response.iter_text())

    raw_frames = _parse_data_frames(raw)
    assert raw_frames, "未收到任何 SSE 数据帧"
    run_id = raw_frames[0]["data"]["run_id"]
    return run_id, raw_frames, [_normalize_frame(frame) for frame in raw_frames]


# -- 用例 1：全链路 SSE 帧序列 == golden --------------------------------------


def test_phase1_full_chain_sse_matches_golden(client: Any, auth_headers: dict[str, str]) -> None:
    """创建 Coding Agent → … → Sandbox 执行 → 返回结果；SSE 帧序列 == golden。"""
    # 注入确定性替身：脚本先产一次 shell 工具调用、再产最终答复。
    scripted = install_scripted_runtime(
        client,
        [tool_call_content("shell", {"command": "echo hello"}), "All done: hello"],
        sandbox=FakeSandboxProvider(stdout="hello\n"),
    )

    workspace_id = _create_workspace(client, auth_headers)
    _select_model(client, auth_headers, workspace_id)
    tool_name = _select_tool(client, auth_headers)
    agent_id = _publish_coding_agent(
        client,
        auth_headers,
        workspace_id=workspace_id,
        model_config=scripted.model_config,
        tool_name=tool_name,
    )
    # 真实权限路径：经 ``POST /tools/permissions`` 授予 shell EXECUTE ALLOW（非替身 checker）。
    _grant_tool_permission(client, auth_headers, agent_id=agent_id, tool_name=tool_name)

    run_id, _raw_frames, normalized = _run_sse(
        client, auth_headers, agent_id, workspace_id=workspace_id, message="请用 shell 打印 hello"
    )

    # 1) SSE 帧序列（通道 + 关键 payload + seq 顺序）逐帧 == golden。
    assert normalized == _load_golden(), json.dumps(normalized, ensure_ascii=False, indent=2)

    # 2) 模型被选中（脚本内容确实经选定 provider 路由）；工具经 Fake 沙箱执行。
    assert scripted.provider.calls == 2, "应恰好两次模型调用（工具调用 + 最终答复）"
    assert scripted.sandbox.created >= 1 and scripted.sandbox.exec_calls >= 1
    assert scripted.sandbox.commands and scripted.sandbox.commands[0] == ["echo", "hello"]

    # 3) Run 终态为 SUCCESS（真实 HTTP 读回），对话消息落库。
    run = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers)
    assert run.status_code == 200, run.text
    assert run.json()["data"]["status"] == "SUCCESS"
    conversation_id = run.json()["data"]["conversation_id"]
    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    ).json()["data"]
    roles = [message["role"] for message in messages]
    assert roles == ["user", "assistant", "tool", "assistant"], roles


def test_phase1_full_chain_sse_is_deterministic(client: Any, auth_headers: dict[str, str]) -> None:
    """同一脚本两次全链路运行 → 规范化帧序列完全一致（非 flaky 证据）。"""

    def _one_run() -> list[dict[str, Any]]:
        scripted = install_scripted_runtime(
            client,
            [tool_call_content("shell", {"command": "echo hello"}), "All done: hello"],
            sandbox=FakeSandboxProvider(stdout="hello\n"),
        )
        workspace_id = _create_workspace(client, auth_headers)
        agent_id = _publish_coding_agent(
            client,
            auth_headers,
            workspace_id=workspace_id,
            model_config=scripted.model_config,
            tool_name=_select_tool(client, auth_headers),
        )
        _grant_tool_permission(client, auth_headers, agent_id=agent_id)
        _run_id, _raw, normalized = _run_sse(
            client,
            auth_headers,
            agent_id,
            workspace_id=workspace_id,
            message="请用 shell 打印 hello",
        )
        return normalized

    first = _one_run()
    second = _one_run()
    assert first == second == _load_golden()


# -- 用例 2：20 轮对话 + 100KB 工具输出 ---------------------------------------


def test_phase1_twenty_turns_do_not_crash(client: Any, auth_headers: dict[str, str]) -> None:
    """连续 20 轮对话：每轮 Run 成功、消息线性增长、无崩溃。"""
    scripted = install_scripted_runtime(client, ["ack"], sandbox=FakeSandboxProvider())
    workspace_id = _create_workspace(client, auth_headers)
    agent_id = _publish_coding_agent(
        client,
        auth_headers,
        workspace_id=workspace_id,
        model_config=scripted.model_config,
        tool_name=_select_tool(client, auth_headers),
    )

    conversation_id: str | None = None
    for turn in range(1, 21):
        body = {"message": f"turn {turn}", "workspace_id": workspace_id}
        if conversation_id is not None:
            body["conversation_id"] = conversation_id
        response = client.post(
            f"/api/v1/agents/{agent_id}/run",
            headers={**auth_headers, "Accept": "application/json"},
            json=body,
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "SUCCESS", data
        conversation_id = data["conversation_id"] or conversation_id

    assert conversation_id is not None
    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    ).json()["data"]
    # 20 轮 × (user + assistant) —— 会话历史线性增长，无丢失 / 无重复执行。
    assert len(messages) == 40, len(messages)
    assert scripted.provider.calls == 20


def test_phase1_100kb_tool_output_truncated_and_persisted(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """单次 100KB 工具输出：全量落库 ``tool_call.output``，喂模型副本按窗口截断。"""
    big_output = "x" * BIG_OUTPUT_CHARS
    scripted = install_scripted_runtime(
        client,
        [tool_call_content("shell", {"command": "echo big"}), "done"],
        sandbox=FakeSandboxProvider(stdout=big_output),
    )
    workspace_id = _create_workspace(client, auth_headers)
    agent_id = _publish_coding_agent(
        client,
        auth_headers,
        workspace_id=workspace_id,
        model_config=scripted.model_config,
        tool_name=_select_tool(client, auth_headers),
    )
    _grant_tool_permission(client, auth_headers, agent_id=agent_id)

    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers={**auth_headers, "Accept": "application/json"},
        json={"message": "echo big", "workspace_id": workspace_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "SUCCESS", data
    run_id = data["run_id"]
    conversation_id = data["conversation_id"]

    # 1) 工具输出**全量落库**（tool_call.output 未截断）。
    from astra_conversation import SqlToolCallRepository

    tool_calls = SqlToolCallRepository(session_factory).list_by_run(run_id)
    assert len(tool_calls) == 1
    persisted = tool_calls[0].output or {}
    stored_value = str(persisted.get("value", ""))
    assert len(stored_value) == BIG_OUTPUT_CHARS, len(stored_value)

    # 2) 喂模型的工具消息副本按上下文窗口截断（§2.7.1，附 ``[...truncated N chars]`` 标记）。
    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    ).json()["data"]
    tool_messages = [message for message in messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    content = tool_messages[0]["content"]
    assert content.startswith('{"value": "')
    assert content.endswith(" chars]") and "[...truncated " in content
    # 保留 8000 字符 + 截断标记；远小于 100KB 全量。
    assert TOOL_OUTPUT_MAX_CHARS <= len(content) < TOOL_OUTPUT_MAX_CHARS + 64
    assert len(content) < BIG_OUTPUT_CHARS


# -- 用例 3：未授权 → DENIED（固化真实路径 deny-by-default） -------------------


def test_phase1_tool_call_denied_without_permission(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """**不**授予 ``tool_permission`` → 真实路径下 ``tool_call`` 恒 ``DENIED``（deny-by-default）。

    W8 / A36：修复仅补齐「经授权放行」，**未**引入任何默认放行——未授权一律 DENIED，
    且 DENIED **不执行**工具（沙箱零调用）。
    """
    scripted = install_scripted_runtime(
        client,
        [tool_call_content("shell", {"command": "echo nope"}), "denied"],
        sandbox=FakeSandboxProvider(stdout="nope\n"),
    )
    workspace_id = _create_workspace(client, auth_headers)
    _select_model(client, auth_headers, workspace_id)
    tool_name = _select_tool(client, auth_headers)
    agent_id = _publish_coding_agent(
        client,
        auth_headers,
        workspace_id=workspace_id,
        model_config=scripted.model_config,
        tool_name=tool_name,
    )
    # 🔴 有意**不**调用 ``_grant_tool_permission`` —— 未授权。

    run_id, _raw_frames, _normalized = _run_sse(
        client, auth_headers, agent_id, workspace_id=workspace_id, message="未授权调用 shell"
    )

    # tool_call 落库为 DENIED（deny-by-default 在真实路径生效）。
    from astra_conversation import SqlToolCallRepository

    tool_calls = SqlToolCallRepository(
        client.app.state.services.providers.database.session_factory
    ).list_by_run(run_id)
    assert len(tool_calls) == 1, [tool_call.status for tool_call in tool_calls]
    assert tool_calls[0].status == "DENIED", tool_calls[0].status
    assert tool_calls[0].error, "DENIED 应带拒绝原因"

    # DENIED 不执行：沙箱零调用。
    assert scripted.sandbox.exec_calls == 0
    assert scripted.sandbox.created == 0

    # Run 仍成功（模型给最终答复），但工具未执行、无输出落库。
    run = client.get(f"/api/v1/runs/{run_id}", headers=auth_headers)
    assert run.status_code == 200, run.text
    assert run.json()["data"]["status"] == "SUCCESS"
    assert tool_calls[0].output is None
