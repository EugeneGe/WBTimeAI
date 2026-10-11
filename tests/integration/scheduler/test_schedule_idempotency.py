"""调度 / 幂等集成测试（W7 / T2-39；R6 / §2.9 / §3.4）。

覆盖：

- **幂等键**：``f"{target_type}:{target_id}:{fire_time.isoformat()}"``（冻结契约）；
- **只建 1 个 task**：同一 ``(target_type, target_id, fire_time)`` 二次触发命中
  ``ScheduleRepository.get_or_create_task`` → 返回**既有** ``task_id``（``created=False``），
  ``task`` 表仅 1 行；``task_execution`` 仅 1 行（``attempt = 1``）；
- **每次执行落 task_execution**：``attempt`` 从 **1** 起、自增（1 → 2）；
- **到期轮询**：``SchedulerTick.tick(now)`` 仅触发 ``enabled`` 且 ``next_run_at <= now`` 的调度，
  并推进 ``last_run_at / next_run_at``；**fake clock**（显式注入 ``now``）；
- **零 ORM**：``astra_task`` 不 import ``astra_database`` / ``sqlalchemy``（硬门禁 R2）。

🔴 SQLite（本地可复现）验证**逻辑级**幂等 + 唯一索引（``uq_task_idempotency_key``）生效；
   PostgreSQL 权威 ``alembic check`` 零漂移由 ``test_0015`` 的门控用例覆盖。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

#: 固定基准时刻（fake clock；对齐整分，便于 cron 计算）。
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def session_factory():
    """隔离的内存 SQLite + 全部 ORM 表（含 ``uq_task_idempotency_key`` / ``schedule``）。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_database.base import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def repos(session_factory):
    """构造 SQL 仓储实现（``SqlScheduleRepository`` / ``SqlTaskExecutionRepository``）。"""
    from astra_database.repositories import SqlScheduleRepository, SqlTaskExecutionRepository

    return SqlScheduleRepository(session_factory), SqlTaskExecutionRepository(session_factory)


def _count_tasks(session_factory, *, idempotency_key: str) -> int:
    """统计某幂等键对应的 ``task`` 行数。"""
    from astra_database.models.task import Task as OrmTask
    from sqlalchemy import func, select

    with session_factory() as session:
        return int(
            session.execute(
                select(func.count())
                .select_from(OrmTask)
                .where(OrmTask.idempotency_key == idempotency_key)
            ).scalar_one()
        )


def test_idempotency_key_format() -> None:
    """幂等键格式冻结：``f"{target_type}:{target_id}:{fire_time.isoformat()}"``（R6）。"""
    from astra_task import idempotency_key

    key = idempotency_key("agent", "agent-1", T0)
    assert key == f"agent:agent-1:{T0.isoformat()}"


def test_get_or_create_task_is_idempotent(session_factory, repos) -> None:
    """同一 ``idempotency_key`` 二次触发**只建 1 个 task**（R6）。"""
    schedules, _executions = repos
    key = f"agent:agent-1:{T0.isoformat()}"

    task_id_1, created_1 = schedules.get_or_create_task(
        tenant_id="tenant-1",
        workspace_id=None,
        task_type="agent.cron",
        payload={"k": "v"},
        idempotency_key=key,
    )
    task_id_2, created_2 = schedules.get_or_create_task(
        tenant_id="tenant-1",
        workspace_id=None,
        task_type="agent.cron",
        payload={"k": "v"},
        idempotency_key=key,
    )

    assert created_1 is True
    assert created_2 is False
    assert task_id_1 == task_id_2
    assert _count_tasks(session_factory, idempotency_key=key) == 1


def test_scheduler_tick_fires_due_schedule_and_records_execution(session_factory, repos) -> None:
    """``tick(now)`` 触发到期调度 → 1 个 task + 1 条执行记录（``attempt = 1``）。"""
    from astra_task import SchedulerTick

    schedules, executions = repos
    tick = SchedulerTick(schedules=schedules, executions=executions)
    schedule = schedules.create(
        tenant_id="tenant-1",
        name="nightly",
        target_type="agent",
        target_id="agent-1",
        trigger="cron",
        cron="0 * * * *",
    )
    # 置为到期（next_run_at = T0）。
    schedule.next_run_at = T0
    schedules.update(schedule)

    fired = tick.tick(T0)
    assert len(fired) == 1

    # 执行记录：attempt 从 1 起。
    records = executions.list_by_task(fired[0])
    assert [r.attempt for r in records] == [1]

    # 推进 last_run_at / next_run_at。
    updated = schedules.get(schedule.id)
    assert updated is not None
    assert updated.last_run_at == T0
    assert updated.next_run_at is not None and updated.next_run_at > T0

    # 幂等：再次 tick（同 now）—— 调度已不再到期 → 0 新建。
    assert tick.tick(T0) == []


def test_fire_now_is_idempotent_at_same_fire_time(session_factory, repos) -> None:
    """``fire_now(now, schedule)`` 二次（同 ``now``）→ 同 ``task_id``、仅 1 执行记录（R6）。"""
    from astra_task import SchedulerTick

    schedules, executions = repos
    tick = SchedulerTick(schedules=schedules, executions=executions)
    schedule = schedules.create(
        tenant_id="tenant-1",
        name="on-demand",
        target_type="workflow",
        target_id="workflow-1",
        trigger="manual",
    )

    task_id_1 = tick.fire_now(T0, schedule)
    task_id_2 = tick.fire_now(T0, schedule)

    assert task_id_1 == task_id_2
    key = f"workflow:workflow-1:{T0.isoformat()}"
    assert _count_tasks(session_factory, idempotency_key=key) == 1
    assert len(executions.list_by_task(task_id_1)) == 1


def test_execution_recorder_attempt_increments(session_factory, repos) -> None:
    """``attempt`` 自增：``begin`` 两次 → 1 然后 2。"""
    from astra_task import ExecutionRecorder

    _schedules, executions = repos
    recorder = ExecutionRecorder(executions)
    first = recorder.begin(task_id="task-x", started_at=T0)
    second = recorder.begin(task_id="task-x", started_at=T0 + timedelta(seconds=1))

    assert (first.attempt, second.attempt) == (1, 2)
    assert [r.attempt for r in executions.list_by_task("task-x")] == [1, 2]


def test_list_due_honours_enabled_and_next_run(session_factory, repos) -> None:
    """``list_due`` 仅返回 ``enabled`` 且 ``next_run_at <= now`` 的调度。"""
    schedules, _executions = repos
    due = schedules.create(
        tenant_id="tenant-1",
        name="due",
        target_type="agent",
        target_id="a-1",
        trigger="cron",
        cron="0 * * * *",
    )
    due.next_run_at = T0
    schedules.update(due)

    future = schedules.create(
        tenant_id="tenant-1",
        name="future",
        target_type="agent",
        target_id="a-2",
        trigger="cron",
        cron="0 * * * *",
    )
    future.next_run_at = T0 + timedelta(hours=1)
    schedules.update(future)

    disabled = schedules.create(
        tenant_id="tenant-1",
        name="disabled",
        target_type="agent",
        target_id="a-3",
        trigger="cron",
        cron="0 * * * *",
        enabled=False,
    )
    disabled.next_run_at = T0
    schedules.update(disabled)

    due_ids = {s.id for s in schedules.list_due(now=T0)}
    assert due.id in due_ids
    assert future.id not in due_ids
    assert disabled.id not in due_ids


def test_astra_task_package_is_zero_orm() -> None:
    """🔴 ``astra_task`` 整包**不 import** ``astra_database`` / ``sqlalchemy``（硬门禁 R2）。"""
    from pathlib import Path

    import astra_task

    package_dir = Path(astra_task.__file__).resolve().parent
    forbidden = {"sqlalchemy", "astra_database"}
    offenders: list[str] = []
    for path in package_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and any(
                token in stripped for token in forbidden
            ):
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, f"astra_task 违规 import：{offenders}"
