"""数据保留与清理 NFR（W9 / T2-48；设计 §2.19 / 裁定 §6 · R8 / R9 / R10 / R14）。

验收锚点 ``I-P2-33`` / ``N-P2-06``：``retention_policy`` 参数化 + **fake clock 快进**
（monkeypatch ``astra_common.utcnow``）断言：

① 到期数据被清理；② **未终态 ``agent_run`` 关联的 ``agent_event`` 保留（不误删）**；
③ 删除级联正确；④ ``retention.protected`` 跳过保护项；⑤ SQLite ``VACUUM`` 调度已配置
（PG no-op 分支）；⑥ 处理器接线 + ``astra data backup/restore`` 可用且**不改**核心命令。

🔴 **禁** ``sleep``：时间推进一律经 monkeypatch ``astra_common.utcnow``（fake clock）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode, NotImplementedYetError, generate_id
from astra_database.maintenance.cleanup import CleanupReport, RetentionCleaner
from astra_database.maintenance.vacuum import (
    DEFAULT_VACUUM_INTERVAL_DAYS,
    VacuumScheduler,
    vacuum_database,
    vacuum_into,
    weekly_vacuum_schedule,
)
from astra_database.models.audit import AuditLog
from astra_database.models.conversation import AgentEvent, AgentRun, Message, ToolCall
from astra_task.maintenance.cleanup import (
    AUDIT_LOG_TABLE,
    MESSAGE_TABLE,
    RETENTION_TASK_TYPE,
    TOOL_CALL_TABLE,
    RetentionPolicy,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

#: fake clock 基准时刻（UTC）。
NOW = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

#: 「已过期」时间戳（200 天前；> 180 天最长窗口）。
OLD = NOW - timedelta(days=200)

#: 「未过期」时间戳（1 天前；< 90 天最短窗口）。
FRESH = NOW - timedelta(days=1)


# -- 极简父图种子（FK 完整，供 SQLite 用例） ---------------------------------


def _seed_scope(factory: sessionmaker[Session]) -> dict[str, str]:
    """建最小父图（tenant/user/workspace/agent/agent_version/conversation）。"""
    from astra_database.models.agent import Agent as OrmAgent
    from astra_database.models.agent import AgentVersion as OrmAgentVersion
    from astra_database.models.conversation import Conversation as OrmConversation
    from astra_database.models.identity import Tenant as OrmTenant
    from astra_database.models.identity import User as OrmUser
    from astra_database.models.workspace import Workspace as OrmWorkspace

    ids = {
        "tenant_id": generate_id(),
        "user_id": generate_id(),
        "workspace_id": generate_id(),
        "agent_id": generate_id(),
        "version_id": generate_id(),
        "conversation_id": generate_id(),
    }
    with factory() as session:
        session.add(
            OrmTenant(id=ids["tenant_id"], slug=f"ret-{ids['tenant_id'][:8]}", name="Retention")
        )
        session.add(
            OrmUser(
                id=ids["user_id"],
                tenant_id=ids["tenant_id"],
                username=f"ret-{ids['user_id'][:8]}",
                email=f"{ids['user_id'][:8]}@example.com",
                password_hash="x",
            )
        )
        session.add(
            OrmWorkspace(
                id=ids["workspace_id"],
                tenant_id=ids["tenant_id"],
                owner_id=ids["user_id"],
                name="Retention WS",
                workspace_type="personal",
            )
        )
        session.add(
            OrmAgent(
                id=ids["agent_id"],
                tenant_id=ids["tenant_id"],
                workspace_id=ids["workspace_id"],
                name="Retention Agent",
                type="PRIMARY",
                status="ACTIVE",
                created_by=ids["user_id"],
            )
        )
        session.add(
            OrmAgentVersion(
                id=ids["version_id"],
                agent_id=ids["agent_id"],
                version="1",
                system_prompt="x",
                model_config={"provider": "ret", "model": "ret-1"},
                runtime_config={},
                status="PUBLISHED",
                created_by=ids["user_id"],
            )
        )
        session.add(
            OrmConversation(
                id=ids["conversation_id"],
                tenant_id=ids["tenant_id"],
                workspace_id=ids["workspace_id"],
                agent_id=ids["agent_id"],
                user_id=ids["user_id"],
                title="retention",
                status="ACTIVE",
            )
        )
        session.commit()
    return ids


def _add_run(
    factory: sessionmaker[Session],
    scope: dict[str, str],
    *,
    status: str,
    started_at: datetime,
) -> str:
    """建一条 ``agent_run``（终态 / 非终态由 ``status`` 指定）。"""
    from astra_domain import COST_STATUS_UNPRICED, RUN_MODE_INLINE, RUN_TRIGGER_USER

    run_id = generate_id()
    with factory() as session:
        session.add(
            AgentRun(
                id=run_id,
                tenant_id=scope["tenant_id"],
                agent_id=scope["agent_id"],
                agent_version_id=scope["version_id"],
                conversation_id=scope["conversation_id"],
                user_id=scope["user_id"],
                status=status,
                run_mode=RUN_MODE_INLINE,
                trigger=RUN_TRIGGER_USER,
                cost_status=COST_STATUS_UNPRICED,
                started_at=started_at,
            )
        )
        session.commit()
    return run_id


def _add_event(
    factory: sessionmaker[Session], *, run_id: str, seq: int, created_at: datetime
) -> str:
    event_id = generate_id()
    with factory() as session:
        session.add(
            AgentEvent(
                id=event_id,
                run_id=run_id,
                seq=seq,
                type="agent.thinking",
                payload={"n": seq},
                created_at=created_at,
            )
        )
        session.commit()
    return event_id


def _add_message(
    factory: sessionmaker[Session],
    *,
    conversation_id: str,
    created_at: datetime,
    run_id: str | None = None,
) -> str:
    message_id = generate_id()
    with factory() as session:
        session.add(
            Message(
                id=message_id,
                conversation_id=conversation_id,
                run_id=run_id,
                role="user",
                content="hi",
                created_at=created_at,
            )
        )
        session.commit()
    return message_id


def _add_tool_call(factory: sessionmaker[Session], *, run_id: str, created_at: datetime) -> str:
    tool_call_id = generate_id()
    with factory() as session:
        session.add(
            ToolCall(
                id=tool_call_id,
                run_id=run_id,
                tool_name="shell",
                tool_type="builtin",
                status="SUCCESS",
                created_at=created_at,
            )
        )
        session.commit()
    return tool_call_id


def _add_audit(
    factory: sessionmaker[Session],
    *,
    tenant_id: str,
    created_at: datetime,
    tool_call_id: str | None = None,
) -> str:
    audit_id = generate_id()
    with factory() as session:
        session.add(
            AuditLog(
                id=audit_id,
                tenant_id=tenant_id,
                action="agent.run",
                outcome="SUCCESS",
                request_id=generate_id(),
                tool_call_id=tool_call_id,
                created_at=created_at,
            )
        )
        session.commit()
    return audit_id


def _count(factory: sessionmaker[Session], model: Any) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _exists(factory: sessionmaker[Session], model: Any, row_id: str) -> bool:
    with factory() as session:
        return session.get(model, row_id) is not None


def _fake_clock(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """把 ``astra_common.utcnow`` 换成固定时刻（fake clock；可反复「快进」）。"""
    import astra_common

    monkeypatch.setattr(astra_common, "utcnow", lambda: moment)


# -- ① + ② fake clock 快进：到期清理、非终态 Run 的 event 保留 ----------------


def test_retention_cleanup_purges_expired_keeps_fresh_and_active_run(
    nfr_sqlite_factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fake clock 快进到 ``NOW``：到期数据被清、未到期保留、非终态 Run 的 event 保留。"""
    _fake_clock(monkeypatch, NOW)
    factory = nfr_sqlite_factory
    scope = _seed_scope(factory)
    run_terminal = _add_run(factory, scope, status="SUCCESS", started_at=OLD)
    run_active = _add_run(factory, scope, status="RUNNING", started_at=OLD)

    event_old = _add_event(factory, run_id=run_terminal, seq=1, created_at=OLD)
    event_active = _add_event(factory, run_id=run_active, seq=1, created_at=OLD)
    event_fresh = _add_event(factory, run_id=run_terminal, seq=2, created_at=FRESH)
    message_old = _add_message(factory, conversation_id=scope["conversation_id"], created_at=OLD)
    message_fresh = _add_message(
        factory, conversation_id=scope["conversation_id"], created_at=FRESH
    )
    tool_old = _add_tool_call(factory, run_id=run_terminal, created_at=OLD)
    tool_fresh = _add_tool_call(factory, run_id=run_terminal, created_at=FRESH)
    audit_old = _add_audit(factory, tenant_id=scope["tenant_id"], created_at=OLD)
    audit_fresh = _add_audit(factory, tenant_id=scope["tenant_id"], created_at=FRESH)

    cleaner = RetentionCleaner(factory, RetentionPolicy(), archive_dir=tmp_path / "archive")
    report = cleaner.run()

    assert isinstance(report, CleanupReport)
    assert report.total_deleted == 4  # event_old + message_old + tool_old + audit_old
    # ① 到期数据被清理。
    assert not _exists(factory, AgentEvent, event_old)
    assert not _exists(factory, Message, message_old)
    assert not _exists(factory, ToolCall, tool_old)
    assert not _exists(factory, AuditLog, audit_old)
    # 未到期保留。
    assert _exists(factory, AgentEvent, event_fresh)
    assert _exists(factory, Message, message_fresh)
    assert _exists(factory, ToolCall, tool_fresh)
    assert _exists(factory, AuditLog, audit_fresh)
    # ② 非终态 Run 关联的 event **不清理**（不误删）。
    assert _exists(factory, AgentEvent, event_active)
    # ③ 父行（agent_run）保留（级联不越界删父）。
    assert _exists(factory, AgentRun, run_terminal)
    assert _exists(factory, AgentRun, run_active)


def test_retention_cleanup_is_paused_noop(
    nfr_sqlite_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``retention.paused`` → 清理整体不动作（``paused`` 短路）。"""
    _fake_clock(monkeypatch, NOW)
    factory = nfr_sqlite_factory
    scope = _seed_scope(factory)
    run_terminal = _add_run(factory, scope, status="SUCCESS", started_at=OLD)
    message_old = _add_message(factory, conversation_id=scope["conversation_id"], created_at=OLD)

    policy = RetentionPolicy(paused=True)
    report = RetentionCleaner(factory, policy).run()
    assert report.paused is True
    assert report.total_deleted == 0
    assert _exists(factory, Message, message_old)
    assert _exists(factory, AgentRun, run_terminal)


# -- ④ retention.protected 跳过保护项 ----------------------------------------


def test_retention_protected_skips_table_and_id(
    nfr_sqlite_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``retention.protected`` 命中**行 ID** → 该行跳过；命中**表名** → 整表跳过。"""
    _fake_clock(monkeypatch, NOW)
    factory = nfr_sqlite_factory
    scope = _seed_scope(factory)
    run_terminal = _add_run(factory, scope, status="SUCCESS", started_at=OLD)

    message_protected = _add_message(
        factory, conversation_id=scope["conversation_id"], created_at=OLD
    )
    message_other = _add_message(factory, conversation_id=scope["conversation_id"], created_at=OLD)
    tool_old = _add_tool_call(factory, run_id=run_terminal, created_at=OLD)

    policy = RetentionPolicy(protected=frozenset({message_protected, TOOL_CALL_TABLE}))
    RetentionCleaner(factory, policy).run()

    # 行 ID 保护：message_protected 保留，其余 message 被清。
    assert _exists(factory, Message, message_protected)
    assert not _exists(factory, Message, message_other)
    # 表名保护：tool_call 整表跳过。
    assert _exists(factory, ToolCall, tool_old)


# -- ③ 删除级联正确（tool_call 删除时置空引用它的 audit_log.tool_call_id） ------


def test_retention_delete_cascade_nulls_audit_reference(
    nfr_sqlite_factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """删 ``tool_call`` 前先置空引用它的 ``audit_log.tool_call_id``（无悬挂外键）。"""
    _fake_clock(monkeypatch, NOW)
    factory = nfr_sqlite_factory
    scope = _seed_scope(factory)
    run_terminal = _add_run(factory, scope, status="SUCCESS", started_at=OLD)

    tool_old = _add_tool_call(factory, run_id=run_terminal, created_at=OLD)  # 过期 → 删
    # 审计较新（未过期，保留），但引用被删的 tool_call → 清理后应被置空。
    audit_fresh = _add_audit(
        factory, tenant_id=scope["tenant_id"], created_at=FRESH, tool_call_id=tool_old
    )

    RetentionCleaner(factory, RetentionPolicy(), archive_dir=tmp_path / "archive").run()

    assert not _exists(factory, ToolCall, tool_old)
    with factory() as session:
        audit = session.get(AuditLog, audit_fresh)
        assert audit is not None
        assert audit.tool_call_id is None  # 引用被置空，审计行保留


# -- 归档优先：audit_log 清理前先导出 JSONL -----------------------------------


def test_retention_archives_audit_log_before_delete(
    nfr_sqlite_factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配置归档目录 → ``audit_log`` 先归档（JSONL）再删；未配置 → 不删（归档优先）。"""
    _fake_clock(monkeypatch, NOW)
    factory = nfr_sqlite_factory
    scope = _seed_scope(factory)
    audit_old = _add_audit(factory, tenant_id=scope["tenant_id"], created_at=OLD)

    archive_dir = tmp_path / "archive"
    report = RetentionCleaner(factory, RetentionPolicy(), archive_dir=archive_dir).run()
    assert report.archived[AUDIT_LOG_TABLE] == 1
    assert not _exists(factory, AuditLog, audit_old)
    files = list(archive_dir.glob("audit_log-*.jsonl"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8").count("\n") == 1

    # 未配置归档目录 → audit_log **不清理**（避免无归档即删除）。
    audit_old2 = _add_audit(factory, tenant_id=scope["tenant_id"], created_at=OLD)
    RetentionCleaner(factory, RetentionPolicy(), archive_dir=None).run()
    assert _exists(factory, AuditLog, audit_old2)


# -- 分批提交（batch_size 生效） ---------------------------------------------


def test_retention_batch_size_splits_commits(
    nfr_sqlite_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``batch_size`` 生效：多批提交（``report.batches`` 反映批次数）。"""
    _fake_clock(monkeypatch, NOW)
    factory = nfr_sqlite_factory
    scope = _seed_scope(factory)
    run_terminal = _add_run(factory, scope, status="SUCCESS", started_at=OLD)
    for seq in range(5):
        _add_event(factory, run_id=run_terminal, seq=seq + 1, created_at=OLD)

    policy = RetentionPolicy(batch_size=2)
    report = RetentionCleaner(factory, policy).run()
    assert report.deleted["agent_event"] == 5
    # 5 行 / 每批 2 → 3 批（2+2+1）。
    assert report.batches == 3


# -- ⑤ SQLite VACUUM 调度已配置（PG no-op） -----------------------------------


def test_vacuum_schedule_is_weekly() -> None:
    """``VACUUM`` 默认每周一次；``is_due`` 依间隔判定。"""
    schedule = weekly_vacuum_schedule()
    assert isinstance(schedule, VacuumScheduler)
    assert schedule.interval_days == DEFAULT_VACUUM_INTERVAL_DAYS == 7
    assert schedule.is_due(NOW, None) is True
    assert schedule.is_due(NOW, NOW - timedelta(days=3)) is False
    assert schedule.is_due(NOW, NOW - timedelta(days=8)) is True
    assert schedule.next_due(NOW) == NOW + timedelta(days=7)


def test_vacuum_sqlite_executes_and_pg_is_noop(
    nfr_sqlite_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """SQLite 执行 ``VACUUM`` / ``VACUUM INTO``；PG（方言）→ no-op / 显式报错。"""
    engine = nfr_sqlite_factory().get_bind()
    assert vacuum_database(engine) is True  # SQLite 真实执行

    snapshot = tmp_path / "snapshot.db"
    assert vacuum_into(engine, snapshot) == snapshot
    assert snapshot.is_file() and snapshot.stat().st_size > 0

    # PG 分支：显式 no-op（不触碰连接）/ 显式报错（**不静默**）。
    pg_stub = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    assert vacuum_database(pg_stub) is False  # type: ignore[arg-type]
    with pytest.raises(DomainError) as excinfo:
        vacuum_into(pg_stub, tmp_path / "pg.db")  # type: ignore[arg-type]
    assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR


# -- ⑥ 处理器接线 + CLI 分组（data backup/restore） ---------------------------


def test_worker_maintenance_cleanup_handler_wiring(
    nfr_sqlite_factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``maintenance.cleanup`` 处理器接线：未注入抛错；注入后驱动清理。"""
    _fake_clock(monkeypatch, NOW)
    from astra_worker import HandlerContext
    from astra_worker.tasks import HANDLERS, MAINTENANCE_CLEANUP_KEY
    from astra_worker.tasks.maintenance_cleanup import handle_maintenance_cleanup

    assert MAINTENANCE_CLEANUP_KEY == RETENTION_TASK_TYPE == "maintenance.cleanup"
    assert HANDLERS[MAINTENANCE_CLEANUP_KEY] is handle_maintenance_cleanup

    # 未注入 → NotImplementedYetError（不静默）。
    with pytest.raises(NotImplementedYetError):
        handle_maintenance_cleanup({"payload": {}}, HandlerContext(providers=None, services={}))

    # 注入 → 驱动清理并回传报告 + 重试计数。
    factory = nfr_sqlite_factory
    scope = _seed_scope(factory)
    run_terminal = _add_run(factory, scope, status="SUCCESS", started_at=OLD)
    _add_message(factory, conversation_id=scope["conversation_id"], created_at=OLD)
    cleaner = RetentionCleaner(factory, RetentionPolicy(), archive_dir=tmp_path / "archive")
    ctx = HandlerContext(providers=None, services={"retention_cleanup": cleaner})
    result = handle_maintenance_cleanup({"payload": {}}, ctx)
    assert result["task"] == "maintenance.cleanup"
    assert result["attempt"] == 1
    assert result["report"]["deleted"][MESSAGE_TABLE] == 1
    assert _exists(factory, AgentRun, run_terminal)


def test_data_cli_registered_and_core_commands_intact() -> None:
    """``astra data`` 经 D5 注册可用；``init/run/doctor`` 一字未动。"""
    from astra_cli.main import app
    from typer.testing import CliRunner

    runner = CliRunner()
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for command in ("init", "run", "doctor", "data"):
        assert command in help_result.output

    data_help = runner.invoke(app, ["data", "--help"])
    assert data_help.exit_code == 0
    assert "backup" in data_help.output and "restore" in data_help.output


def test_data_backup_and_restore_roundtrip(isolated_settings_env: Path, tmp_path: Path) -> None:
    """``astra data backup`` → ``VACUUM INTO`` 快照；``restore`` → 以备份替换当前库。"""
    from astra_cli.commands.data import run_backup, run_restore

    backup_path = tmp_path / "backup" / "astra.db"
    backup_report = run_backup(str(backup_path))
    assert backup_report.action == "backup"
    assert backup_report.path == backup_path
    assert backup_path.is_file() and backup_path.stat().st_size > 0

    # 以备份替换当前库（要求停服务；此处测试库无并发连接）。
    restore_report = run_restore(str(backup_path))
    assert restore_report.action == "restore"
    assert restore_report.source == backup_path
    assert restore_report.path.read_bytes() == backup_path.read_bytes()


def test_data_backup_rejects_non_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """PG 面**显式不支持**（``CONFIGURATION_ERROR``，不静默）。"""
    monkeypatch.setenv("ASTRA_DATABASE_URL", "postgresql+psycopg://user@localhost/astra")
    from astra_config.loader import reset_settings_cache

    reset_settings_cache()
    try:
        from astra_cli.commands.data import run_backup

        with pytest.raises(DomainError) as excinfo:
            run_backup(str(tmp_path / "x.db"))
        assert excinfo.value.code == ErrorCode.CONFIGURATION_ERROR
    finally:
        reset_settings_cache()
