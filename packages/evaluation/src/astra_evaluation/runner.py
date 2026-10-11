"""``EvaluationRunner`` —— 批量执行器（设计 §2.13.2 / W9 裁定 §5.1 / §5.2）。

:meth:`EvaluationRunner.run` 读取**冻结** dataset 版本的用例（按 ``position``），经注入
:class:`~astra_evaluation.launcher.AgentRunLauncher` **受并发上限约束**逐例创建 ``agent_run``，
每例完成即写 ``evaluation_result``（含逐 case 分数）。

- **并发上限**：默认 ``4``（:data:`DEFAULT_MAX_PARALLEL`，复用 ``runtime_config.concurrency``
  口径）——以**有界线程池**实现（**不新增依赖**）；
- **固定版本**：``evaluation_run`` 同时固定 ``dataset_id`` 与 ``agent_version_id``，运行期只读；
- **取消传播（A-9）**：见 :class:`~astra_evaluation.cancel.EvaluationCancellation`；
- **汇总**：``summary`` 落通过率 / 平均分（**缺失 → ``None``，不视为 0**）。

🔴 本模块**零 Web**（能力包仅禁 Web）；**不 import** ``astra_runtime`` / ``astra_agent``。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from astra_common.time import utcnow
from astra_core import DomainError, ErrorCode

from .cancel import EvaluationCancellation, result_status_for_outcome
from .domain import (
    CANCELLED_ERROR_TYPE,
    RESULT_STATUS_CANCELLED,
    RESULT_STATUS_FAILED,
    RESULT_STATUS_SUCCESS,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCESS,
    EvaluationCase,
    EvaluationCaseRepository,
    EvaluationDataset,
    EvaluationDatasetRepository,
    EvaluationResult,
    EvaluationResultRepository,
    EvaluationRun,
    EvaluationRunRepository,
    RunStatus,
)
from .launcher import AgentRunLauncher, RunHandle
from .scorers import score_case

__all__ = ["DEFAULT_MAX_PARALLEL", "EvaluationRunner"]

#: 并发上限默认值（§5.1；复用 ``runtime_config.concurrency.max_parallel`` 口径）。
DEFAULT_MAX_PARALLEL = 4


class EvaluationRunner:
    """批量评测执行器（DI 注入四仓储 + ``AgentRunLauncher``；并发上调默认 4）。"""

    def __init__(
        self,
        *,
        datasets: EvaluationDatasetRepository,
        cases: EvaluationCaseRepository,
        runs: EvaluationRunRepository,
        results: EvaluationResultRepository,
        launcher: AgentRunLauncher,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
    ) -> None:
        """装配执行器（依赖由**组合根**注入）。

        Args:
            datasets / cases / runs / results: 四仓储（能力包 Protocol）。
            launcher: 逐例 ``agent_run`` 创建 / 等待 / 取消端口（注入 Protocol）。
            max_parallel: 并发上限（缺省 4；``<=0`` 视为 1）。
        """
        self.datasets = datasets
        self.cases = cases
        self.runs = runs
        self.results = results
        self.launcher = launcher
        self.max_parallel = max(1, int(max_parallel))
        self._cancellations: dict[str, EvaluationCancellation] = {}
        self._cancel_lock = threading.Lock()

    # -- 批量执行 -----------------------------------------------------------

    def run(self, evaluation_run_id: str) -> EvaluationRun:
        """执行一次批量评测至终态，返回更新后的 ``evaluation_run``。

        Args:
            evaluation_run_id: 目标评测标识。

        Returns:
            更新后的 :class:`~astra_evaluation.domain.EvaluationRun`（终态；已终态则原样返回）。

        Raises:
            DomainError: 评测不存在（``NOT_FOUND``）。
        """
        run = self.runs.get(evaluation_run_id)
        if run is None:
            raise DomainError(
                "Evaluation Run 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"evaluation_run_id": evaluation_run_id},
            )
        if run.is_terminal():
            return run

        run.status = RUN_STATUS_RUNNING
        if run.started_at is None:
            run.started_at = utcnow()
        run = self.runs.update(run)

        cancellation = self._cancellation(evaluation_run_id)
        dataset = self.datasets.get(run.dataset_id)
        if dataset is None:
            return self._finish(
                run,
                status=RUN_STATUS_FAILED,
                results=[],
                error_type="NOT_FOUND",
            )
        cases = self.cases.list_by_dataset(run.dataset_id)

        results: list[EvaluationResult] = []
        if cases and not cancellation.is_requested():
            workers = max(1, min(self.max_parallel, len(cases)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(self._process_case, run, dataset, case, cancellation)
                    for case in cases
                ]
                for future in as_completed(futures):
                    results.append(future.result())
        elif cases:
            # 取消已请求 → 全部用例直接置 ``CANCELLED``（不启动任何 Run）。
            for case in cases:
                results.append(
                    self._write_result(
                        run,
                        case,
                        status=RESULT_STATUS_CANCELLED,
                        error_type=CANCELLED_ERROR_TYPE,
                    )
                )

        status = RUN_STATUS_CANCELLED if cancellation.is_requested() else RUN_STATUS_SUCCESS
        return self._finish(run, status=status, results=results)

    def cancel(self, evaluation_run_id: str) -> EvaluationRun | None:
        """请求取消一次评测：置标志 + 取消已启动 Run + 置 ``CANCELLED`` 终态（幂等）。"""
        cancellation = self._cancellation(evaluation_run_id)
        cancellation.request()
        for run_id in cancellation.registered_runs():
            try:
                self.launcher.cancel(run_id)
            except Exception:  # noqa: BLE001 - 取消传播失败不阻断（已置标志，终态仍收敛）
                continue
        run = self.runs.get(evaluation_run_id)
        if run is not None and not run.is_terminal():
            run.status = RUN_STATUS_CANCELLED
            run.completed_at = utcnow()
            run = self.runs.update(run)
        return run

    # -- 内部 ---------------------------------------------------------------

    def _cancellation(self, evaluation_run_id: str) -> EvaluationCancellation:
        """取（必要时建）某评测的取消令牌（线程安全）。"""
        with self._cancel_lock:
            token = self._cancellations.get(evaluation_run_id)
            if token is None:
                token = EvaluationCancellation()
                self._cancellations[evaluation_run_id] = token
            return token

    def _process_case(
        self,
        run: EvaluationRun,
        dataset: EvaluationDataset,
        case: EvaluationCase,
        cancellation: EvaluationCancellation,
    ) -> EvaluationResult:
        """处理单条用例：未启动则直接取消；否则逐例创建 / 等待 / 评分 / 落库。"""
        if cancellation.is_requested():
            return self._write_result(
                run, case, status=RESULT_STATUS_CANCELLED, error_type=CANCELLED_ERROR_TYPE
            )

        handle: RunHandle = self.launcher.launch(
            tenant_id=run.tenant_id or "",
            organization_id=run.organization_id,
            workspace_id=run.workspace_id,
            agent_id=run.agent_id,
            agent_version_id=run.agent_version_id,
            input=case.input,
            user_id=run.created_by,
        )
        cancellation.register_run(handle.run_id)
        outcome = self.launcher.await_result(handle)

        # 运行中收到取消请求且 Run 未终态 → 按 A-9 取消并统一置 ``CANCELLED``。
        if cancellation.is_requested() and outcome.status not in RunStatus.terminal_values():
            try:
                self.launcher.cancel(handle.run_id)
            except Exception:  # noqa: BLE001 - 取消失败仍按请求收敛为 CANCELLED
                pass
            outcome.status = RUN_STATUS_CANCELLED
            outcome.error_type = CANCELLED_ERROR_TYPE

        score_result = score_case(
            case.assertions,
            output=outcome.output,
            expected=case.expected,
            tool_calls=outcome.tool_calls,
        )
        return self._write_result(
            run,
            case,
            status=result_status_for_outcome(outcome),
            agent_run_id=outcome.run_id,
            score=score_result.score,
            assertion_results=score_result.assertions or None,
            duration_ms=outcome.duration_ms,
            token_usage=outcome.token_usage,
            cost=outcome.cost,
            error_type=outcome.error_type,
        )

    def _write_result(
        self,
        run: EvaluationRun,
        case: EvaluationCase,
        *,
        status: str,
        agent_run_id: str | None = None,
        score: float | None = None,
        assertion_results: list[dict[str, Any]] | None = None,
        duration_ms: int | None = None,
        token_usage: dict[str, Any] | None = None,
        cost: float | None = None,
        error_type: str | None = None,
    ) -> EvaluationResult:
        """写（或更新）一条 ``evaluation_result``（每 case 每 Run 恰一条）。"""
        entity = EvaluationResult(
            tenant_id=run.tenant_id,
            evaluation_run_id=run.id,
            case_id=case.id,
            agent_run_id=agent_run_id,
            status=status,
            score=score,
            assertion_results=assertion_results,
            duration_ms=duration_ms,
            token_usage=token_usage,
            cost=cost,
            error_type=error_type,
        )
        existing = self.results.get_by_run_case(run.id, case.id)
        if existing is not None:
            entity.id = existing.id
            entity.created_at = existing.created_at
            return self.results.update(entity)
        return self.results.add(entity)

    def _finish(
        self,
        run: EvaluationRun,
        *,
        status: str,
        results: list[EvaluationResult],
        error_type: str | None = None,
    ) -> EvaluationRun:
        """置终态 + 汇总（通过率 / 平均分；**缺失 → ``None``，不视为 0**）。"""
        run.status = status
        run.completed_at = utcnow()
        run.summary = _summarize(results)
        if error_type is not None:
            run.summary["error_type"] = error_type
        return self.runs.update(run)


def _summarize(results: list[EvaluationResult]) -> dict[str, Any]:
    """由逐 case 结果汇总 ``evaluation_run.summary``。"""
    total = len(results)
    passed = sum(1 for result in results if result.status == RESULT_STATUS_SUCCESS)
    failed = sum(1 for result in results if result.status == RESULT_STATUS_FAILED)
    cancelled = sum(1 for result in results if result.status == RESULT_STATUS_CANCELLED)
    scores = [result.score for result in results if result.score is not None]
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "cancelled": cancelled,
        "scored": len(scores),
        "pass_rate": (passed / total) if total else None,
        "mean_score": (sum(scores) / len(scores)) if scores else None,
    }
