"""Phase 2c 子链路端到端（W10 / T2-52；设计 §2.8 / §2.12 / §2.13 / 裁定 R-W10-01/02）。

**2c 纵切**（真实 HTTP / ``TestClient`` / 真实 SQLite；stub 驱动、确定性、**零网络 / 零 Docker**）：

    ① Workspace/Project：建 WS → 建 Project → 文件经 ``Storage`` → Git 经 ``Sandbox`` 路径；
    ② Studio：Agent 版本 / 绑定数据面（发布新版本 = 不可变快照）；
    ③ Marketplace：``export → import → export`` 往返（规范化 yaml 字节一致 + 幂等）；
    ④ Evaluation：建 dataset → 批量 Run → scorer 逐例评分 → 两版本回归对比。

驱动方式（照抄 ``tests/e2e/test_phase2b_flow.py`` + ``tests/e2e/fixtures/``）：

- 全程真实 ``create_app`` + ``TestClient``（真实中间件 / 统一响应壳
  ``{code,message,data,request_id}`` / 真实 SQLite / 真实 ``Storage`` / 真实沙箱替身）；
- 仅以**确定性替身**替换两处外部能力：文件存储（``astra_storage`` 本地实现）与沙箱
  （``FakeSandboxProvider``，零真实 git 进程）；Evaluation 逐例执行经**注入 fake launcher**
  替换组合根 bridge（同 ``tests/integration/evaluation/test_evaluation_api.py`` 口径）。

🔴 **与 T2-51 的分工**（``tests/e2e/test_phase2_flow.py``，Phase 2 总链路）**不重复**：本文只做
   **2c 五面纵切**（Workspace/Project / Studio / Marketplace / Evaluation），不覆盖 Skill/MCP/
   Workflow/Knowledge/Memory 全链路。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from astra_evaluation import RunHandle, RunOutcome
from astra_plugin.marketplace import (
    DEFAULT_CORE_VERSION,
    build_manifest,
    canonical_dump,
    manifest_to_dict,
)
from astra_storage import create_local_file_storage
from astra_workspace import build_workspace_services

from tests.e2e.fixtures.fake_sandbox import FakeSandboxProvider

# -- 端点 / 常量 -------------------------------------------------------------

_WS = "/api/v1/workspaces"
_PROJECTS = "/api/v1/projects"
_AGENTS = "/api/v1/agents"
_SKILLS = "/api/v1/skills"
_MARKETPLACE_IMPORT = "/api/v1/agent-studio/marketplace/import"
_MARKETPLACE_EXPORT = "/api/v1/agent-studio/marketplace/export"
_DATASETS = "/api/v1/evaluation/datasets"
_RUNS = "/api/v1/evaluation/runs"

#: 2c Marketplace 往返所用 Skill 包名（满足 ``NAME_PATTERN``）。
_MP_SKILL_NAME = "phase2c-mp-skill"


# -- 通用支撑 ----------------------------------------------------------------


def _data(response: Any) -> Any:  # noqa: ANN401 - fastapi ``TestClient`` response
    """从统一响应壳取 ``data``（``{code,message,data,request_id}``）。"""
    body = response.json()
    assert "data" in body, response.text
    return body["data"]


def _services(client: Any) -> Any:  # noqa: ANN401 - ``AppServices``
    """取已装配的组合根产物 ``AppServices``。"""
    return client.app.state.services


def _create_workspace(
    client: Any,  # noqa: ANN401
    headers: dict[str, str],
    name: str = "c-ws",
) -> str:
    """建一个工作区并返回其 id。"""
    response = client.post(_WS, headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return str(_data(response)["id"])


def _install_workspace_doubles(
    client: Any,  # noqa: ANN401
    storage_root: Path,
    sandbox: FakeSandboxProvider,
) -> None:
    """把本地 ``Storage`` + 沙箱替身**就地**注入 ``services.workspace``（组合根替身注入范式）。

    ``build_app_services`` 以 ``build_workspace_services(session_factory)`` 装配 → ``files`` /
    ``git`` 缺依赖时为 ``None``（文件端点 503）；此处按装配位重建，以驱动**真实** Storage /
    Sandbox 路径（对齐 ``tests/e2e/fixtures/wiring.py`` 的「就地替换」）。
    """
    services = _services(client)
    session_factory = services.providers.database.session_factory
    services.workspace = build_workspace_services(
        session_factory,
        storage=create_local_file_storage(storage_root),
        sandbox=sandbox,
    )


def _skill_package_yaml(
    *,
    name: str = _MP_SKILL_NAME,
    version: str = "1.0.0",
    instructions: str = "review the diff",
) -> str:
    """构造一个合法的 skill 市场包 yaml（清单字段 + ``resource``）。"""
    resource = {
        "name": name,
        "version": version,
        "display_name": "Phase2c Marketplace Skill",
        "description": "2c e2e demo skill",
        "category": "quality",
        "instructions": instructions,
    }
    manifest = build_manifest(
        kind="skill",
        name=name,
        version=version,
        manifest_path="skill.yaml",
        core_compat=f">={DEFAULT_CORE_VERSION}",
        author="alice",
        license="MIT",
        artifact_sha256="",
    )
    bundle = manifest_to_dict(manifest)
    bundle["resource"] = resource
    return canonical_dump(bundle)


class _FakeLauncher:
    """确定性 fake ``AgentRunLauncher``（替换组合根 bridge；照抄 Evaluation API 测试口径）。

    按 ``agent_version_id`` 决定终态 / 输出：``fail_versions`` 内的版本置 ``FAILED``（输出
    ``BAD``），否则置 ``SUCCESS`` 并输出固定文本（供 ``contains`` scorer 评分）。
    """

    def __init__(
        self,
        *,
        output_by_version: dict[str, str] | None = None,
        fail_versions: set[str] | None = None,
        default_output: str = "OK",
    ) -> None:
        """装配确定性 launcher。"""
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
        input: Any,  # noqa: ANN401 - 用例 input（任意 JSON）
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


# -- ① Workspace/Project：WS → Project → 文件经 Storage → Git 经 Sandbox --------


def test_phase2c_workspace_project_files_git(
    client: Any,  # noqa: ANN401
    auth_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    """① 建 WS → 建 Project → 文件经 ``Storage`` 往返 → ``clone`` 经 ``Sandbox``。"""
    sandbox = FakeSandboxProvider()
    _install_workspace_doubles(client, tmp_path / "ws-storage", sandbox)

    # 建工作区 + 建项目（真实 HTTP / DB）。
    ws_id = _create_workspace(client, auth_headers, name="c-ws-1")
    project = _data(
        client.post(
            _PROJECTS,
            headers=auth_headers,
            json={
                "name": "c-project",
                "workspace_id": ws_id,
                "repo_url": "https://example.com/repo.git",
                "default_branch": "main",
            },
        )
    )
    assert project["workspace_id"] == ws_id
    assert project["repo_url"] == "https://example.com/repo.git"

    # 项目详情 / 列表经真实 HTTP 读回。
    fetched = client.get(f"{_PROJECTS}/{project['id']}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert _data(fetched)["id"] == project["id"]
    listed = _data(client.get(_PROJECTS, headers=auth_headers, params={"workspace_id": ws_id}))
    assert [item["id"] for item in listed] == [project["id"]]

    # 文件经 Storage 写入（经真实 ``FileService``），再经真实 HTTP 读回。
    files = _services(client).workspace.files
    assert files is not None
    files.put(
        workspace_id=ws_id,
        path="README.md",
        data=b"# phase2c",
        content_type="text/markdown",
    )

    objects = _data(client.get(f"{_WS}/{ws_id}/files", headers=auth_headers))
    assert [obj["key"] for obj in objects] == [f"workspaces/{ws_id}/README.md"]

    content = _data(
        client.get(
            f"{_WS}/{ws_id}/files/content",
            headers=auth_headers,
            params={"path": "README.md"},
        )
    )
    assert content["encoding"] == "base64"
    assert base64.b64decode(content["content_base64"]) == b"# phase2c"

    # Git 经 Sandbox 路径：``clone`` 的每条命令均经 ``SandboxProvider.exec``。
    outcome = _services(client).workspace.projects.clone(
        tenant_id=project["tenant_id"], project_id=project["id"], base_ref="main"
    )
    assert outcome.result is not None and outcome.result.ok
    assert any(cmd[:2] == ["git", "clone"] for cmd in sandbox.commands), sandbox.commands
    assert ["git", "checkout", "main"] in sandbox.commands
    assert all(cmd and cmd[0] == "git" for cmd in sandbox.commands), sandbox.commands
    assert sandbox.created == 1 and sandbox.destroyed == 1


def test_phase2c_files_unwired_returns_503(
    client: Any,  # noqa: ANN401
    auth_headers: dict[str, str],
) -> None:
    """① 兜底：缺 ``Storage`` 装配的文件端点 → 结构化 ``503 DEPENDENCY_MISSING``。"""
    ws_id = _create_workspace(client, auth_headers, name="c-ws-503")
    response = client.get(f"{_WS}/{ws_id}/files", headers=auth_headers)
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "DEPENDENCY_MISSING"


# -- ② Studio：Agent 版本 / 绑定数据面 ---------------------------------------


def test_phase2c_studio_agent_versions_binding(
    client: Any,  # noqa: ANN401
    auth_headers: dict[str, str],
) -> None:
    """② 建 Agent → 发布版本（不可变快照）→ 版本列表数据面追加，历史不覆盖。"""
    agent = _data(client.post(_AGENTS, headers=auth_headers, json={"name": "c-studio-agent"}))
    agent_id = str(agent["id"])

    publish = client.post(
        f"{_AGENTS}/{agent_id}/publish",
        headers=auth_headers,
        json={"system_prompt": "SP-v1", "model_config": {"model": "gpt-4o-mini"}, "version": "v1"},
    )
    assert publish.status_code == 201, publish.text
    first = _data(publish)
    assert first["version"] == "v1"
    assert first["system_prompt"] == "SP-v1"

    # 版本列表数据面（Studio AgentVersions）：含 v1 快照。
    versions = _data(client.get(f"{_AGENTS}/{agent_id}/versions", headers=auth_headers))
    assert any(item["version"] == "v1" and item["system_prompt"] == "SP-v1" for item in versions)

    # 再发布 v2 → 列表追加（不可变：v1 仍在，不被覆盖）。
    second = client.post(
        f"{_AGENTS}/{agent_id}/publish",
        headers=auth_headers,
        json={"system_prompt": "SP-v2", "version": "v2"},
    )
    assert second.status_code == 201, second.text
    versions = _data(client.get(f"{_AGENTS}/{agent_id}/versions", headers=auth_headers))
    assert {item["version"] for item in versions} >= {"v1", "v2"}
    by_version = {item["version"]: item for item in versions}
    assert by_version["v1"]["system_prompt"] == "SP-v1"
    assert by_version["v2"]["system_prompt"] == "SP-v2"


# -- ③ Marketplace：export → import → export 往返 -----------------------------


def test_phase2c_marketplace_export_import_export_roundtrip(
    client: Any,  # noqa: ANN401
    auth_headers: dict[str, str],
) -> None:
    """③ 导入包 → 导出资 → 再导入该导出 → 再导出：规范化 yaml + 摘要**字节一致**（幂等）。"""
    imported = client.post(
        _MARKETPLACE_IMPORT,
        headers=auth_headers,
        json={"package_yaml": _skill_package_yaml(), "confirm": True},
    )
    assert imported.status_code == 200, imported.text
    result = _data(imported)
    assert result["status"] == "IMPORTED"
    assert result["name"] == _MP_SKILL_NAME

    skill_id = next(
        item["id"]
        for item in _data(client.get(_SKILLS, headers=auth_headers))
        if item["name"] == _MP_SKILL_NAME
    )

    exported_1 = _data(
        client.get(
            _MARKETPLACE_EXPORT,
            headers=auth_headers,
            params={"kind": "skill", "id": skill_id},
        )
    )
    yaml_1, digest_1 = exported_1["yaml"], exported_1["digest"]
    assert yaml_1.endswith("\n") and not yaml_1.endswith("\n\n")
    assert f"name: {_MP_SKILL_NAME}" in yaml_1

    # 再导入导出的 yaml → 同摘要幂等（不重复建资源）。
    reimported = client.post(
        _MARKETPLACE_IMPORT,
        headers=auth_headers,
        json={"package_yaml": yaml_1, "confirm": True},
    )
    assert reimported.status_code == 200, reimported.text
    assert _data(reimported)["digest"] == digest_1

    # 再导出 → 与首次**字节一致**（往返等价）。
    exported_2 = _data(
        client.get(
            _MARKETPLACE_EXPORT,
            headers=auth_headers,
            params={"kind": "skill", "id": skill_id},
        )
    )
    assert exported_2["yaml"] == yaml_1
    assert exported_2["digest"] == digest_1

    names = [item["name"] for item in _data(client.get(_SKILLS, headers=auth_headers))]
    assert names.count(_MP_SKILL_NAME) == 1


# -- ④ Evaluation：dataset → 批量 Run → scorer → 对比 ------------------------


def _contains_ok() -> dict[str, Any]:
    """``contains`` 断言（期望输出含 ``OK``）。"""
    return {"scorer": "contains", "weight": 1.0, "params": {"values": ["OK"]}}


def test_phase2c_evaluation_dataset_run_scorer_compare(
    client: Any,  # noqa: ANN401
    auth_headers: dict[str, str],
) -> None:
    """④ 建 dataset → 导用例（scorer）→ 发布 → 批量 Run（逐例评分）→ 两版本对比。"""
    _services(client).evaluation.runner.launcher = _FakeLauncher(fail_versions={"v-baseline"})

    dataset = _data(client.post(_DATASETS, headers=auth_headers, json={"name": "c-dataset"}))
    assert dataset["status"] == "DRAFT"

    cases = [
        {"case_key": "case-1", "input": {"q": "hello"}, "assertions": [_contains_ok()]},
        {"case_key": "case-2", "input": {"q": "world"}},
    ]
    imported = client.post(
        f"{_DATASETS}/{dataset['id']}/cases", headers=auth_headers, json={"cases": cases}
    )
    assert imported.status_code == 201, imported.text
    case_ids = {item["case_key"]: item["id"] for item in _data(imported)}

    assert (
        client.post(f"{_DATASETS}/{dataset['id']}/publish", headers=auth_headers).status_code == 200
    )

    def _start(version: str) -> dict[str, Any]:
        """启动一次批量评测（返回 Run 视图）。"""
        response = client.post(
            _RUNS,
            headers=auth_headers,
            json={"dataset_id": dataset["id"], "agent_id": "agent-1", "agent_version_id": version},
        )
        assert response.status_code == 201, response.text
        return _data(response)

    candidate = _start("v-candidate")
    baseline = _start("v-baseline")

    # 逐 case 分数：case-1 命中 contains → 1.0；case-2 无断言 → None（N/A）。
    detail = _data(client.get(f"{_RUNS}/{candidate['id']}", headers=auth_headers))
    assert detail["status"] == "SUCCESS"
    by_case = {item["case_id"]: item for item in detail["results"]}
    assert by_case[case_ids["case-1"]]["score"] == 1.0
    assert by_case[case_ids["case-2"]]["score"] is None
    assert detail["summary"]["pass_rate"] == 1.0

    # 两版本回归对比：baseline 全 FAILED（输出 BAD）→ 通过率 0；candidate 1；delta 1。
    report = _data(
        client.get(
            f"{_RUNS}/{candidate['id']}/compare",
            headers=auth_headers,
            params={"baseline_run_id": baseline["id"]},
        )
    )
    assert report["agent_version_a"] == "v-baseline"
    assert report["agent_version_b"] == "v-candidate"
    assert report["pass_rate"]["a"] == 0.0
    assert report["pass_rate"]["b"] == 1.0
    assert report["pass_rate"]["delta"] == 1.0
    assert set(report["fails"]["only_a"]) == {"case-1", "case-2"}
