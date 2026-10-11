"""Tool 权限集成测试（T1-17 / ``I-P1-10``）。

构造 ``astra_database`` 的 SQL 仓储 → **注入** ``PermissionService`` / ``PermissionChecker``；
覆盖：仓储满足领域 Protocol、ALLOW / DENY、``effect=APPROVAL`` 拒绝、工具版本往返。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from astra_core import DomainError, ErrorCode
from astra_database import (
    Base,
    SqlToolPermissionRepository,
    SqlToolRepository,
    create_session_factory,
)
from astra_domain import (
    Tool,
    ToolEffect,
    ToolPermissionRepository,
    ToolRepository,
    ToolVersion,
    ToolVersionRepository,
)
from astra_tool import GitTool, ShellTool, ToolContext, build_tool_services
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

TENANT_A = "tenant-aaaa"
AGENT_1 = "agent-0001"


@pytest.fixture()
def tool_session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    engine = create_engine(f"sqlite:///{(tmp_path / 'tool.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _service(factory: sessionmaker[Session]) -> tuple[SqlToolRepository, object]:
    tools = SqlToolRepository(factory)
    service = build_tool_services(
        tool_repository=tools,
        tool_permission_repository=SqlToolPermissionRepository(factory),
    )
    return tools, service


def test_repositories_satisfy_domain_protocols(
    tool_session_factory: sessionmaker[Session],
) -> None:
    assert isinstance(SqlToolRepository(tool_session_factory), ToolRepository)
    assert isinstance(SqlToolRepository(tool_session_factory), ToolVersionRepository)
    assert isinstance(SqlToolPermissionRepository(tool_session_factory), ToolPermissionRepository)


def test_allow_and_default_deny(tool_session_factory: sessionmaker[Session]) -> None:
    tools, service = _service(tool_session_factory)
    tool = tools.add(
        Tool(tenant_id=None, name="git", display_name="Git", category="vcs", status="ACTIVE")
    )
    service.grant(  # type: ignore[attr-defined]
        tenant_id=TENANT_A, tool_id=tool.id, action="EXECUTE", effect="ALLOW", agent_id=AGENT_1
    )
    ctx = ToolContext(tenant_id=TENANT_A, agent_id=AGENT_1)
    checker = service.build_checker(agent_id=AGENT_1)  # type: ignore[attr-defined]

    assert checker.check(ctx, GitTool(), "EXECUTE") is ToolEffect.ALLOW
    assert checker.check(ctx, ShellTool(), "EXECUTE") is ToolEffect.DENY


def test_explicit_deny(tool_session_factory: sessionmaker[Session]) -> None:
    tools, service = _service(tool_session_factory)
    tool = tools.add(
        Tool(tenant_id=None, name="shell", display_name="Shell", category="system", status="ACTIVE")
    )
    service.grant(  # type: ignore[attr-defined]
        tenant_id=TENANT_A, tool_id=tool.id, action="EXECUTE", effect="DENY", agent_id=AGENT_1
    )
    checker = service.build_checker(agent_id=AGENT_1)  # type: ignore[attr-defined]
    assert checker.check(ToolContext(agent_id=AGENT_1), ShellTool(), "EXECUTE") is ToolEffect.DENY


def test_approval_effect_rejected(tool_session_factory: sessionmaker[Session]) -> None:
    tools, service = _service(tool_session_factory)
    tool = tools.add(
        Tool(tenant_id=None, name="git", display_name="Git", category="vcs", status="ACTIVE")
    )
    with pytest.raises(DomainError) as excinfo:
        service.grant(  # type: ignore[attr-defined]
            tenant_id=TENANT_A,
            tool_id=tool.id,
            action="EXECUTE",
            effect="APPROVAL",
            agent_id=AGENT_1,
        )
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_tool_lookup_and_version_roundtrip(tool_session_factory: sessionmaker[Session]) -> None:
    tools, _service_obj = _service(tool_session_factory)
    tool = tools.add(
        Tool(
            tenant_id=None,
            name="filesystem",
            display_name="Filesystem",
            category="system",
            status="ACTIVE",
            requires_sandbox=False,
        )
    )
    assert tools.get_by_name("filesystem") is not None
    assert [item.name for item in tools.list_builtin()] == ["filesystem"]

    tools.add(ToolVersion(tool_id=tool.id, version="1.0.0", spec={"k": "v"}))
    versions = tools.list_by_tool(tool.id)
    assert [version.version for version in versions] == ["1.0.0"]
