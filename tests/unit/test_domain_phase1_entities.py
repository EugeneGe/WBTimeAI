"""Phase 1 新实体默认值单测（决策 D2 / C-04：ID 来自 ``generate_id``，时间戳 UTC）。"""

from __future__ import annotations

from datetime import UTC

from astra_domain import (
    Agent,
    AgentEvent,
    AgentRun,
    AgentTool,
    AgentVersion,
    AuditLog,
    Conversation,
    Message,
    Model,
    ModelProvider,
    SandboxSession,
    Tool,
    ToolCall,
    ToolPermission,
    ToolVersion,
)

_PHASE1_ENTITIES = [
    Agent,
    AgentVersion,
    AgentTool,
    ModelProvider,
    Model,
    Tool,
    ToolVersion,
    ToolPermission,
    Conversation,
    Message,
    AgentRun,
    ToolCall,
    AgentEvent,
    SandboxSession,
    AuditLog,
]


def _is_uuid_v7(value: str) -> bool:
    """形如 xxxxxxxx-xxxx-7xxx-xxxx-xxxxxxxxxxxx（第 3 组以 7 开头）。"""
    parts = value.split("-")
    return len(parts) == 5 and parts[2][0] == "7"


def test_phase1_entities_have_uuidv7_ids() -> None:
    for entity_cls in _PHASE1_ENTITIES:
        instance = entity_cls()
        assert _is_uuid_v7(instance.id), f"{entity_cls.__name__}.id 非 UUIDv7"
        assert instance.id != entity_cls().id


def test_phase1_entities_have_utc_timestamps() -> None:
    for entity_cls in _PHASE1_ENTITIES:
        instance = entity_cls()
        assert instance.created_at.tzinfo is not None
        assert instance.updated_at.tzinfo is not None
        assert instance.created_at.utcoffset() == UTC.utcoffset(None)


def test_phase1_entities_default_tenant_scope_is_none() -> None:
    for entity_cls in _PHASE1_ENTITIES:
        assert entity_cls().tenant_id is None


def test_agent_defaults() -> None:
    agent = Agent(tenant_id="t-1", name="coder")
    assert agent.type == "PRIMARY"
    assert agent.status == "DRAFT"
    assert agent.current_version_id is None
    assert agent.workspace_id is None


def test_agent_tool_defaults_enabled() -> None:
    binding = AgentTool(tenant_id="t-1", agent_version_id="v-1", tool_id="tool-1")
    assert binding.enabled is True
    assert binding.permission_scope == {}


def test_agent_run_defaults_are_non_terminal() -> None:
    run = AgentRun(tenant_id="t-1", agent_id="a-1", conversation_id="c-1")
    assert run.status == "PENDING"
    assert run.run_mode == "INLINE"
    assert run.trigger == "user"
    assert run.success is None
    assert run.tool_error_count == 0
    assert run.cost is None
    assert run.cost_status == "UNPRICED"


def test_tool_call_defaults() -> None:
    call = ToolCall(run_id="r-1", tool_name="filesystem")
    assert call.tool_type == "builtin"
    assert call.attempt == 1
    assert call.status == "PENDING"


def test_message_and_event_defaults() -> None:
    message = Message(conversation_id="c-1", role="user", content="hi")
    assert message.content_parts == []
    event = AgentEvent(run_id="r-1", seq=1, type="agent.started")
    assert event.payload == {}


def test_audit_log_defaults() -> None:
    record = AuditLog(tenant_id="t-1", action="login", request_id="req-1")
    assert record.outcome == "SUCCESS"
    assert record.metadata == {}
    assert record.extensions == {}
