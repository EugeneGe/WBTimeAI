"""``LocalScheduler`` 一次性任务调度单测（懒启动）。"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from astra_task import LocalScheduler


def test_schedule_once_runs() -> None:
    scheduler = LocalScheduler()
    fired = threading.Event()

    run_at = datetime.now(UTC) + timedelta(seconds=0.2)
    job_id = scheduler.schedule_once(run_at, fired.set)
    assert isinstance(job_id, str) and job_id

    scheduler.start()
    try:
        assert fired.wait(timeout=5.0) is True
    finally:
        scheduler.shutdown()


def test_constructor_does_not_start() -> None:
    scheduler = LocalScheduler()
    assert scheduler.started is False
