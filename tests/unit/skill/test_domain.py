"""Skill 域实体单测（W2 / T2-07）。

覆盖：

- ``SkillVersion`` **不可变**（``frozen``）：已 ``PUBLISHED`` 后改 ``instructions`` /
  ``manifest`` → ``DomainError(CONFLICT, published_immutable)``；
- 状态机单向：``DRAFT → PUBLISHED → DEPRECATED``（非法迁移 → ``CONFLICT``）；
- ``DRAFT`` 允许改 ``instructions``（产生新实例，不改原实例）；
- ``AgentSkill`` 唯一键语义（``(agent_version_id, skill_id)``，同构 ``agent_tool``）。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_database.models.skill import AgentSkill as OrmAgentSkill
from astra_domain import AgentSkill
from astra_skill import (
    SKILL_VERSION_STATUS_DEPRECATED,
    SKILL_VERSION_STATUS_DRAFT,
    SKILL_VERSION_STATUS_PUBLISHED,
    SkillVersion,
)
from sqlalchemy import UniqueConstraint


def _version(status: str = SKILL_VERSION_STATUS_DRAFT) -> SkillVersion:
    """构造一个测试用 SkillVersion。"""
    return SkillVersion(
        skill_id="skill-1",
        version="1.0.0",
        instructions="原始指令",
        manifest={"name": "demo"},
        status=status,
        created_by="user-1",
    )


def test_skill_version_is_frozen() -> None:
    """``SkillVersion`` 为 ``frozen`` dataclass：字段不可原地赋值。"""
    version = _version()
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError
        version.instructions = "篡改"  # type: ignore[misc]


def test_draft_allows_instruction_change_via_new_instance() -> None:
    """``DRAFT`` 允许改 ``instructions``，返回新实例，原实例不变。"""
    original = _version(SKILL_VERSION_STATUS_DRAFT)
    changed = original.with_instructions("新指令")
    assert changed.instructions == "新指令"
    assert original.instructions == "原始指令"
    assert changed is not original


def test_published_instruction_change_is_rejected() -> None:
    """已 ``PUBLISHED`` 改 ``instructions`` → ``CONFLICT``（``published_immutable``）。"""
    published = _version(SKILL_VERSION_STATUS_PUBLISHED)
    with pytest.raises(DomainError) as excinfo:
        published.with_instructions("发布后篡改")
    assert excinfo.value.code is ErrorCode.CONFLICT
    assert excinfo.value.data.get("reason") == "published_immutable"


def test_published_manifest_change_is_rejected() -> None:
    """已 ``PUBLISHED`` 改 ``manifest`` → ``CONFLICT``（``published_immutable``）。"""
    published = _version(SKILL_VERSION_STATUS_PUBLISHED)
    with pytest.raises(DomainError) as excinfo:
        published.with_manifest({"name": "changed"})
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_status_transitions_are_one_way() -> None:
    """``DRAFT → PUBLISHED → DEPRECATED`` 合法；逆向 / 同态迁移非法。"""
    draft = _version(SKILL_VERSION_STATUS_DRAFT)
    published = draft.publish()
    assert published.status == SKILL_VERSION_STATUS_PUBLISHED
    deprecated = published.deprecate()
    assert deprecated.status == SKILL_VERSION_STATUS_DEPRECATED

    with pytest.raises(DomainError):
        deprecated.publish()  # DEPRECATED → PUBLISHED 非法
    with pytest.raises(DomainError):
        draft.with_status(SKILL_VERSION_STATUS_DRAFT)  # DRAFT → DRAFT 非法


def test_agent_skill_defaults() -> None:
    """``AgentSkill`` 域实体默认值（``enabled=True`` / ``config={}``）。"""
    binding = AgentSkill(agent_version_id="av-1", skill_id="skill-1")
    assert binding.enabled is True
    assert binding.config == {}


def test_agent_skill_unique_key_is_declared() -> None:
    """``agent_skill`` ORM 唯一键为 ``(agent_version_id, skill_id)``（同构 ``agent_tool``）。"""
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in OrmAgentSkill.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("agent_version_id", "skill_id") in unique_columns
