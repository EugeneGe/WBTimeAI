"""AgentVersion 不可变 + 发布语义单测（T1-22 / ``I-P1-05``）。

一次发布 = 一个新版本；旧版本字段哈希不变（不可变）；显式加载明确版本。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from astra_agent import build_agent_services

from tests.unit.runtime_stubs import build_session_factory


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


def _agent(service):  # noqa: ANN001
    return service.create_agent(tenant_id="t1", name="A", created_by="u1")


def test_publish_new_version_switches_current(tmp_path: Path) -> None:
    factory, engine = build_session_factory(tmp_path / "agent.db")
    try:
        services = build_agent_services(factory)
        service = services.agent_service
        agent = _agent(service)

        v1 = service.publish_version(
            agent_id=agent.id,
            system_prompt="PROMPT-A",
            model_config={"provider": "stub", "model": "m1"},
            runtime_config={"max_iterations": 3},
            created_by="u1",
        )
        h1 = _hash(v1)
        reloaded_agent = service.get_agent(agent.id)
        assert reloaded_agent.current_version_id == v1.id
        assert v1.version == "v1"

        v2 = service.publish_version(
            agent_id=agent.id,
            system_prompt="PROMPT-B",
            model_config={"provider": "stub", "model": "m1"},
            runtime_config={"max_iterations": 4},
            created_by="u1",
        )
        assert v2.id != v1.id
        assert v2.version == "v2"
        agent_after = service.get_agent(agent.id)
        assert agent_after.current_version_id == v2.id

        # 旧版本不可变：字段哈希不变。
        v1_reloaded = service.load_version(agent_after, v1.id)
        assert _hash(v1_reloaded) == h1
        # 缺省加载当前版本。
        assert service.load_version(agent_after).id == v2.id
        assert service.load_version(agent_after).system_prompt == "PROMPT-B"
    finally:
        engine.dispose()


def test_version_repository_update_is_identity(tmp_path: Path) -> None:
    """``update`` 对已存在版本**不改字段**（不可变）。"""
    factory, engine = build_session_factory(tmp_path / "agent2.db")
    try:
        services = build_agent_services(factory)
        service = services.agent_service
        agent = _agent(service)
        v1 = service.publish_version(
            agent_id=agent.id,
            system_prompt="P1",
            model_config={"provider": "stub", "model": "m1"},
            runtime_config={},
            created_by="u1",
        )
        v1.system_prompt = "TAMPERED"
        services.versions.update(v1)
        assert services.versions.get(v1.id).system_prompt == "P1"
    finally:
        engine.dispose()


def test_validate_current_version_consistency(tmp_path: Path) -> None:
    factory, engine = build_session_factory(tmp_path / "agent3.db")
    try:
        services = build_agent_services(factory)
        service = services.agent_service
        agent = _agent(service)
        v1 = service.publish_version(
            agent_id=agent.id,
            system_prompt="P1",
            model_config={"provider": "stub", "model": "m1"},
            runtime_config={},
            created_by="u1",
        )
        agent_after = service.get_agent(agent.id)
        # 一致：不抛错。
        service.validate_current_version(agent_after, v1)
    finally:
        engine.dispose()
