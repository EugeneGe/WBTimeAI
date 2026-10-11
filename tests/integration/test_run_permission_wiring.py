"""Run 权限装配集成测试（W8 / A36 裁定 §5.2-②；验 ``E-P1-01``）。

走**真实**组合根（``build_app_services``）+ ``TestClient`` + 真实 ``POST /tools/permissions``
授权 + ``POST /agents/{id}/run``（**不**注入替身 checker），验证：

1. **经授权 → 放行**：授予 ``(agent_id, <真实 tool id>, EXECUTE, ALLOW)`` → ``tool_call.status``
   ``SUCCESS``，且工具**经 Sandbox 执行**；
2. **未授权 → DENY**：不授予 → ``tool_call.status`` ``DENIED``（deny-by-default 在真实路径生效）；
3. **per-run 隔离不串扰**：Agent A（授权）/ Agent B（未授权）**交替**驱动 → A ``SUCCESS``、
   B ``DENIED``，**互不影响**（对齐 A35 探针范式）；且 ``ToolExecutor`` 单例校验器**未被写回**。

> 说明：模型 Provider / 沙箱 Provider 为合理替身（外部能力）；**权限**链路走真实装配——
> ``AgentRunService`` 按 ``run.agent_id`` per-run 解析授权、构造**独立**
> ``RuntimePermissionChecker`` 注入本次执行（裁定 §3 / §4）。
"""

from __future__ import annotations

from typing import Any

from astra_conversation import SqlToolCallRepository

from tests.e2e.fixtures.fake_sandbox import FakeSandboxProvider
from tests.e2e.fixtures.stub_provider_script import tool_call_content
from tests.e2e.fixtures.wiring import install_scripted_runtime, seed_builtin_tool

TOOL_NAME = "shell"


def _create_workspace(client: Any, headers: dict[str, str]) -> str:
    """创建 Workspace，返回 id。"""
    response = client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "Wiring Workspace", "workspace_type": "personal"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _register_model(client: Any, headers: dict[str, str], workspace_id: str) -> None:
    """注册模型提供方 + 模型（供发布版本引用；实际经脚本化替身路由）。"""
    provider = client.post(
        "/api/v1/models/providers",
        headers=headers,
        json={
            "name": "wiring-openai",
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
        json={"name": "gpt-wiring", "model_type": "CHAT", "context_window": 128000},
    )
    assert model.status_code == 201, model.text


def _publish_agent(
    client: Any, headers: dict[str, str], *, workspace_id: str, model_config: dict[str, Any]
) -> str:
    """创建 + 发布一个绑定 ``shell`` 工具的 Agent，返回 ``agent_id``。"""
    created = client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Wiring Agent",
            "type": "PRIMARY",
            "workspace_id": workspace_id,
            "description": "权限装配集成测试 Agent",
        },
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
            "tools": [{"tool_id": TOOL_NAME, "permission_scope": {}, "enabled": True}],
        },
    )
    assert published.status_code == 201, published.text
    return agent_id


def _grant_shell(client: Any, headers: dict[str, str], *, agent_id: str) -> str:
    """经真实 API 授予 ``(agent_id, shell, EXECUTE, ALLOW)``，返回真实 ``tool_id``。"""
    tool_id = seed_builtin_tool(client.app.state.services, name=TOOL_NAME)
    response = client.post(
        "/api/v1/tools/permissions",
        headers=headers,
        json={
            "tool_id": tool_id,
            "action": "EXECUTE",
            "effect": "ALLOW",
            "agent_id": agent_id,
        },
    )
    assert response.status_code == 201, response.text
    return tool_id


def _run(client: Any, headers: dict[str, str], agent_id: str, *, message: str) -> str:
    """以 JSON 模式运行一次 Agent，返回 ``run_id``。"""
    response = client.post(
        f"/api/v1/agents/{agent_id}/run",
        headers={**headers, "Accept": "application/json"},
        json={"message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["run_id"]


def _tool_calls(client: Any, run_id: str) -> list[Any]:
    """读回某 Run 的 ``tool_call`` 行。"""
    repository = SqlToolCallRepository(client.app.state.services.providers.database.session_factory)
    return repository.list_by_run(run_id)


def test_authorized_agent_run_allows_tool_via_real_api(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """经授权 → 放行：``POST /tools/permissions`` 授权后 ``tool_call.status == SUCCESS``。"""
    scripted = install_scripted_runtime(
        client,
        [tool_call_content(TOOL_NAME, {"command": "echo hello"}), "done"],
        sandbox=FakeSandboxProvider(stdout="hello\n"),
    )
    workspace_id = _create_workspace(client, auth_headers)
    _register_model(client, auth_headers, workspace_id)
    agent_id = _publish_agent(
        client, auth_headers, workspace_id=workspace_id, model_config=scripted.model_config
    )
    _grant_shell(client, auth_headers, agent_id=agent_id)

    run_id = _run(client, auth_headers, agent_id, message="run shell")

    tool_calls = _tool_calls(client, run_id)
    assert len(tool_calls) == 1, [tool_call.status for tool_call in tool_calls]
    assert tool_calls[0].status == "SUCCESS", tool_calls[0].status
    # 工具经 Fake 沙箱**真实执行**（授权放行后方可达）。
    assert scripted.sandbox.exec_calls == 1
    assert scripted.sandbox.commands == [["echo", "hello"]]


def test_unauthorized_agent_run_denies_tool_via_real_api(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """未授权 → DENY：不授予权限 → ``tool_call.status == DENIED``，工具**不执行**。"""
    scripted = install_scripted_runtime(
        client,
        [tool_call_content(TOOL_NAME, {"command": "echo nope"}), "denied"],
        sandbox=FakeSandboxProvider(stdout="nope\n"),
    )
    workspace_id = _create_workspace(client, auth_headers)
    _register_model(client, auth_headers, workspace_id)
    agent_id = _publish_agent(
        client, auth_headers, workspace_id=workspace_id, model_config=scripted.model_config
    )
    # 有意不授权。

    run_id = _run(client, auth_headers, agent_id, message="run shell")

    tool_calls = _tool_calls(client, run_id)
    assert len(tool_calls) == 1, [tool_call.status for tool_call in tool_calls]
    assert tool_calls[0].status == "DENIED", tool_calls[0].status
    assert tool_calls[0].error, "DENIED 应带拒绝原因"
    assert scripted.sandbox.exec_calls == 0
    assert scripted.sandbox.created == 0


def test_per_run_checkers_are_isolated(client: Any, auth_headers: dict[str, str]) -> None:
    """per-run 隔离：A（授权）SUCCESS / B（未授权）DENIED，交替驱动互不串扰。"""
    # 三次 Run（A→B→A），每次消耗「工具调用 + 终答」两条脚本。
    scripted = install_scripted_runtime(
        client,
        [
            tool_call_content(TOOL_NAME, {"command": "echo a"}),
            "done-a",
            tool_call_content(TOOL_NAME, {"command": "echo b"}),
            "done-b",
            tool_call_content(TOOL_NAME, {"command": "echo a"}),
            "done-a",
        ],
        sandbox=FakeSandboxProvider(stdout="a\n"),
    )
    workspace_id = _create_workspace(client, auth_headers)
    _register_model(client, auth_headers, workspace_id)

    agent_a = _publish_agent(
        client, auth_headers, workspace_id=workspace_id, model_config=scripted.model_config
    )
    agent_b = _publish_agent(
        client, auth_headers, workspace_id=workspace_id, model_config=scripted.model_config
    )
    _grant_shell(client, auth_headers, agent_id=agent_a)  # 仅 A 授权。

    runtime = client.app.state.services.agent_run.runtime
    singleton_checker = runtime.execution_manager._tool_executor._checker  # noqa: SLF001 - 隔离探针

    # 交替驱动：A → B → A（若单例缓存 per-agent 规则，B 将串到 A 的 ALLOW）。
    run_a1 = _run(client, auth_headers, agent_a, message="a1")
    run_b1 = _run(client, auth_headers, agent_b, message="b1")
    run_a2 = _run(client, auth_headers, agent_a, message="a2")

    assert _tool_calls(client, run_a1)[0].status == "SUCCESS"
    assert _tool_calls(client, run_b1)[0].status == "DENIED"
    assert _tool_calls(client, run_a2)[0].status == "SUCCESS"

    # 单例校验器**未被写回** per-agent 规则（仍为装配期默认 = 无规则，deny-by-default）。
    assert runtime.execution_manager._tool_executor._checker is singleton_checker  # noqa: SLF001
    assert singleton_checker.delegate._rules == {}  # noqa: SLF001
