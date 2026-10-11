"""``SqlSandboxSessionRepository`` 专门单测（W7 / 台账 C6）。

覆盖：``add`` 回读（域↔ORM 映射正确）、``get`` 命中/未命中、``list(**filters)``
等值过滤、``update`` 命中/未命中分支、``delete``、``list_by_run`` 按 ``created_at``
升序且仅含目标 Run。

沿用仓库既有 ``Sql*Repository`` 测试约定（``session_factory`` fixture，内存 SQLite）。
"""

from __future__ import annotations

import time

from astra_database import SqlSandboxSessionRepository
from astra_domain import (
    SANDBOX_PROVIDER_LOCAL_PROCESS,
    SANDBOX_SESSION_STATUS_RUNNING,
    SANDBOX_SESSION_STATUS_STOPPED,
    SandboxSession,
)


def _session(
    *,
    run_id: str | None = "run-1",
    workspace_id: str | None = "ws-1",
    provider: str = SANDBOX_PROVIDER_LOCAL_PROCESS,
    image: str | None = "alpine:3.20",
    status: str = SANDBOX_SESSION_STATUS_RUNNING,
    container_ref: str | None = "ctr-1",
    workdir: str = "/workspace",
    tenant_id: str = "tenant-1",
) -> SandboxSession:
    """构造一个最小 ``SandboxSession``。"""
    return SandboxSession(
        tenant_id=tenant_id,
        run_id=run_id,
        workspace_id=workspace_id,
        provider=provider,
        image=image,
        status=status,
        container_ref=container_ref,
        workdir=workdir,
    )


def test_add_and_get_round_trip(session_factory) -> None:  # noqa: ANN001
    """``add`` 回读：域→ORM→域 映射字段一致。"""
    repo = SqlSandboxSessionRepository(session_factory)
    entity = _session()
    added = repo.add(entity)

    fetched = repo.get(added.id)
    assert fetched is not None
    assert fetched.id == added.id
    assert fetched.run_id == "run-1"
    assert fetched.workspace_id == "ws-1"
    assert fetched.provider == SANDBOX_PROVIDER_LOCAL_PROCESS
    assert fetched.image == "alpine:3.20"
    assert fetched.status == SANDBOX_SESSION_STATUS_RUNNING
    assert fetched.container_ref == "ctr-1"
    assert fetched.workdir == "/workspace"
    assert fetched.tenant_id == "tenant-1"
    assert fetched.created_at is not None
    assert fetched.ended_at is None


def test_get_missing_returns_none(session_factory) -> None:  # noqa: ANN001
    """``get`` 未命中返回 ``None``。"""
    repo = SqlSandboxSessionRepository(session_factory)
    assert repo.get("does-not-exist") is None


def test_list_equality_filters(session_factory) -> None:  # noqa: ANN001
    """``list(**filters)`` 按字段等值过滤。"""
    repo = SqlSandboxSessionRepository(session_factory)
    repo.add(_session(run_id="run-A", status=SANDBOX_SESSION_STATUS_RUNNING))
    repo.add(_session(run_id="run-B", status=SANDBOX_SESSION_STATUS_STOPPED))
    repo.add(_session(run_id="run-A", status=SANDBOX_SESSION_STATUS_STOPPED))

    assert len(repo.list()) == 3
    assert {s.run_id for s in repo.list(run_id="run-A")} == {"run-A"}
    assert len(repo.list(run_id="run-A")) == 2
    assert {s.run_id for s in repo.list(status=SANDBOX_SESSION_STATUS_STOPPED)} == {
        "run-A",
        "run-B",
    }
    assert repo.list(run_id="run-A", status=SANDBOX_SESSION_STATUS_RUNNING)[0].run_id == "run-A"
    assert repo.list(run_id="nope") == []


def test_update_hit(session_factory) -> None:  # noqa: ANN001
    """``update`` 命中：字段更新并落库。"""
    repo = SqlSandboxSessionRepository(session_factory)
    added = repo.add(_session())
    added.status = SANDBOX_SESSION_STATUS_STOPPED
    added.container_ref = None
    added.workdir = "/srv"

    updated = repo.update(added)
    assert updated.status == SANDBOX_SESSION_STATUS_STOPPED

    reloaded = repo.get(added.id)
    assert reloaded is not None
    assert reloaded.status == SANDBOX_SESSION_STATUS_STOPPED
    assert reloaded.container_ref is None
    assert reloaded.workdir == "/srv"


def test_update_miss_does_not_create_row(session_factory) -> None:  # noqa: ANN001
    """``update`` 未命中：返回映射实体但**不**建行。"""
    repo = SqlSandboxSessionRepository(session_factory)
    ghost = _session(run_id="run-ghost")
    returned = repo.update(ghost)

    assert returned.id == ghost.id
    assert repo.get(ghost.id) is None
    assert repo.list(run_id="run-ghost") == []


def test_delete(session_factory) -> None:  # noqa: ANN001
    """``delete`` 删除后 ``get`` 返回 ``None``。"""
    repo = SqlSandboxSessionRepository(session_factory)
    added = repo.add(_session())
    repo.delete(added)
    assert repo.get(added.id) is None


def test_list_by_run_ascending_and_scoped(session_factory) -> None:  # noqa: ANN001
    """``list_by_run`` 仅含目标 Run，且按 ``created_at`` 升序。"""
    repo = SqlSandboxSessionRepository(session_factory)
    first = repo.add(_session(run_id="run-1"))
    time.sleep(0.002)
    second = repo.add(_session(run_id="run-1"))
    time.sleep(0.002)
    third = repo.add(_session(run_id="run-1"))
    # 另一 Run 的会话不得混入。
    repo.add(_session(run_id="run-2"))

    listed = repo.list_by_run("run-1")
    assert [s.id for s in listed] == [first.id, second.id, third.id]
    created = [s.created_at for s in listed]
    assert created == sorted(created)

    assert len(repo.list_by_run("run-2")) == 1
    assert repo.list_by_run("run-missing") == []
