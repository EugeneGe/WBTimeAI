"""``EvaluationService``——Evaluation 用例编排器（W9 / T2-47；设计 §2.13.2 / 裁定 R1 / R6）。

**应用/用例层（第三类）**：编排「任务集 / 用例 CRUD、发布、启动批量评测、回归对比」，
**不**承载实体持久化、**不**提供被 Runtime 消费的 Protocol、**零** Web / ORM
（``test_application_import_boundary`` 强制）。

- :meth:`list_datasets` / :meth:`get_dataset` / :meth:`create_dataset`：任务集用例（三维过滤）；
- :meth:`import_cases` / :meth:`publish_dataset`：用例导入（**schema + 敏感扫描**）与发布
  （``PUBLISHED`` 后用例不可修改；需改则克隆新版本）；
- :meth:`start_run`：**幂等**启动批量评测（固定 ``dataset`` / ``agent_version`` 版本），
  经注入的 :class:`~astra_evaluation.EvaluationRunner` **同步**逐例执行（复用正式 Runtime）；
- :meth:`get_run`：评测详情（含逐 case 结果）；
- :meth:`compare`：同一任务集下两 ``agent_version`` 的回归对比（缺失指标 ``N/A``）。

🔴 依赖 ``astra_evaluation``（能力包 Protocol / 实体 / runner / compare）——
**新边 application→evaluation**（R1）；逐例 ``agent_run`` 创建经**注入** ``AgentRunLauncher``
（真实 bridge 落组合根），故本服务对 Runtime **松耦合**、可注入 fake 单测。敏感扫描**复用**
``astra_plugin.marketplace.scan_sensitive``（既有 application→plugin 边，W8/R4）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode, PermissionDeniedError
from astra_domain import ScopeFilter
from astra_evaluation import (
    DATASET_STATUS_DRAFT,
    DEFAULT_DATASET_VERSION,
    RUN_STATUS_QUEUED,
    EvaluationCase,
    EvaluationCaseRepository,
    EvaluationDataset,
    EvaluationDatasetRepository,
    EvaluationResultRepository,
    EvaluationRunner,
    EvaluationRunRepository,
    compare_runs,
    validate_assertions,
)
from astra_evaluation import EvaluationRun as EvaluationRunEntity
from astra_plugin.marketplace import scan_sensitive

from ..dto.evaluation import (
    EvaluationCaseDTO,
    EvaluationCompareReportDTO,
    EvaluationDatasetDTO,
    EvaluationResultDTO,
    EvaluationRunDTO,
)
from .base import ApplicationService

__all__ = [
    "ACTION_READ",
    "ACTION_WRITE",
    "ACTION_RUN",
    "EvaluationPermissionChecker",
    "EvaluationService",
]

#: 读取权限码（列表 / 详情 / 对比）。
ACTION_READ = "evaluation:read"

#: 写入权限码（建任务集 / 导入用例 / 发布）。
ACTION_WRITE = "evaluation:write"

#: 运行权限码（启动批量评测）。
ACTION_RUN = "evaluation:run"


@runtime_checkable
class EvaluationPermissionChecker(Protocol):
    """Evaluation 权限判定（组合根注入；结构化满足即可）。"""

    def can(self, user_id: str, permission: str) -> bool:
        """判定用户是否具备某权限码。"""
        ...


class EvaluationService(ApplicationService):
    """Evaluation 用例编排器（DI 注入四仓储 + runner + 可选权限判定；零 ORM）。"""

    datasets: EvaluationDatasetRepository
    cases: EvaluationCaseRepository
    runs: EvaluationRunRepository
    results: EvaluationResultRepository
    runner: EvaluationRunner
    permission: EvaluationPermissionChecker | None

    def __init__(
        self,
        *,
        datasets: EvaluationDatasetRepository,
        cases: EvaluationCaseRepository,
        runs: EvaluationRunRepository,
        results: EvaluationResultRepository,
        runner: EvaluationRunner,
        permission: EvaluationPermissionChecker | None = None,
    ) -> None:
        """装配用例编排器（依赖由**组合根**注入）。

        Args:
            datasets / cases / runs / results: 四仓储（能力包 Protocol）。
            runner: 批量评测执行器（内部持有注入的 ``AgentRunLauncher``）。
            permission: 权限判定（可选；``None`` → 不额外校验，权限由 Router 守卫兜底）。
        """
        super().__init__(
            datasets=datasets,
            cases=cases,
            runs=runs,
            results=results,
            runner=runner,
            permission=permission,
        )

    # -- 任务集 --------------------------------------------------------------

    def list_datasets(
        self,
        *,
        tenant_id: str,
        user_id: str,
        organization_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[EvaluationDatasetDTO]:
        """列出范围内任务集（``ScopeFilter`` 租户 / 组织 / 工作区三维过滤）。"""
        self._require(user_id, ACTION_READ)
        scope = ScopeFilter(
            tenant_id=tenant_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        return [EvaluationDatasetDTO.from_entity(item) for item in self.datasets.list(scope)]

    def get_dataset(self, dataset_id: str, *, tenant_id: str, user_id: str) -> EvaluationDatasetDTO:
        """返回某任务集 DTO（跨租户 / 不存在 → ``NOT_FOUND``）。"""
        self._require(user_id, ACTION_READ)
        return EvaluationDatasetDTO.from_entity(self._require_dataset(dataset_id, tenant_id))

    def create_dataset(
        self,
        *,
        tenant_id: str,
        user_id: str,
        name: str,
        description: str | None = None,
        workspace_id: str | None = None,
        organization_id: str | None = None,
    ) -> EvaluationDatasetDTO:
        """创建任务集（``status=DRAFT``、``version=1``）。

        Raises:
            DomainError: 名称为空（``VALIDATION_ERROR``）；权限不足（``PERMISSION_DENIED``）。
        """
        self._require(user_id, ACTION_WRITE)
        if not str(name).strip():
            raise DomainError(
                "任务集名称不得为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "name"},
            )
        dataset = EvaluationDataset(
            tenant_id=tenant_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=str(name),
            version=DEFAULT_DATASET_VERSION,
            status=DATASET_STATUS_DRAFT,
            description=description,
            created_by=user_id,
        )
        dataset.assert_valid()
        return EvaluationDatasetDTO.from_entity(self.datasets.add(dataset))

    # -- 用例（导入 + 发布） --------------------------------------------------

    def import_cases(
        self,
        dataset_id: str,
        *,
        tenant_id: str,
        user_id: str,
        cases: Sequence[EvaluationCaseDTO],
    ) -> list[EvaluationCaseDTO]:
        """导入用例（**schema 校验 + 敏感扫描**；``(dataset_id, case_key)`` 唯一）。

        Args:
            dataset_id: 目标任务集标识。
            tenant_id / user_id: 主体与租户标识。
            cases: 待导入用例（``case_key`` / ``input`` / ``expected`` / ``assertions`` /
                ``tags`` / ``position``）。

        Returns:
            已落库用例 DTO 列表。

        Raises:
            DomainError: 任务集不存在 / 跨租户（``NOT_FOUND``）；已发布数据集的用例不可修改
                （``CONFLICT``）；``case_key`` 缺失 / 重复（``VALIDATION_ERROR`` / ``CONFLICT``）；
                断言 schema 非法 / 敏感明文命中（``VALIDATION_ERROR``）；权限不足
                （``PERMISSION_DENIED``）。
        """
        self._require(user_id, ACTION_WRITE)
        dataset = self._require_dataset(dataset_id, tenant_id)
        if dataset.is_published():
            raise DomainError(
                "已发布任务集的用例不可修改（需改请克隆新版本）",
                code=ErrorCode.CONFLICT,
                data={"dataset_id": dataset.id, "status": dataset.status},
            )

        created: list[EvaluationCase] = []
        for index, spec in enumerate(cases):
            case_key = str(spec.case_key or "").strip()
            if not case_key:
                raise DomainError(
                    "用例缺少 case_key",
                    code=ErrorCode.VALIDATION_ERROR,
                    data={"field": "case_key", "index": index},
                )
            if self.cases.get_by_key(dataset.id, case_key) is not None:
                raise DomainError(
                    "用例 case_key 在同任务集内重复",
                    code=ErrorCode.CONFLICT,
                    data={"reason": "duplicate_case_key", "case_key": case_key},
                )
            assertions = list(spec.assertions or [])
            validate_assertions(assertions)
            scan_sensitive(spec.input)
            if spec.expected is not None:
                scan_sensitive(spec.expected)
            entity = EvaluationCase(
                dataset_id=dataset.id,
                case_key=case_key,
                input=spec.input,
                expected=spec.expected,
                assertions=assertions,
                tags=list(spec.tags) if spec.tags is not None else None,
                position=int(spec.position) if spec.position else index,
            )
            created.append(self.cases.add(entity))
        return [EvaluationCaseDTO.from_entity(item) for item in created]

    def publish_dataset(
        self, dataset_id: str, *, tenant_id: str, user_id: str
    ) -> EvaluationDatasetDTO:
        """发布任务集（``status=PUBLISHED``；用例从此不可修改；**幂等**）。

        Raises:
            DomainError: 任务集不存在 / 跨租户（``NOT_FOUND``）；权限不足（``PERMISSION_DENIED``）。
        """
        self._require(user_id, ACTION_WRITE)
        dataset = self._require_dataset(dataset_id, tenant_id)
        if dataset.is_published():
            return EvaluationDatasetDTO.from_entity(dataset)
        dataset.publish()
        return EvaluationDatasetDTO.from_entity(self.datasets.update(dataset))

    # -- 批量评测（幂等启动 + 同步执行） --------------------------------------

    def start_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        dataset_id: str,
        agent_id: str,
        agent_version_id: str,
        idempotency_key: str | None = None,
        organization_id: str | None = None,
        workspace_id: str | None = None,
    ) -> EvaluationRunDTO:
        """**幂等**启动一次批量评测并**同步**执行至终态。

        - 幂等键 = 显式 ``idempotency_key`` 或确定性生成
          ``f"{dataset_id}:{agent_version_id}:{scope_key}"``；
          **重复请求返回既有 Run**（不重复创建）；
        - 固定 ``dataset_id``（须 ``PUBLISHED``）与 ``agent_version_id``（可重放）；
        - 逐例 ``agent_run`` 经注入 ``AgentRunLauncher`` 创建（复用正式 Runtime / 权限 / Sandbox）。

        Raises:
            DomainError: 任务集不存在 / 跨租户（``NOT_FOUND``）；任务集未发布（``CONFLICT``）；
                ``agent_id`` / ``agent_version_id`` 缺失（``VALIDATION_ERROR``）；权限不足
                （``PERMISSION_DENIED``）。
        """
        self._require(user_id, ACTION_RUN)
        if not str(agent_id).strip() or not str(agent_version_id).strip():
            raise DomainError(
                "启动评测需明确 agent_id 与 agent_version_id",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "agent_version_id"},
            )
        dataset = self._require_dataset(dataset_id, tenant_id)
        if not dataset.is_published():
            raise DomainError(
                "任务集未发布，不能启动评测",
                code=ErrorCode.CONFLICT,
                data={"dataset_id": dataset.id, "status": dataset.status},
            )

        key = idempotency_key or self._default_idempotency_key(
            dataset.id, agent_version_id, workspace_id or organization_id
        )
        existing = self.runs.get_by_idempotency_key(key)
        if existing is not None:
            return EvaluationRunDTO.from_entity(existing)

        run = EvaluationRunEntity(
            tenant_id=tenant_id,
            organization_id=organization_id or dataset.organization_id,
            workspace_id=workspace_id or dataset.workspace_id,
            dataset_id=dataset.id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            status=RUN_STATUS_QUEUED,
            idempotency_key=key,
            created_by=user_id,
        )
        run.assert_valid()
        run = self.runs.add(run)
        final = self.runner.run(run.id)
        dto = EvaluationRunDTO.from_entity(final)
        dto.results = [
            EvaluationResultDTO.from_entity(item) for item in self.results.list_by_run(final.id)
        ]
        return dto

    def get_run(self, run_id: str, *, tenant_id: str, user_id: str) -> EvaluationRunDTO:
        """返回某评测 DTO（**含逐 case 结果**；跨租户 / 不存在 → ``NOT_FOUND``）。"""
        self._require(user_id, ACTION_READ)
        run = self._require_run(run_id, tenant_id)
        dto = EvaluationRunDTO.from_entity(run)
        dto.results = [
            EvaluationResultDTO.from_entity(item) for item in self.results.list_by_run(run.id)
        ]
        return dto

    # -- 回归对比 ------------------------------------------------------------

    def compare(
        self,
        *,
        tenant_id: str,
        user_id: str,
        run_id: str,
        baseline_run_id: str,
    ) -> EvaluationCompareReportDTO:
        """对比同一任务集下的基线（``baseline_run_id``）与候选（``run_id``）。

        Raises:
            DomainError: 评测不存在 / 跨租户（``NOT_FOUND``）；两评测不属于同一任务集
                （``VALIDATION_ERROR``）；权限不足（``PERMISSION_DENIED``）。
        """
        self._require(user_id, ACTION_READ)
        candidate = self._require_run(run_id, tenant_id)
        baseline = self._require_run(baseline_run_id, tenant_id)
        dataset = self._require_dataset(candidate.dataset_id, tenant_id)
        report = compare_runs(
            dataset=dataset,
            baseline=baseline,
            candidate=candidate,
            baseline_results=self.results.list_by_run(baseline.id),
            candidate_results=self.results.list_by_run(candidate.id),
            cases=self.cases.list_by_dataset(dataset.id),
        )
        return EvaluationCompareReportDTO.from_report(report)

    # -- 内部 ----------------------------------------------------------------

    @staticmethod
    def _default_idempotency_key(
        dataset_id: str, agent_version_id: str, scope_key: str | None
    ) -> str:
        """确定性幂等键（设计 §4.4）：``"{dataset_id}:{agent_version_id}:{scope_key}"``。"""
        return f"{dataset_id}:{agent_version_id}:{scope_key or ''}"

    def _require_dataset(self, dataset_id: str, tenant_id: str) -> EvaluationDataset:
        """加载任务集并校验租户归属（不存在 / 跨租户 → ``NOT_FOUND``）。"""
        dataset = self.datasets.get(dataset_id)
        if dataset is None or (tenant_id and dataset.tenant_id != tenant_id):
            raise DomainError(
                "任务集不存在",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "dataset_not_found", "dataset_id": dataset_id},
            )
        return dataset

    def _require_run(self, run_id: str, tenant_id: str) -> EvaluationRunEntity:
        """加载评测并校验租户归属（不存在 / 跨租户 → ``NOT_FOUND``）。"""
        run = self.runs.get(run_id)
        if run is None or (tenant_id and run.tenant_id != tenant_id):
            raise DomainError(
                "评测不存在",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "evaluation_run_not_found", "evaluation_run_id": run_id},
            )
        return run

    def _require(self, user_id: str, action: str) -> None:
        """权限守卫（未注入判定器 → 放行，权限由 Router 依赖兜底）。

        Raises:
            PermissionDeniedError: 判定器存在且拒绝（``PERMISSION_DENIED``）。
        """
        if self.permission is None:
            return
        if not self.permission.can(user_id, action):
            raise PermissionDeniedError(f"缺少权限：{action}", data={"permission": action})
