"""Evaluation 批量执行 / 确定性 scorer / 回归对比 集成测试（W9 / T2-46）。

覆盖（W9 裁定 §5 / §9；验收 ``I-P2-43``）：

- **批量产出逐 case 分数**：固定版本批量 Run → 每 case 恰一条结果 + 分数；
- **失败 / 取消可区分**：``SUCCESS | FAILED | CANCELLED`` 三态 + ``error_type``；
- **两版本对比**：同 dataset version 两 ``agent_version``；缺失指标 ``N/A``（``None``）；
- **幂等**：``idempotency_key`` 唯一（重复 → ``IntegrityError``；``get_by_idempotency_key`` 命中）；
- **取消传播（A-9）**：已启动 Run 经 ``launcher.cancel``；未开始 case 直接 ``CANCELLED``；
- **``tool_error_count`` 口径**：只数 ``FAILED``；``DENIED`` 单独读取。

用 **fake ``AgentRunLauncher``**（不依赖 runtime / 真实模型）。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import pytest
from astra_evaluation import (
    DEFAULT_MAX_PARALLEL,
    AgentRunLauncher,
    EvaluationCancellation,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationRunner,
    RunHandle,
    RunOutcome,
    ToolCallView,
    build_evaluation_repositories,
    compare_runs,
    count_tool_denials,
    count_tool_errors,
    score_case,
)
from sqlalchemy.exc import IntegrityError

_TENANT = "00000000-0000-7000-8000-000000000e01"
_AGENT = "00000000-0000-7000-8000-000000000e02"


# -- fixtures / helpers ------------------------------------------------------


class FakeLauncher:
    """按用例 ``input`` 规格模拟逐例 ``agent_run``（注入 Protocol 实现）。"""

    def __init__(self) -> None:
        self.launched: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self._counter = 0
        self._lock = threading.Lock()

    def launch(
        self,
        *,
        tenant_id: str,
        organization_id: str | None,
        workspace_id: str | None,
        agent_id: str,
        agent_version_id: str,
        input: Any,
        user_id: str | None = None,
    ) -> RunHandle:
        with self._lock:
            self._counter += 1
            run_id = f"run-{self._counter}"
            self.launched.append(
                {"run_id": run_id, "input": input, "agent_version_id": agent_version_id}
            )
        return RunHandle(run_id=run_id)

    def await_result(self, handle: RunHandle) -> RunOutcome:
        record = next(item for item in self.launched if item["run_id"] == handle.run_id)
        spec = record["input"] if isinstance(record["input"], dict) else {}
        tool_calls = [
            ToolCallView(name=str(name), status=str(status))
            for name, status in spec.get("tool_calls", [])
        ]
        return RunOutcome(
            run_id=handle.run_id,
            status=str(spec.get("status", "SUCCESS")),
            output=spec.get("output"),
            error_type=spec.get("error_type"),
            duration_ms=spec.get("duration_ms"),
            token_usage=spec.get("token_usage"),
            cost=spec.get("cost"),
            tool_calls=tool_calls,
        )

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)


@pytest.fixture()
def repos(session_factory: object) -> Any:
    """基于隔离 SQLite 的四仓储集合。"""
    return build_evaluation_repositories(session_factory)  # type: ignore[arg-type]


def _seed_dataset(repos: Any, *, published: bool = True) -> EvaluationDataset:
    dataset = repos.datasets.add(EvaluationDataset(tenant_id=_TENANT, name="ds"))
    if published:
        dataset.publish()
        dataset = repos.datasets.update(dataset)
    return dataset


def _add_case(
    repos: Any,
    dataset_id: str,
    case_key: str,
    case_input: Any,
    *,
    expected: Any = None,
    assertions: list[dict[str, Any]] | None = None,
    position: int = 0,
) -> EvaluationCase:
    return repos.cases.add(
        EvaluationCase(
            dataset_id=dataset_id,
            case_key=case_key,
            input=case_input,
            expected=expected,
            assertions=assertions or [],
            position=position,
        )
    )


def _new_run(repos: Any, dataset_id: str, agent_version: str = "v1") -> EvaluationRun:
    return repos.runs.add(
        EvaluationRun(
            tenant_id=_TENANT,
            dataset_id=dataset_id,
            agent_id=_AGENT,
            agent_version_id=agent_version,
        )
    )


def _results_by_key(repos: Any, run_id: str, cases: list[EvaluationCase]) -> dict[str, Any]:
    key_by_id = {case.id: case.case_key for case in cases}
    return {key_by_id[r.case_id]: r for r in repos.results.list_by_run(run_id)}


# -- 批量执行 + 逐 case 分数 --------------------------------------------------


def test_batch_produces_per_case_scores(repos: Any) -> None:
    """固定版本批量 Run → 逐 case 分数（含**无断言 → ``None``**）。"""
    dataset = _seed_dataset(repos)
    cases = [
        _add_case(
            repos,
            dataset.id,
            "c1",
            {"output": "hello"},
            expected="hello",
            assertions=[{"scorer": "exact_match", "weight": 1, "params": {}}],
            position=0,
        ),
        _add_case(
            repos,
            dataset.id,
            "c2",
            {"output": "the answer is 42"},
            assertions=[{"scorer": "contains", "weight": 1, "params": {"values": ["42"]}}],
            position=1,
        ),
        _add_case(repos, dataset.id, "c3", {"output": "anything"}, position=2),
    ]
    run = _new_run(repos, dataset.id)
    runner = EvaluationRunner(
        datasets=repos.datasets,
        cases=repos.cases,
        runs=repos.runs,
        results=repos.results,
        launcher=FakeLauncher(),
        max_parallel=DEFAULT_MAX_PARALLEL,
    )

    finished = runner.run(run.id)

    assert finished.status == "SUCCESS"
    assert finished.started_at is not None
    assert finished.completed_at is not None
    by_key = _results_by_key(repos, run.id, cases)
    assert set(by_key) == {"c1", "c2", "c3"}
    assert by_key["c1"].score == 1.0
    assert by_key["c2"].score == 1.0
    assert by_key["c3"].score is None  # 无断言 → N/A（不视为 0）
    assert all(by_key[key].agent_run_id for key in by_key)
    assert finished.summary is not None
    assert finished.summary["passed"] == 3
    assert finished.summary["pass_rate"] == 1.0
    assert finished.summary["mean_score"] == 1.0
    assert finished.summary["scored"] == 2


def test_failed_and_cancelled_distinguishable(repos: Any) -> None:
    """失败 / 取消状态可区分（``FAILED`` vs ``CANCELLED`` + ``error_type``）。"""
    dataset = _seed_dataset(repos)
    cases = [
        _add_case(repos, dataset.id, "ok", {"output": "x", "status": "SUCCESS"}, position=0),
        _add_case(
            repos,
            dataset.id,
            "bad",
            {"status": "FAILED", "error_type": "MODEL_ERROR"},
            position=1,
        ),
        _add_case(
            repos,
            dataset.id,
            "cxl",
            {"status": "CANCELLED", "error_type": "CANCELLED"},
            position=2,
        ),
    ]
    run = _new_run(repos, dataset.id)
    runner = EvaluationRunner(
        datasets=repos.datasets,
        cases=repos.cases,
        runs=repos.runs,
        results=repos.results,
        launcher=FakeLauncher(),
    )

    runner.run(run.id)
    by_key = _results_by_key(repos, run.id, cases)
    assert by_key["ok"].status == "SUCCESS"
    assert by_key["bad"].status == "FAILED"
    assert by_key["bad"].error_type == "MODEL_ERROR"
    assert by_key["cxl"].status == "CANCELLED"
    assert by_key["cxl"].error_type == "CANCELLED"


def test_cancel_blocks_pending_cases(repos: Any) -> None:
    """取消传播：已启动 Run 经 ``launcher.cancel``；未开始 case 直接 ``CANCELLED``（A-9）。"""
    dataset = _seed_dataset(repos)
    for index in range(3):
        _add_case(repos, dataset.id, f"c{index}", {"output": "ok"}, position=index)
    run = _new_run(repos, dataset.id)

    gate = threading.Event()
    launched = threading.Event()

    class SlowLauncher(FakeLauncher):
        def launch(self, **kwargs: Any) -> RunHandle:
            handle = super().launch(**kwargs)
            launched.set()
            return handle

        def await_result(self, handle: RunHandle) -> RunOutcome:
            gate.wait(timeout=10)
            return super().await_result(handle)

    launcher = SlowLauncher()
    runner = EvaluationRunner(
        datasets=repos.datasets,
        cases=repos.cases,
        runs=repos.runs,
        results=repos.results,
        launcher=launcher,
        max_parallel=1,
    )

    finished_holder: dict[str, EvaluationRun] = {}

    def _run_in_thread() -> None:
        finished_holder["run"] = runner.run(run.id)

    thread = threading.Thread(target=_run_in_thread)
    thread.start()
    assert launched.wait(timeout=10), "首个 Run 未启动"
    runner.cancel(run.id)
    gate.set()
    thread.join(timeout=10)

    assert launcher.cancelled, "已启动 Run 未按 A-9 取消"
    final = repos.runs.get(run.id)
    assert final is not None and final.status == "CANCELLED"
    statuses = [result.status for result in repos.results.list_by_run(run.id)]
    assert statuses.count("SUCCESS") == 1
    assert statuses.count("CANCELLED") == 2


# -- 幂等 --------------------------------------------------------------------


def test_idempotency_key_unique(repos: Any) -> None:
    """``evaluation_run.idempotency_key`` 唯一：重复 → ``IntegrityError``；``get_by_...`` 命中。"""
    dataset = _seed_dataset(repos)
    repos.runs.add(
        EvaluationRun(
            tenant_id=_TENANT,
            dataset_id=dataset.id,
            agent_id=_AGENT,
            agent_version_id="v1",
            idempotency_key="k-1",
        )
    )
    assert repos.runs.get_by_idempotency_key("k-1") is not None
    with pytest.raises(IntegrityError):
        repos.runs.add(
            EvaluationRun(
                tenant_id=_TENANT,
                dataset_id=dataset.id,
                agent_id=_AGENT,
                agent_version_id="v1",
                idempotency_key="k-1",
            )
        )


# -- 回归对比 ----------------------------------------------------------------


def _result(
    run_id: str,
    case_id: str,
    *,
    status: str,
    score: float | None = None,
    duration_ms: int | None = None,
    tokens: int | None = None,
    cost: float | None = None,
) -> EvaluationResult:
    token_usage = {"total": tokens} if tokens is not None else None
    return EvaluationResult(
        evaluation_run_id=run_id,
        case_id=case_id,
        status=status,
        score=score,
        duration_ms=duration_ms,
        token_usage=token_usage,
        cost=cost,
    )


def test_compare_two_versions_report(repos: Any) -> None:
    """两版本对比：通过率 / 平均分 / 失败分解 / 耗时 / Token / 成本（缺失 ``N/A``）。"""
    dataset = _seed_dataset(repos)
    case_a = _add_case(repos, dataset.id, "c1", {}, position=0)
    case_b = _add_case(repos, dataset.id, "c2", {}, position=1)

    baseline = _new_run(repos, dataset.id, "vA")
    candidate = _new_run(repos, dataset.id, "vB")

    baseline_results = [
        _result(
            baseline.id,
            case_a.id,
            status="SUCCESS",
            score=1.0,
            duration_ms=100,
            tokens=10,
            cost=0.1,
        ),
        _result(baseline.id, case_b.id, status="FAILED"),
    ]
    candidate_results = [
        _result(
            candidate.id,
            case_a.id,
            status="SUCCESS",
            score=1.0,
            duration_ms=80,
            tokens=8,
            cost=0.08,
        ),
        _result(
            candidate.id,
            case_b.id,
            status="SUCCESS",
            score=1.0,
            duration_ms=90,
            tokens=9,
            cost=0.09,
        ),
    ]

    report = compare_runs(
        dataset=dataset,
        baseline=baseline,
        candidate=candidate,
        baseline_results=baseline_results,
        candidate_results=candidate_results,
        cases=[case_a, case_b],
    )

    assert report.dataset_version == 1
    assert report.agent_version_a == "vA"
    assert report.agent_version_b == "vB"
    assert report.pass_rate.a == 0.5
    assert report.pass_rate.b == 1.0
    assert report.pass_rate.delta == 0.5
    assert report.mean_score.a == 1.0
    assert report.mean_score.b == 1.0
    assert report.mean_score.delta == 0.0
    assert report.fails.only_a == ["c2"]
    assert report.fails.only_b == []
    assert report.fails.both == []
    # 平均耗时：A=100（c1；c2 无耗时）→ B=(80+90)/2=85 → delta=-15。
    assert report.duration_ms.a == 100.0
    assert report.duration_ms.b == 85.0
    assert report.duration_ms.delta == -15.0
    assert report.token_usage.a == 10.0
    assert report.token_usage.b == 8.5
    assert report.cost.a == 0.1


def test_compare_missing_metric_is_na_not_zero(repos: Any) -> None:
    """缺失指标 → ``N/A``（``None``）；``delta`` 任一测为空亦 ``None``（**不视为 0**）。"""
    dataset = _seed_dataset(repos)
    case_a = _add_case(repos, dataset.id, "c1", {}, position=0)
    baseline = _new_run(repos, dataset.id, "vA")
    candidate = _new_run(repos, dataset.id, "vB")

    report = compare_runs(
        dataset=dataset,
        baseline=baseline,
        candidate=candidate,
        baseline_results=[_result(baseline.id, case_a.id, status="FAILED")],
        candidate_results=[_result(candidate.id, case_a.id, status="FAILED")],
        cases=[case_a],
    )
    assert report.mean_score.a is None
    assert report.mean_score.b is None
    assert report.mean_score.delta is None
    assert report.cost.a is None
    assert report.token_usage.a is None


# -- tool_error_count 口径 + scorer ------------------------------------------


def test_tool_error_count_scope() -> None:
    """``tool_error_count`` 只数 ``FAILED``；``DENIED`` 单独读取（§5.3 冻结口径）。"""
    calls = [
        ToolCallView(name="search", status="SUCCESS"),
        ToolCallView(name="write", status="FAILED"),
        ToolCallView(name="rm", status="DENIED"),
        ToolCallView(name="read", status="FAILED"),
    ]
    assert count_tool_errors(calls) == 2
    assert count_tool_denials(calls) == 1


def test_scorer_weight_normalization_and_weighted_sequence() -> None:
    """权重归一：``Σ(w·s)/Σ(w)``；``tool_call_sequence`` 子序列匹配。"""
    case_score = score_case(
        [
            {"scorer": "exact_match", "weight": 3, "params": {}},
            {"scorer": "contains", "weight": 1, "params": {"values": ["zzz"]}},
        ],
        output="hello",
        expected="hello",
    )
    assert case_score.score == 0.75  # (3*1 + 1*0) / 4
    assert [item["passed"] for item in case_score.assertions] == [True, False]

    seq = score_case(
        [{"scorer": "tool_call_sequence", "weight": 1, "params": {"sequence": ["a", "c"]}}],
        output="",
        tool_calls=[
            ToolCallView("a", "SUCCESS"),
            ToolCallView("b", "SUCCESS"),
            ToolCallView("c", "SUCCESS"),
        ],
    )
    assert seq.score == 1.0

    assert score_case(None, output="x").score is None


def test_cancellation_token_registers_runs() -> None:
    """``EvaluationCancellation`` 线程安全登记（去重）+ 请求标志。"""
    token = EvaluationCancellation()
    assert not token.is_requested()
    token.register_run("r1")
    token.register_run("r1")
    token.register_run("r2")
    assert token.registered_runs() == ["r1", "r2"]
    token.request()
    assert token.is_requested()


def test_fake_launcher_satisfies_protocol() -> None:
    """正向断言：fake 实现结构化满足 ``AgentRunLauncher`` Protocol。"""
    assert isinstance(FakeLauncher(), AgentRunLauncher)


def test_repos_fixture_smoke(repos: Any) -> None:
    """四仓储可装配（冒烟）。"""
    dataset = _seed_dataset(repos, published=False)
    assert dataset.status == "DRAFT"
    listed: Iterator[EvaluationDataset] = iter(repos.datasets.list())
    assert any(item.id == dataset.id for item in listed)
