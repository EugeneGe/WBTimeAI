"""``/api/v1/evaluation`` API 集成测试（W9 / T2-47；设计 §2.13.2 / 裁定 R1 / R6）。

覆盖：

- 任务集创建 / 详情 / 列表（三维过滤）+ **统一响应壳**；
- 用例导入（**schema 校验 + 敏感扫描**）+ 重复 ``case_key`` → ``CONFLICT``；
- 发布后用例**不可修改**（``CONFLICT``）；
- **幂等启动**批量评测（同键返回既有 Run；不重复创建）；
- 评测详情 **逐 case 分数**（无断言 → ``score=null`` ＝ ``N/A``）；
- 两版本回归对比（通过率 / 均分 / 失败 case / ``delta``）；
- 跨租户 → **404**；无权限 → **403**。

🔴 逐例 ``agent_run`` 创建经**注入** ``AgentRunLauncher``（组合根 bridge）；本测试以确定性
**fake launcher** 替换（``services.evaluation.runner.launcher``），从而在无模型 / 无 Sandbox
的隔离环境下稳定复现「固定版本 + 逐 case 分数 + 两版本对比」（T2-46 的同一契约）。
"""

from __future__ import annotations

from typing import Any

import pytest
from astra_application import EvaluationService
from astra_core import DomainError, ErrorCode
from astra_evaluation import (
    EvaluationRunner,
    RunHandle,
    RunOutcome,
    build_evaluation_repositories,
)

_DATASETS = "/api/v1/evaluation/datasets"
_RUNS = "/api/v1/evaluation/runs"

#: 敏感明文样例（命中扫描）。
_SECRET = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class _FakeLauncher:
    """确定性 fake ``AgentRunLauncher``（替换组合根 bridge）。

    按 ``agent_version_id`` 决定终态 / 输出：``fail_versions`` 内的版本置 ``FAILED``，
    否则置 ``SUCCESS`` 并输出该版本的固定文本（供 ``contains`` 断言评分）。
    """

    def __init__(
        self,
        *,
        output_by_version: dict[str, str] | None = None,
        fail_versions: set[str] | None = None,
        default_output: str = "OK",
    ) -> None:
        self._output_by_version = dict(output_by_version or {})
        self._fail_versions = set(fail_versions or set())
        self._default_output = default_output
        self._counter = 0
        self._versions: dict[str, str] = {}

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
        """创建一条 fake Run 句柄（记录版本）。"""
        self._counter += 1
        run_id = f"agent-run-{self._counter}"
        self._versions[run_id] = agent_version_id
        return RunHandle(run_id=run_id)

    def await_result(self, handle: RunHandle) -> RunOutcome:
        """返回确定性终态快照。"""
        version = self._versions.get(handle.run_id, "")
        if version in self._fail_versions:
            return RunOutcome(
                run_id=handle.run_id,
                status="FAILED",
                output="BAD",
                error_type="UPSTREAM_ERROR",
                duration_ms=9,
            )
        output = self._output_by_version.get(version, self._default_output)
        return RunOutcome(
            run_id=handle.run_id,
            status="SUCCESS",
            output=output,
            duration_ms=7,
            token_usage={"total": 11},
            cost=0.02,
        )

    def cancel(self, run_id: str) -> None:
        """取消（fake no-op）。"""
        return None


# -- 辅助 --------------------------------------------------------------------


def _data(response: Any) -> Any:
    """从统一响应壳取 ``data``。"""
    body = response.json()
    assert "data" in body, response.text
    return body["data"]


def _inject_fake_launcher(client: Any, launcher: _FakeLauncher) -> None:
    """把组合根 ``EvaluationRunner`` 的 launcher 替换为确定性 fake。"""
    client.app.state.services.evaluation.runner.launcher = launcher


def _create_dataset(client: Any, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    """创建任务集并返回其 ``data``。"""
    payload: dict[str, Any] = {"name": "ds-1"}
    payload.update(overrides)
    response = client.post(_DATASETS, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return _data(response)


def _import_cases(
    client: Any, headers: dict[str, str], dataset_id: str, cases: list[dict[str, Any]]
) -> Any:
    """导入用例请求。"""
    return client.post(f"{_DATASETS}/{dataset_id}/cases", headers=headers, json={"cases": cases})


def _publish(client: Any, headers: dict[str, str], dataset_id: str) -> Any:
    """发布任务集请求。"""
    return client.post(f"{_DATASETS}/{dataset_id}/publish", headers=headers)


def _start_run(
    client: Any,
    headers: dict[str, str],
    *,
    dataset_id: str,
    agent_version_id: str,
    idempotency_key: str | None = None,
) -> Any:
    """启动评测请求。"""
    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "agent_id": "agent-1",
        "agent_version_id": agent_version_id,
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return client.post(_RUNS, headers=headers, json=payload)


def _contains_ok() -> dict[str, Any]:
    """``contains`` 断言（期望输出含 ``OK``）。"""
    return {"scorer": "contains", "weight": 1.0, "params": {"values": ["OK"]}}


def _seed_published_dataset(
    client: Any, headers: dict[str, str]
) -> tuple[str, list[dict[str, Any]]]:
    """建一个含 2 用例（1 断言 / 1 无断言）的已发布任务集。"""
    dataset = _create_dataset(client, headers)
    cases = [
        {"case_key": "case-1", "input": {"q": "hello"}, "assertions": [_contains_ok()]},
        {"case_key": "case-2", "input": {"q": "world"}},
    ]
    imported = _import_cases(client, headers, dataset["id"], cases)
    assert imported.status_code == 201, imported.text
    assert _publish(client, headers, dataset["id"]).status_code == 200
    return dataset["id"], _data(imported)


# -- 任务集 ------------------------------------------------------------------


def test_create_and_get_dataset(client: Any, auth_headers: dict[str, str]) -> None:
    """创建（``DRAFT``/``version=1``）并可经详情读回。"""
    dataset = _create_dataset(client, auth_headers, name="regression-a")
    assert dataset["status"] == "DRAFT"
    assert dataset["version"] == 1
    assert dataset["id"]

    fetched = client.get(f"{_DATASETS}/{dataset['id']}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert _data(fetched)["id"] == dataset["id"]


def test_list_datasets_scope_filter(client: Any, auth_headers: dict[str, str]) -> None:
    """列表支持 ``workspace_id`` 三维过滤。"""
    _create_dataset(client, auth_headers, name="ws-1", workspace_id="ws-1")
    _create_dataset(client, auth_headers, name="ws-2", workspace_id="ws-2")

    all_items = _data(client.get(_DATASETS, headers=auth_headers))
    assert len(all_items) >= 2

    filtered = _data(client.get(_DATASETS, headers=auth_headers, params={"workspace_id": "ws-1"}))
    assert [item["name"] for item in filtered] == ["ws-1"]


def test_cross_tenant_dataset_is_not_found(session_factory: Any) -> None:
    """跨租户读取任务集 → ``NOT_FOUND``（隔离不变量 I-1；服务层，非 403）。

    🔴 经服务层断言（API 守卫按 RBAC 先判权限 → 无权限用户为 403；跨租户 ``NOT_FOUND``
    为**隔离**语义，与 ``test_cross_tenant_404.py`` 同口径）。
    """
    repos = build_evaluation_repositories(session_factory)
    service = EvaluationService(
        datasets=repos.datasets,
        cases=repos.cases,
        runs=repos.runs,
        results=repos.results,
        runner=EvaluationRunner(
            datasets=repos.datasets,
            cases=repos.cases,
            runs=repos.runs,
            results=repos.results,
            launcher=_FakeLauncher(),
        ),
    )
    created = service.create_dataset(tenant_id="tenant-a", user_id="u1", name="x")
    assert service.get_dataset(created.id, tenant_id="tenant-a", user_id="u1").id == created.id
    with pytest.raises(DomainError) as excinfo:
        service.get_dataset(created.id, tenant_id="tenant-b", user_id="u1")
    assert excinfo.value.code is ErrorCode.NOT_FOUND


# -- 用例导入 / 发布 ---------------------------------------------------------


def test_import_cases_and_publish(client: Any, auth_headers: dict[str, str]) -> None:
    """导入用例（201）→ 发布（``PUBLISHED``）。"""
    dataset = _create_dataset(client, auth_headers)
    imported = _import_cases(
        client,
        auth_headers,
        dataset["id"],
        [{"case_key": "c1", "input": {"q": 1}}, {"case_key": "c2", "input": {"q": 2}}],
    )
    assert imported.status_code == 201, imported.text
    assert [item["case_key"] for item in _data(imported)] == ["c1", "c2"]

    published = _publish(client, auth_headers, dataset["id"])
    assert published.status_code == 200, published.text
    assert _data(published)["status"] == "PUBLISHED"


def test_import_duplicate_case_key_conflicts(client: Any, auth_headers: dict[str, str]) -> None:
    """同任务集重复 ``case_key`` → ``CONFLICT``（409）。"""
    dataset = _create_dataset(client, auth_headers)
    first = _import_cases(client, auth_headers, dataset["id"], [{"case_key": "dup", "input": 1}])
    assert first.status_code == 201, first.text
    conflict = _import_cases(client, auth_headers, dataset["id"], [{"case_key": "dup", "input": 2}])
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "CONFLICT"


def test_import_cases_rejects_sensitive_plaintext(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """用例 ``input`` 含敏感明文 → ``VALIDATION_ERROR``（422）且**不泄漏明文**。"""
    dataset = _create_dataset(client, auth_headers)
    response = _import_cases(
        client, auth_headers, dataset["id"], [{"case_key": "s1", "input": {"token": _SECRET}}]
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert _SECRET not in response.text


def test_import_cases_rejects_invalid_assertions(client: Any, auth_headers: dict[str, str]) -> None:
    """非法断言 schema（未知 scorer）→ ``VALIDATION_ERROR``（422）。"""
    dataset = _create_dataset(client, auth_headers)
    response = _import_cases(
        client,
        auth_headers,
        dataset["id"],
        [
            {
                "case_key": "a1",
                "input": {"q": 1},
                "assertions": [{"scorer": "bogus", "weight": 1.0, "params": {}}],
            }
        ],
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_published_dataset_cases_are_immutable(client: Any, auth_headers: dict[str, str]) -> None:
    """发布后的任务集不可再导入用例 → ``CONFLICT``（409）。"""
    dataset_id, _cases = _seed_published_dataset(client, auth_headers)
    response = _import_cases(client, auth_headers, dataset_id, [{"case_key": "late", "input": 1}])
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "CONFLICT"


# -- 启动评测（幂等 + 逐 case 分数） -----------------------------------------


def test_start_run_is_idempotent(client: Any, auth_headers: dict[str, str]) -> None:
    """同幂等键重复启动 → 返回**同一** Run（不重复创建）。"""
    dataset_id, _cases = _seed_published_dataset(client, auth_headers)
    _inject_fake_launcher(client, _FakeLauncher())

    first = _start_run(
        client, auth_headers, dataset_id=dataset_id, agent_version_id="v1", idempotency_key="k1"
    )
    second = _start_run(
        client, auth_headers, dataset_id=dataset_id, agent_version_id="v1", idempotency_key="k1"
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert _data(first)["id"] == _data(second)["id"]


def test_get_run_returns_per_case_scores(client: Any, auth_headers: dict[str, str]) -> None:
    """评测详情返回逐 case 分数（无断言 → ``score=null`` ＝ ``N/A``）。"""
    dataset_id, cases = _seed_published_dataset(client, auth_headers)
    _inject_fake_launcher(client, _FakeLauncher())

    started = _start_run(client, auth_headers, dataset_id=dataset_id, agent_version_id="v1")
    assert started.status_code == 201, started.text
    run = _data(started)
    assert run["status"] == "SUCCESS"

    fetched = client.get(f"{_RUNS}/{run['id']}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    detail = _data(fetched)
    by_case = {item["case_id"]: item for item in detail["results"]}
    case_by_key = {item["case_key"]: item["id"] for item in cases}
    assert by_case[case_by_key["case-1"]]["score"] == 1.0
    assert by_case[case_by_key["case-2"]]["score"] is None
    # 汇总：通过率 1.0、均分 1.0（仅统计有测项）、scored=1。
    assert detail["summary"]["pass_rate"] == 1.0
    assert detail["summary"]["mean_score"] == 1.0
    assert detail["summary"]["scored"] == 1


def test_compare_two_versions(client: Any, auth_headers: dict[str, str]) -> None:
    """两 ``agent_version`` 回归对比：通过率 / 均分 / 失败 case / ``delta``。"""
    dataset_id, _cases = _seed_published_dataset(client, auth_headers)
    _inject_fake_launcher(client, _FakeLauncher(fail_versions={"v-baseline"}))

    candidate = _start_run(
        client, auth_headers, dataset_id=dataset_id, agent_version_id="v-candidate"
    )
    baseline = _start_run(
        client, auth_headers, dataset_id=dataset_id, agent_version_id="v-baseline"
    )
    assert candidate.status_code == 201 and baseline.status_code == 201, candidate.text

    report = client.get(
        f"{_RUNS}/{_data(candidate)['id']}/compare",
        headers=auth_headers,
        params={"baseline_run_id": _data(baseline)["id"]},
    )
    assert report.status_code == 200, report.text
    data = _data(report)
    assert data["agent_version_a"] == "v-baseline"
    assert data["agent_version_b"] == "v-candidate"
    assert data["pass_rate"]["a"] == 0.0
    assert data["pass_rate"]["b"] == 1.0
    assert data["pass_rate"]["delta"] == 1.0
    assert set(data["fails"]["only_a"]) == {"case-1", "case-2"}
    assert data["mean_score"]["a"] == 0.0
    assert data["mean_score"]["b"] == 1.0


def test_start_run_requires_published_dataset(client: Any, auth_headers: dict[str, str]) -> None:
    """未发布任务集启动评测 → ``CONFLICT``（409）。"""
    dataset = _create_dataset(client, auth_headers)
    _import_cases(client, auth_headers, dataset["id"], [{"case_key": "c1", "input": 1}])
    _inject_fake_launcher(client, _FakeLauncher())
    response = _start_run(client, auth_headers, dataset_id=dataset["id"], agent_version_id="v1")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "CONFLICT"


# -- 响应壳 / 权限 -----------------------------------------------------------


def test_response_shell_envelope(client: Any, auth_headers: dict[str, str]) -> None:
    """成功响应遵循统一响应壳 ``{code, message, data, request_id}``。"""
    response = client.get(_DATASETS, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"code", "message", "data", "request_id"}.issubset(body.keys())
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert response.headers.get("X-Request-Id") == body["request_id"]


def test_endpoints_require_permission(client: Any, permissionless_headers: dict[str, str]) -> None:
    """无权限用户的读 / 写 / 运行 → ``PERMISSION_DENIED``（403）。"""
    read = client.get(_DATASETS, headers=permissionless_headers)
    assert read.status_code == 403, read.text
    assert read.json()["code"] == "PERMISSION_DENIED"

    write = client.post(_DATASETS, headers=permissionless_headers, json={"name": "x"})
    assert write.status_code == 403, write.text
    assert write.json()["code"] == "PERMISSION_DENIED"

    run = _start_run(client, permissionless_headers, dataset_id="d", agent_version_id="v")
    assert run.status_code == 403, run.text
    assert run.json()["code"] == "PERMISSION_DENIED"
