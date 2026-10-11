"""数据驱动三连断言集成测试（T1-22 / ``I-P1-05``）。

改 ``system_prompt`` → ContextManager 首条 system 消息变化；
改 ``agent_tool`` → 工具解析集合变化；
编辑后 ``agent_version.id`` 变化且旧版本字段哈希不变（不可变）。
"""

from __future__ import annotations

import hashlib
import json

from astra_agent import build_agent_services
from astra_model import ChatMessage
from astra_runtime import ContextManager, PromptManager


def _hash(version) -> str:  # noqa: ANN001
    raw = json.dumps(
        {
            "system_prompt": version.system_prompt,
            "model_config": version.model_config,
            "runtime_config": version.runtime_config,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_data_driven_system_prompt_and_tools(session_factory) -> None:  # noqa: ANN001
    services = build_agent_services(session_factory)
    service = services.agent_service
    agent = service.create_agent(tenant_id="t1", name="A", created_by="u1")

    v1 = service.publish_version(
        agent_id=agent.id,
        system_prompt="PROMPT-A",
        model_config={"provider": "stub", "model": "m1"},
        runtime_config={"max_iterations": 3},
        created_by="u1",
    )
    service.bind_tool(
        tenant_id="t1",
        agent_version_id=v1.id,
        tool_id="tool-fs",
        permission_scope={"allow": ["read"]},
    )
    h1 = _hash(v1)

    prompt_manager = PromptManager()
    context_manager = ContextManager()

    agent_after = service.get_agent(agent.id)
    loaded1 = service.load_version(agent_after)
    messages1 = context_manager.build(
        system_prompt=prompt_manager.load_system_prompt(loaded1),
        history=[ChatMessage(role="user", content="hi")],
    )
    assert messages1[0].role == "system"
    assert messages1[0].content == "PROMPT-A"
    assert [tool.tool_id for tool in service.tools_for_version(loaded1.id)] == ["tool-fs"]

    # -- 发布 v2：改 prompt + 改 tool --------------------------------------
    v2 = service.publish_version(
        agent_id=agent.id,
        system_prompt="PROMPT-B",
        model_config={"provider": "stub", "model": "m1"},
        runtime_config={"max_iterations": 5},
        created_by="u1",
    )
    service.bind_tool(tenant_id="t1", agent_version_id=v2.id, tool_id="tool-git")

    assert v2.id != v1.id
    agent_after2 = service.get_agent(agent.id)
    loaded2 = service.load_version(agent_after2)
    assert loaded2.id == v2.id

    messages2 = context_manager.build(
        system_prompt=prompt_manager.load_system_prompt(loaded2),
        history=[ChatMessage(role="user", content="hi")],
    )
    assert messages2[0].content == "PROMPT-B"  # 首条 system 变化
    assert [tool.tool_id for tool in service.tools_for_version(loaded2.id)] == ["tool-git"]

    # -- 旧版本不可变 -------------------------------------------------------
    v1_reloaded = service.load_version(agent_after2, v1.id)
    assert _hash(v1_reloaded) == h1


def test_execution_loads_explicit_version(session_factory) -> None:  # noqa: ANN001
    services = build_agent_services(session_factory)
    service = services.agent_service
    agent = service.create_agent(tenant_id="t1", name="A", created_by="u1")
    v1 = service.publish_version(
        agent_id=agent.id,
        system_prompt="P1",
        model_config={"provider": "stub", "model": "m1"},
        runtime_config={},
        created_by="u1",
    )
    v2 = service.publish_version(
        agent_id=agent.id,
        system_prompt="P2",
        model_config={"provider": "stub", "model": "m1"},
        runtime_config={},
        created_by="u1",
    )
    agent_after = service.get_agent(agent.id)
    # 执行时总是加载一个明确 version（可重建）。
    assert service.load_version(agent_after, v1.id).system_prompt == "P1"
    assert service.load_version(agent_after, v2.id).system_prompt == "P2"
