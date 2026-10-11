"""事件清单扫描断言（W3 / T2-16；设计 §2.11；裁定 §6；验收 ``I-P2-16``）。

覆盖：

- 5 个新增事件模块（``skill`` / ``workflow`` / ``knowledge`` / ``memory`` / ``approval``）存在，
  且 **不新建** ``events/mcp.py``（Errata-B）；
- 全部新增事件**继承** ``astra_core.events.DomainEvent``（基类唯一，C-02）；
- ``type`` 字符串与设计 §2.11 逐字一致，且**前缀匹配模块族**；
- 事件从 ``astra_event.events`` 与 ``astra_event`` 导出；
- ``EventBus`` Protocol 接口**不变**（``publish`` / ``subscribe`` / ``unsubscribe``），
  新事件经 ``LocalEventBus`` **发布且被消费**（替换总线实现不改上层，C-02）；
- SSE 通道映射（``SSE_CHANNEL_BY_DOMAIN_TYPE``）**仅追加**，不破坏既有 9 类契约。
"""

from __future__ import annotations

import importlib.util

import pytest
from astra_core import DomainEvent

#: 新增事件模块 → 该类模块承载的（事件类名 → ``type``）。
NEW_EVENT_MODULES: dict[str, dict[str, str]] = {
    "skill": {"SkillResolved": "skill.resolved"},
    "workflow": {
        "WorkflowStarted": "workflow.started",
        "WorkflowNodeStarted": "workflow.node.started",
        "WorkflowNodeCompleted": "workflow.node.completed",
        "WorkflowCompleted": "workflow.completed",
        "WorkflowFailed": "workflow.failed",
    },
    "knowledge": {"KnowledgeIndexed": "knowledge.indexed"},
    "memory": {"MemoryWritten": "memory.written"},
    "approval": {
        "ApprovalRequested": "approval.requested",
        "ApprovalDecided": "approval.decided",
    },
}

#: Phase 1 §2.9 既有 9 类 → SSE 通道（**不得改动**）。
EXISTING_SSE_MAP: dict[str, str] = {
    "agent.started": "agent.started",
    "agent.thinking": "agent.thinking",
    "agent.message": "message.delta",
    "tool_call.started": "tool.started",
    "tool_call.completed": "tool.completed",
    "mcp_call.started": "mcp.started",
    "mcp_call.completed": "mcp.completed",
    "agent.completed": "agent.completed",
    "agent.failed": "agent.error",
}

#: T2-16 新增 SSE 通道（仅追加）。
NEW_SSE_MAP: dict[str, str] = {
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


def _all_new_events() -> dict[str, type[DomainEvent]]:
    """返回全部新增事件（类名 → 类）。"""
    import astra_event

    names = [name for module in NEW_EVENT_MODULES.values() for name in module]
    return {name: getattr(astra_event, name) for name in names}


def test_new_event_modules_present_and_no_mcp_module() -> None:
    """5 个新增模块存在；**不新建** ``events/mcp.py``（MCPCall* 仍在 ``agent.py``）。"""
    for module in NEW_EVENT_MODULES:
        spec = importlib.util.find_spec(f"astra_event.events.{module}")
        assert spec is not None, f"缺少事件模块：astra_event.events.{module}"
    assert (
        importlib.util.find_spec("astra_event.events.mcp") is None
    ), "不应新建 events/mcp.py（Erratum-B）"
    # MCPCall* 仍在 ``agent.py``。
    agent_spec = importlib.util.find_spec("astra_event.events.agent")
    assert agent_spec is not None


def test_new_events_subclass_domain_event_only() -> None:
    """全部新增事件**继承** ``DomainEvent``（事件基类唯一，C-02）。"""
    for name, cls in _all_new_events().items():
        assert issubclass(cls, DomainEvent), f"{name} 未继承 DomainEvent"
        # 仅一个 DomainEvent 祖先（除自身）。
        domain_bases = [b for b in cls.__mro__ if b is DomainEvent]
        assert len(domain_bases) == 1, f"{name} 的 DomainEvent 基类不唯一"


def test_new_event_types_match_spec_and_prefix() -> None:
    """``type`` 与设计 §2.11 逐字一致，且前缀与模块族匹配。"""
    for module, events in NEW_EVENT_MODULES.items():
        for name, expected_type in events.items():
            cls = _all_new_events()[name]
            assert cls.type == expected_type, f"{name}.type 应为 {expected_type}"
            assert cls.type.startswith(f"{module}."), f"{name}.type 前缀应为 {module}."
    # type 全局唯一。
    types = [cls.type for cls in _all_new_events().values()]
    assert len(types) == len(set(types)), "事件 type 必须唯一"


def test_new_events_exported_from_both_roots() -> None:
    """新增事件从 ``astra_event.events`` 与 ``astra_event`` 均导出。"""
    import astra_event
    import astra_event.events as events_pkg

    for name in _all_new_events():
        assert hasattr(astra_event, name), f"astra_event 未导出 {name}"
        assert name in astra_event.__all__, f"astra_event.__all__ 缺 {name}"
        assert hasattr(events_pkg, name), f"astra_event.events 未导出 {name}"
        assert name in events_pkg.__all__, f"astra_event.events.__all__ 缺 {name}"


def test_eventbus_interface_unchanged_and_publishes_new_events() -> None:
    """``EventBus`` 接口不变；新事件经 ``LocalEventBus`` **发布且被消费**（C-02）。"""
    from astra_event import LocalEventBus

    for method in ("publish", "subscribe", "unsubscribe"):
        assert hasattr(LocalEventBus, method), f"EventBus 缺失 {method}（接口被改）"

    received: list[str] = []
    bus = LocalEventBus()
    for cls in _all_new_events().values():
        bus.subscribe(cls.type, lambda event, _sink=received: _sink.append(event.type))

    # 逐类构造 → 发布 → 断言被消费。
    instances = [
        _all_new_events()["SkillResolved"].create(skill_name="s", skill_id="sk-1"),
        _all_new_events()["WorkflowStarted"].create(workflow_id="wf-1", run_id="r-1"),
        _all_new_events()["WorkflowNodeStarted"].create(
            workflow_id="wf-1", run_id="r-1", node_id="n-1"
        ),
        _all_new_events()["WorkflowNodeCompleted"].create(
            workflow_id="wf-1", run_id="r-1", node_id="n-1", status="ok"
        ),
        _all_new_events()["WorkflowCompleted"].create(workflow_id="wf-1", run_id="r-1"),
        _all_new_events()["WorkflowFailed"].create(
            workflow_id="wf-1", run_id="r-1", error_type="boom"
        ),
        _all_new_events()["KnowledgeIndexed"].create(kb_id="kb-1", document_id="d-1"),
        _all_new_events()["MemoryWritten"].create(memory_id="m-1", scope="user"),
        _all_new_events()["ApprovalRequested"].create(
            approval_id="ap-1", subject_type="tool", subject_ref="t-1"
        ),
        _all_new_events()["ApprovalDecided"].create(approval_id="ap-1", status="APPROVED"),
    ]
    for instance in instances:
        bus.publish(instance)

    assert sorted(received) == sorted(NEW_SSE_MAP.keys()), received


def test_sse_channel_mapping_extended_not_broken() -> None:
    """SSE 通道映射**仅追加**：既有 9 类不变 + 新增 10 类生效。"""
    from astra_api.sse.encoder import SSE_CHANNEL_BY_DOMAIN_TYPE

    for domain_type, channel in EXISTING_SSE_MAP.items():
        assert (
            SSE_CHANNEL_BY_DOMAIN_TYPE.get(domain_type) == channel
        ), f"既有通道契约被破坏：{domain_type}"
    for domain_type, channel in NEW_SSE_MAP.items():
        assert (
            SSE_CHANNEL_BY_DOMAIN_TYPE.get(domain_type) == channel
        ), f"新增通道缺失：{domain_type}"


@pytest.mark.parametrize("name", sorted(_all_new_events()))
def test_create_builds_serializable_payload(name: str) -> None:
    """``create`` 产出的载荷可序列化（JSON），且 ``to_dict`` 含 ``type`` / ``payload``。"""
    import json

    builder = _all_new_events()[name]
    # 用最小必填参数构造（依据模块签名）。
    minimal_args: dict[str, dict[str, object]] = {
        "SkillResolved": {"skill_name": "s"},
        "WorkflowStarted": {"workflow_id": "wf", "run_id": "r"},
        "WorkflowNodeStarted": {"workflow_id": "wf", "run_id": "r", "node_id": "n"},
        "WorkflowNodeCompleted": {
            "workflow_id": "wf",
            "run_id": "r",
            "node_id": "n",
            "status": "ok",
        },
        "WorkflowCompleted": {"workflow_id": "wf", "run_id": "r"},
        "WorkflowFailed": {"workflow_id": "wf", "run_id": "r", "error_type": "e"},
        "KnowledgeIndexed": {"kb_id": "kb", "document_id": "d"},
        "MemoryWritten": {"memory_id": "m", "scope": "user"},
        "ApprovalRequested": {
            "approval_id": "ap",
            "subject_type": "tool",
            "subject_ref": "t",
        },
        "ApprovalDecided": {"approval_id": "ap", "status": "APPROVED"},
    }
    event = builder.create(**minimal_args[name])
    as_dict = event.to_dict()
    assert as_dict["type"] == builder.type
    json.dumps(as_dict["payload"], ensure_ascii=False)
