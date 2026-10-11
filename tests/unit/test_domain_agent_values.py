"""Agent 组值对象单测（设计 §2.4 / §2.7.1 / §2.7.2）。"""

from __future__ import annotations

import pytest
from astra_core import ValidationError
from astra_domain import (
    AgentStatus,
    AgentType,
    AgentVersionStatus,
    ConcurrencyConfig,
    ContextConfig,
    ExecutionPolicy,
    ModelConfig,
    RuntimeConfig,
)


def test_agent_type_values_and_ensure() -> None:
    assert set(AgentType.values()) == {
        "PRIMARY",
        "SUB_AGENT",
        "WORKFLOW_AGENT",
        "SCHEDULED_AGENT",
        "EVENT_AGENT",
    }
    assert AgentType.ensure("PRIMARY") is AgentType.PRIMARY
    with pytest.raises(ValidationError):
        AgentType.ensure("NOPE")


def test_agent_status_and_version_status_values() -> None:
    assert set(AgentStatus.values()) == {"DRAFT", "ACTIVE", "ARCHIVED"}
    assert set(AgentVersionStatus.values()) == {"DRAFT", "PUBLISHED", "DEPRECATED"}
    assert AgentStatus.ensure(AgentStatus.ACTIVE) is AgentStatus.ACTIVE
    with pytest.raises(ValidationError):
        AgentVersionStatus.ensure("BAD")


def test_model_config_requires_provider_and_model() -> None:
    with pytest.raises(ValidationError):
        ModelConfig(provider="", model="gpt-4o")
    with pytest.raises(ValidationError):
        ModelConfig(provider="openai", model="")
    with pytest.raises(ValidationError):
        ModelConfig(provider="openai", model="gpt-4o", temperature=3.0)


def test_model_config_roundtrip() -> None:
    config = ModelConfig(provider="openai", model="gpt-4o", temperature=0.2, max_tokens=512)
    data = config.to_dict()
    assert data["provider"] == "openai"
    assert ModelConfig.from_dict(data).model == "gpt-4o"


def test_runtime_config_contains_all_segments() -> None:
    config = RuntimeConfig()
    data = config.to_dict()
    # 设计 §2.7.1 / §2.7.2：必须含 context / execution / concurrency 段。
    assert set(data) >= {
        "max_iterations",
        "tool_choice",
        "allow_stream",
        "sandbox",
        "context",
        "execution",
        "concurrency",
    }
    assert isinstance(config.context, ContextConfig)
    assert isinstance(config.execution, ExecutionPolicy)
    assert isinstance(config.concurrency, ConcurrencyConfig)
    assert data["context"]["overflow_strategy"] == "TRUNCATE_OLDEST"


def test_runtime_config_roundtrip() -> None:
    config = RuntimeConfig(max_iterations=5, tool_choice="auto", allow_stream=False)
    restored = RuntimeConfig.from_dict(config.to_dict())
    assert restored.max_iterations == 5
    assert restored.allow_stream is False
    assert restored.execution.max_retry == config.execution.max_retry


def test_runtime_config_rejects_non_positive_iterations() -> None:
    with pytest.raises(ValidationError):
        RuntimeConfig(max_iterations=0)
