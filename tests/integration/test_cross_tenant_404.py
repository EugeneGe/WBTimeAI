"""跨租户越权 → ``NOT_FOUND``（隔离不变量 I-1 / ``N-P1-05``）。

总纲 §4.1 / §11.2：**越权（跨租户）返回 404 而非 403**——不泄露资源是否存在。
领域层以 ``ErrorCode.NOT_FOUND`` 承载（API 层映射为 HTTP 404）。
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
from astra_domain import Tool
from astra_tool import build_tool_services
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

TENANT_A = "tenant-aaaa"
TENANT_B = "tenant-bbbb"


@pytest.fixture()
def tool_session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表

    engine = create_engine(f"sqlite:///{(tmp_path / 'xtenant.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def _granted(factory: sessionmaker[Session]):
    tools = SqlToolRepository(factory)
    service = build_tool_services(
        tool_repository=tools,
        tool_permission_repository=SqlToolPermissionRepository(factory),
    )
    tool = tools.add(
        Tool(tenant_id=None, name="git", display_name="Git", category="vcs", status="ACTIVE")
    )
    permission = service.grant(
        tenant_id=TENANT_A, tool_id=tool.id, action="EXECUTE", effect="ALLOW", agent_id="agent-1"
    )
    return service, permission


def test_cross_tenant_get_permission_returns_not_found(
    tool_session_factory: sessionmaker[Session],
) -> None:
    service, permission = _granted(tool_session_factory)

    # 同租户可见。
    assert service.get_permission(permission.id, tenant_id=TENANT_A).id == permission.id

    # 跨租户 → NOT_FOUND（映射 HTTP 404），**非** PERMISSION_DENIED（403）。
    with pytest.raises(DomainError) as excinfo:
        service.get_permission(permission.id, tenant_id=TENANT_B)
    assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_cross_tenant_revoke_returns_not_found(
    tool_session_factory: sessionmaker[Session],
) -> None:
    service, permission = _granted(tool_session_factory)
    with pytest.raises(DomainError) as excinfo:
        service.revoke(permission.id, tenant_id=TENANT_B)
    assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_tenant_scoped_tool_lookup_hides_other_tenant(
    tool_session_factory: sessionmaker[Session],
) -> None:
    tools = SqlToolRepository(tool_session_factory)
    tools.add(
        Tool(
            tenant_id=TENANT_A,
            name="private-tool",
            display_name="Private",
            category="custom",
            status="ACTIVE",
        )
    )
    # 跨租户按名不可见 → None（上层映射 404）。
    assert tools.get_by_name("private-tool", tenant_id=TENANT_B) is None
