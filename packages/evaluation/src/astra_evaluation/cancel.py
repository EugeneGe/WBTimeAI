"""取消传播（A-9；W9 裁定 §5.2）。

- :class:`EvaluationCancellation`：**线程安全**取消标志 + 已启动 ``agent_run`` 句柄登记。

语义（§5.2）：

- 取消 ``evaluation_run`` → **阻止尚未开始的 case**（runner 每例开工前检查 :meth:`is_requested`，
  未启动者直接置 ``CANCELLED``）；
- 对**已启动**的 Run：经 :meth:`AgentRunLauncher.cancel` **按 A-9** 取消（传播到 runtime
  取消路径）；
- 终态：取消的 ``evaluation_result.status="CANCELLED"``、``error_type="CANCELLED"``（统一词表）。
"""

from __future__ import annotations

import threading

from .domain import RESULT_STATUS_CANCELLED, RESULT_STATUS_FAILED, RESULT_STATUS_SUCCESS
from .launcher import RunOutcome

__all__ = ["EvaluationCancellation", "result_status_for_outcome"]

#: ``agent_run`` 终态 → ``evaluation_result.status`` 映射（取消统一 ``CANCELLED``）。
_OUTCOME_TO_RESULT_STATUS: dict[str, str] = {
    "SUCCESS": RESULT_STATUS_SUCCESS,
    "FAILED": RESULT_STATUS_FAILED,
    "CANCELLED": RESULT_STATUS_CANCELLED,
}


def result_status_for_outcome(outcome: RunOutcome) -> str:
    """把 ``agent_run`` 终态映射为 ``evaluation_result.status``（未知 → ``FAILED``）。"""
    return _OUTCOME_TO_RESULT_STATUS.get(outcome.status, RESULT_STATUS_FAILED)


class EvaluationCancellation:
    """线程安全的取消标志 + 已启动 Run 登记（A-9 取消传播）。"""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._runs: list[str] = []
        self._lock = threading.Lock()

    def request(self) -> None:
        """置取消标志（幂等）。"""
        self._event.set()

    def is_requested(self) -> bool:
        """是否已请求取消。"""
        return self._event.is_set()

    def register_run(self, run_id: str) -> None:
        """登记一条已启动的 ``agent_run``（去重；供取消传播遍历）。"""
        with self._lock:
            if run_id not in self._runs:
                self._runs.append(run_id)

    def registered_runs(self) -> list[str]:
        """返回已登记的 ``agent_run`` 标识快照。"""
        with self._lock:
            return list(self._runs)
