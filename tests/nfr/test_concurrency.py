"""NFR 并发基线（W8 / T1-38；设计 §3.1 N2 · ``N-P1-02``）。

验收口径（设计 §3.1）：

> 同一 Conversation 活跃 Run 数 ≤ ``runtime_config.concurrency.max_runs_per_conversation``；
> 并发下无丢失 / 无重复写；``SELECT ... FOR UPDATE`` 或等价锁生效。

覆盖（SQLite 实跑；PG 侧严格上界见 :mod:`tests.nfr.test_pg_baselines`）：

1. **活跃 Run 上界（顺序，确定性）**：达上限后继续创建 → ``DomainError(CONFLICT)``（非排队）；
2. **活跃 Run 上界（同会话并发）**：10 线程同会话并发、``max_runs_per_conversation=1`` →
   **恰好 1 成功 / 9 ``CONFLICT``**、活跃 Run=1（``BEGIN IMMEDIATE`` 等价串行化，A37）；
3. **并发无丢失 / 无重复**：多线程并发创建（跨会话）后总数精确、主键唯一；
4. **并发下事件 ``seq`` 隔离**：并发多 Run 各自写事件，**每 Run** ``seq`` 连续唯一（无串号）；
5. **负向护栏**：``session_scope`` **默认**（不传 ``serialize_writes``）在 SQLite 下**不**发
   ``BEGIN IMMEDIATE``（读路径未受损）。

> ✅ **SQLite 并发串行化缺口已修复（A37 · ``BEGIN IMMEDIATE`` 等价串行化）**：
> ``SqlAgentRunRepository.add_guarded`` 经 ``session_scope(..., serialize_writes=True)``
> 以 ``BEGIN IMMEDIATE`` **先取写锁**，使「计数 + 建 Run」处于同一串行化写事务
> （设计 §2.7.2「等价串行化」/ ``N-P1-02``「等价锁生效」）；引擎补 busy-timeout
> （``engine.py``）。修复前本机 10 线程同会话 ``max=1`` 实测 10/10 越限，修复后
> **恰好 1 成功 / 9 拒绝**（详见用例 2）。PG 侧 ``SELECT ... FOR UPDATE`` 严格上界断言
> 保持不变（:mod:`tests.nfr.test_pg_baselines`）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

import pytest
from astra_conversation import SqlAgentEventRepository, SqlAgentRunRepository
from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from astra_database.models.conversation import AgentRun as OrmAgentRun
from astra_domain import AgentEvent, AgentRun, ConcurrencyConfig
from astra_runtime import ConcurrencyController
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

T = TypeVar("T")


def _run_concurrently(count: int, work: Callable[[int], T]) -> list[T]:
    """并发执行 ``work(i)``（``count`` 次）并返回结果列表（``work`` 内自行同步）。"""
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(work, i) for i in range(count)]
        return [future.result() for future in futures]


# -- 用例 1 / 2：上界（顺序）+ 非静默排队 ------------------------------------


def test_active_runs_bounded_sequentially(nfr_sqlite_factory: sessionmaker[Session]) -> None:
    """达上限后顺序创建 → ``CONFLICT``；活跃 Run 数恒等于上限。"""
    repo = SqlAgentRunRepository(nfr_sqlite_factory)
    concurrency = ConcurrencyController(ConcurrencyConfig(max_runs_per_conversation=2))
    for _ in range(2):
        concurrency.guard_run_creation(
            repo, AgentRun(conversation_id="c-seq", agent_id="a1", agent_version_id="v1")
        )
    with pytest.raises(DomainError) as excinfo:
        concurrency.guard_run_creation(
            repo, AgentRun(conversation_id="c-seq", agent_id="a1", agent_version_id="v1")
        )
    assert excinfo.value.code is ErrorCode.CONFLICT
    assert len(repo.list_active_by_conversation("c-seq")) == 2


def test_guard_is_not_silently_queued(nfr_sqlite_factory: sessionmaker[Session]) -> None:
    """超限**立即**抛出 ``CONFLICT``（无阻塞等待、无静默排队）。"""
    repo = SqlAgentRunRepository(nfr_sqlite_factory)
    concurrency = ConcurrencyController(ConcurrencyConfig(max_runs_per_conversation=1))
    concurrency.guard_run_creation(
        repo, AgentRun(conversation_id="c-immediate", agent_id="a1", agent_version_id="v1")
    )
    with pytest.raises(DomainError) as excinfo:
        concurrency.guard_run_creation(
            repo, AgentRun(conversation_id="c-immediate", agent_id="a1", agent_version_id="v1")
        )
    assert excinfo.value.code is ErrorCode.CONFLICT


# -- 用例 2b：上界（同会话并发 · A37 等价串行化） -----------------------------


def test_sqlite_concurrent_active_runs_bounded(
    nfr_sqlite_factory: sessionmaker[Session],
) -> None:
    """SQLite 同会话并发：**恰好 1 成功 / 9 ``CONFLICT``**、活跃 Run=1、无 ``database is locked``。

    镜像 PG 用例（``test_pg_baselines``）——W8-2 / A37 修复后 SQLite 亦**严格可证**：``add_guarded``
    经 ``serialize_writes=True``（``BEGIN IMMEDIATE``）先取写锁，「计数 + 建 Run」原子，10 线程同放
    时**其余 9 者读到已达上限而拒绝**（而非各自读到 0 全建）。
    """
    repo = SqlAgentRunRepository(nfr_sqlite_factory)
    concurrency = ConcurrencyController(ConcurrencyConfig(max_runs_per_conversation=1))
    count = 10
    barrier = threading.Barrier(count)

    def attempt(index: int) -> str:
        barrier.wait()  # 10 线程同放，最大化竞争。
        try:
            created = concurrency.guard_run_creation(
                repo,
                AgentRun(conversation_id="c-shared", agent_id="a1", agent_version_id="v1"),
            )
        except DomainError as exc:
            return "CONFLICT" if exc.code is ErrorCode.CONFLICT else f"ERROR:{exc.code}"
        except Exception as exc:  # noqa: BLE001 - 显式暴露 database is locked 等并发异常
            return f"ERROR:{exc!r}"
        return f"ok:{created.id}"

    outcomes = _run_concurrently(count, attempt)

    # 无 ``database is locked`` / 其他并发异常（busy-timeout 生效）。
    errors = [outcome for outcome in outcomes if outcome.startswith("ERROR:")]
    assert not errors, errors
    # 恰好 1 成功 / 9 CONFLICT（A37 修复后 SQLite 与 PG 口径一致）。
    assert outcomes.count("CONFLICT") == count - 1
    assert sum(outcome.startswith("ok:") for outcome in outcomes) == 1
    # 活跃 Run 恒 = 上限（1），未越限。
    assert len(repo.list_active_by_conversation("c-shared")) == 1


# -- 用例 5：负向护栏（默认 session_scope 不取写锁） --------------------------


def test_session_scope_default_does_not_take_write_lock(
    nfr_sqlite_factory: sessionmaker[Session],
) -> None:
    """负向护栏：``session_scope`` **默认**在 SQLite 下**不**发 ``BEGIN IMMEDIATE``。

    仅显式 ``serialize_writes=True`` 时取写锁——证明 W8-2 为**加性**改动：默认（含只读）路径
    不取写锁，读并发未受损（裁定 §4-5）。
    """
    engine = nfr_sqlite_factory.kw["bind"]
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement.upper())

    event.listen(engine, "before_cursor_execute", _record)
    try:
        # 默认（serialize_writes 缺省 False）→ 不发 BEGIN IMMEDIATE。
        with session_scope(nfr_sqlite_factory) as session:
            session.execute(select(func.count()).select_from(OrmAgentRun))
        assert not any("BEGIN IMMEDIATE" in stmt for stmt in statements), statements

        # 显式 serialize_writes=True → 发 BEGIN IMMEDIATE（先取写锁）。
        statements.clear()
        with session_scope(nfr_sqlite_factory, serialize_writes=True) as session:
            session.execute(select(func.count()).select_from(OrmAgentRun))
        assert any("BEGIN IMMEDIATE" in stmt for stmt in statements), statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


# -- 用例 3：并发无丢失 / 无重复（跨会话） ------------------------------------


def test_concurrent_creation_has_no_loss_or_duplicates(
    nfr_sqlite_factory: sessionmaker[Session],
) -> None:
    """多线程并发创建（每线程独立会话）：**无丢失**（总数精确）且**无重复**（主键唯一）。"""
    repo = SqlAgentRunRepository(nfr_sqlite_factory)
    concurrency = ConcurrencyController(ConcurrencyConfig(max_runs_per_conversation=1))
    count = 40
    barrier = threading.Barrier(count)

    def attempt(index: int) -> str:
        barrier.wait()
        created = concurrency.guard_run_creation(
            repo,
            AgentRun(conversation_id=f"c-{index}", agent_id="a1", agent_version_id="v1"),
        )
        return created.id

    ids = _run_concurrently(count, attempt)
    assert len(ids) == count
    assert len(set(ids)) == count, "并发建 Run 出现重复主键"
    # 全部落库（无丢失）。
    assert all(repo.get(run_id) is not None for run_id in ids)


# -- 用例 4：并发下事件 seq 隔离 ----------------------------------------------


def test_per_run_event_seq_contiguous_under_concurrent_runs(
    nfr_sqlite_factory: sessionmaker[Session],
) -> None:
    """并发多 Run 各自写事件：**每 Run** ``seq`` 连续唯一（无跨 Run 串号 / 丢失）。"""
    run_repo = SqlAgentRunRepository(nfr_sqlite_factory)
    event_repo = SqlAgentEventRepository(nfr_sqlite_factory)
    threads = 8
    runs_per_thread = 4
    events_per_run = 25
    barrier = threading.Barrier(threads)

    def worker(index: int) -> list[str]:
        created_ids: list[str] = []
        barrier.wait()
        for run_index in range(runs_per_thread):
            run = run_repo.add(
                AgentRun(
                    conversation_id=f"c-{index}-{run_index}",
                    agent_id="a1",
                    agent_version_id="v1",
                )
            )
            event_repo.add_many(
                [
                    AgentEvent(run_id=run.id, type="agent.thinking", payload={"i": i})
                    for i in range(events_per_run)
                ]
            )
            created_ids.append(run.id)
        return created_ids

    batches = _run_concurrently(threads, worker)
    all_runs = [run_id for batch in batches for run_id in batch]
    assert len(all_runs) == threads * runs_per_thread
    for run_id in all_runs:
        seqs = [event.seq for event in event_repo.list_by_run(run_id)]
        assert seqs == list(range(1, events_per_run + 1)), (run_id, seqs)
