"""AI 任务挂靠集成测试（T1-26 / ``I-P1-12``）。

一次执行产生 ``type="agent.run"`` 的 ``task``；两条路径各自序列断言：
INLINE = ``CREATED→RUNNING→终态``（跳过 ``PENDING``）、QUEUED = ``CREATED→PENDING→RUNNING→终态``；
``task.execution_mode`` 与 ``agent_run.run_mode`` 一致；状态映射一一对应。
"""

from __future__ import annotations

from astra_conversation import AGENT_RUN_TASK_TYPE, build_conversation_services
from astra_database import SqlTaskRepository
from astra_domain import RUN_MODE_INLINE, RUN_MODE_QUEUED, RUN_STATUS_RUNNING, AgentRun


def _run_service(session_factory):  # noqa: ANN001
    return build_conversation_services(
        session_factory, task_repository=SqlTaskRepository(session_factory)
    )


def test_inline_path_skips_pending(session_factory) -> None:  # noqa: ANN001
    services = _run_service(session_factory)
    run = services.runs.add(
        AgentRun(
            conversation_id="c1",
            agent_id="a1",
            agent_version_id="v1",
            run_mode=RUN_MODE_INLINE,
            status=RUN_STATUS_RUNNING,
        )
    )
    task = services.run_service.create_for_run(run)

    assert task.type == AGENT_RUN_TASK_TYPE
    assert task.execution_mode == RUN_MODE_INLINE
    # INLINE：CREATED → RUNNING（跳过 PENDING）。
    assert task.status == "RUNNING"

    stored = services.run_service.get_for_run(run)
    assert stored is not None
    assert stored.status == "RUNNING"
    assert stored.payload["run_id"] == run.id
    assert stored.payload["conversation_id"] == "c1"

    # run.task_id 反向关联。
    refreshed = services.runs.get(run.id)
    assert refreshed.task_id == task.task_id

    # 终态同步。
    finished = services.run_service.finish(refreshed, "SUCCESS", result={"ok": True})
    assert finished is not None
    assert finished.status == "SUCCESS"


def test_queued_path_sequence(session_factory) -> None:  # noqa: ANN001
    services = _run_service(session_factory)
    run = services.runs.add(
        AgentRun(
            conversation_id="c2",
            agent_id="a1",
            agent_version_id="v1",
            run_mode=RUN_MODE_QUEUED,
            status=RUN_STATUS_RUNNING,
        )
    )
    task = services.run_service.create_for_run(run)
    sequence = [str(task.status)]

    assert task.status == "PENDING"  # CREATED → PENDING
    assert task.execution_mode == RUN_MODE_QUEUED

    task = services.run_service.mark_running(task)  # PENDING → RUNNING
    sequence.append(str(task.status))
    assert task.status == "RUNNING"

    refreshed = services.runs.get(run.id)
    task = services.run_service.finish(refreshed, "SUCCESS")  # RUNNING → SUCCESS
    sequence.append(str(task.status))

    assert sequence == ["PENDING", "RUNNING", "SUCCESS"]


def test_task_status_maps_run_terminal_states(session_factory) -> None:  # noqa: ANN001
    services = _run_service(session_factory)
    for index, run_status in enumerate(("FAILED", "CANCELLED")):
        run = services.runs.add(
            AgentRun(
                conversation_id=f"cc{index}",
                agent_id="a1",
                agent_version_id="v1",
                run_mode=RUN_MODE_INLINE,
                status=RUN_STATUS_RUNNING,
            )
        )
        services.run_service.create_for_run(run)
        refreshed = services.runs.get(run.id)
        task = services.run_service.finish(refreshed, run_status, error="boom")
        assert task is not None
        assert task.status == run_status


def test_execution_mode_matches_run_mode(session_factory) -> None:  # noqa: ANN001
    services = _run_service(session_factory)
    for index, mode in enumerate((RUN_MODE_INLINE, RUN_MODE_QUEUED)):
        run = services.runs.add(
            AgentRun(
                conversation_id=f"m{index}",
                agent_id="a1",
                agent_version_id="v1",
                run_mode=mode,
            )
        )
        task = services.run_service.create_for_run(run)
        assert task.execution_mode == run.run_mode == mode


def test_finish_failed_does_not_persist_task_error(session_factory) -> None:  # noqa: ANN001
    """``finish(error=…)`` 不把 ``error`` 写入 ``Task``（台账 A24）。

    ``task`` 表**无** ``error`` 列，故 ``finish`` 后 ``Task`` 终态正确，``error`` 恒为
    ``None``（``error`` 落 ``agent_run``）；形参保留仅为向后兼容调用方签名。
    """
    services = _run_service(session_factory)
    run = services.runs.add(
        AgentRun(
            conversation_id="err1",
            agent_id="a1",
            agent_version_id="v1",
            run_mode=RUN_MODE_INLINE,
            status=RUN_STATUS_RUNNING,
        )
    )
    task = services.run_service.create_for_run(run)
    refreshed = services.runs.get(run.id)

    finished = services.run_service.finish(refreshed, "FAILED", error="boom")
    assert finished is not None
    assert finished.status == "FAILED"
    # error 不落 task（无该列）；内存态亦不保留无效写入。
    assert finished.error is None

    reloaded = SqlTaskRepository(session_factory).get(task.task_id)
    assert reloaded is not None
    assert reloaded.status == "FAILED"
    assert reloaded.error is None
