"""``/evaluation`` 路由（W9 / T2-47；设计 §2.13.2 / 裁定 R1 / R6）。

端点：

- ``GET  /evaluation/datasets``：任务集列表（``organization_id`` / ``workspace_id`` 可空过滤）；
- ``POST /evaluation/datasets``：创建任务集（``DRAFT``）；
- ``GET  /evaluation/datasets/{id}``：任务集详情；
- ``POST /evaluation/datasets/{id}/cases``：导入用例（**schema + 敏感扫描**）；
- ``POST /evaluation/datasets/{id}/publish``：发布任务集（``PUBLISHED``，用例从此不可修改）；
- ``POST /evaluation/runs``：**幂等**启动批量评测（同步执行至终态）；
- ``GET  /evaluation/runs/{id}``：评测详情（含逐 case 分数）；
- ``GET  /evaluation/runs/{id}/compare?baseline_run_id=``：两 ``agent_version`` 回归对比。

Router **只**依赖 ``AppServices``（N-8）：**不** import ``astra_evaluation`` / ``astra_database`` /
``sqlalchemy`` / ``astra_runtime``（``test_api_routers_have_no_orm_dependency``）；编排全部经
``services.evaluation``（应用层 ``EvaluationService``）。**统一响应壳**
``{code,data,message,request_id}`` 由中间件注入（本 Router 只返回模型）。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from astra_application.dto import UserDTO
from astra_application.dto.evaluation import EvaluationCaseDTO
from fastapi import APIRouter, Depends, Query

from astra_api.dependencies.auth import require_permission
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.evaluation import (
    CaseOut,
    CompareReport,
    CreateDatasetRequest,
    DatasetOut,
    ImportCasesRequest,
    RunOut,
    StartRunRequest,
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

#: 权限码（与 ``EvaluationService`` 动作码同口径）。
_PERMISSION_READ = "evaluation:read"
_PERMISSION_WRITE = "evaluation:write"
_PERMISSION_RUN = "evaluation:run"


def _tenant_id(user: UserDTO) -> str:
    """取当前用户租户标识。"""
    return user.tenant_id or ""


@router.get(
    "/datasets",
    response_model=list[DatasetOut],
    summary="任务集列表",
)
def list_datasets(
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_READ))],
    services: Annotated[AppServices, Depends(get_app_services)],
    organization_id: Annotated[str | None, Query()] = None,
    workspace_id: Annotated[str | None, Query()] = None,
) -> list[DatasetOut]:
    """列出范围内任务集（租户 / 组织 / 工作区三维过滤）。"""
    dtos = services.evaluation.list_datasets(
        tenant_id=_tenant_id(user),
        user_id=user.id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return [DatasetOut(**asdict(dto)) for dto in dtos]


@router.post(
    "/datasets",
    response_model=DatasetOut,
    status_code=201,
    summary="创建任务集",
)
def create_dataset(
    payload: CreateDatasetRequest,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_WRITE))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> DatasetOut:
    """创建一个任务集（``status=DRAFT``、``version=1``）。"""
    dto = services.evaluation.create_dataset(
        tenant_id=_tenant_id(user),
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        workspace_id=payload.workspace_id,
        organization_id=payload.organization_id,
    )
    return DatasetOut(**asdict(dto))


@router.get(
    "/datasets/{dataset_id}",
    response_model=DatasetOut,
    summary="任务集详情",
)
def get_dataset(
    dataset_id: str,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_READ))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> DatasetOut:
    """按 id 获取任务集（跨租户 / 不存在 → 404）。"""
    dto = services.evaluation.get_dataset(dataset_id, tenant_id=_tenant_id(user), user_id=user.id)
    return DatasetOut(**asdict(dto))


@router.post(
    "/datasets/{dataset_id}/cases",
    response_model=list[CaseOut],
    status_code=201,
    summary="导入用例",
)
def import_cases(
    dataset_id: str,
    payload: ImportCasesRequest,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_WRITE))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[CaseOut]:
    """导入用例（**schema 校验 + 敏感扫描**；已发布任务集 → 409）。"""
    specs = [
        EvaluationCaseDTO(
            case_key=item.case_key,
            input=item.input,
            expected=item.expected,
            assertions=list(item.assertions),
            tags=item.tags,
            position=item.position,
        )
        for item in payload.cases
    ]
    dtos = services.evaluation.import_cases(
        dataset_id, tenant_id=_tenant_id(user), user_id=user.id, cases=specs
    )
    return [CaseOut(**asdict(dto)) for dto in dtos]


@router.post(
    "/datasets/{dataset_id}/publish",
    response_model=DatasetOut,
    summary="发布任务集",
)
def publish_dataset(
    dataset_id: str,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_WRITE))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> DatasetOut:
    """发布任务集（``status=PUBLISHED``；用例从此不可修改；幂等）。"""
    dto = services.evaluation.publish_dataset(
        dataset_id, tenant_id=_tenant_id(user), user_id=user.id
    )
    return DatasetOut(**asdict(dto))


@router.post(
    "/runs",
    response_model=RunOut,
    status_code=201,
    summary="启动批量评测（幂等）",
)
def start_run(
    payload: StartRunRequest,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_RUN))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> RunOut:
    """**幂等**启动一次批量评测（重复请求返回既有 Run），同步执行至终态。"""
    dto = services.evaluation.start_run(
        tenant_id=_tenant_id(user),
        user_id=user.id,
        dataset_id=payload.dataset_id,
        agent_id=payload.agent_id,
        agent_version_id=payload.agent_version_id,
        idempotency_key=payload.idempotency_key,
        organization_id=payload.organization_id,
        workspace_id=payload.workspace_id,
    )
    return RunOut(**asdict(dto))


@router.get(
    "/runs/{run_id}",
    response_model=RunOut,
    summary="评测详情",
)
def get_run(
    run_id: str,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_READ))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> RunOut:
    """按 id 获取评测（含逐 case 结果；跨租户 / 不存在 → 404）。"""
    dto = services.evaluation.get_run(run_id, tenant_id=_tenant_id(user), user_id=user.id)
    return RunOut(**asdict(dto))


@router.get(
    "/runs/{run_id}/compare",
    response_model=CompareReport,
    summary="两版本回归对比",
)
def compare_runs(
    run_id: str,
    baseline_run_id: str,
    user: Annotated[UserDTO, Depends(require_permission(_PERMISSION_READ))],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> CompareReport:
    """对比同一任务集下的基线（``baseline_run_id``）与候选（``run_id``）。"""
    dto = services.evaluation.compare(
        tenant_id=_tenant_id(user),
        user_id=user.id,
        run_id=run_id,
        baseline_run_id=baseline_run_id,
    )
    return CompareReport(**asdict(dto))
