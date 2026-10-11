import { api } from "@/lib/api";
import type {
  AddCaseRequest,
  CaseOut,
  CompareReport,
  CreateDatasetRequest,
  DatasetDetailResponse,
  DatasetListResponse,
  DatasetOut,
  RunDetailResponse,
  RunOut,
  StartRunRequest,
} from "@/types";

/**
 * Evaluation 服务（`/evaluation/*` API，W9 / T2-47；设计 §2.13.2；裁定 §2.3 / §5.5）。
 *
 * - **任务集管理**：列表 / 新建 / 详情（含用例）/ 追加用例 / 发布（`PUBLISHED`）；
 * - **批量执行**：启动 `Run`（**幂等**——`idempotency_key` 命中唯一索引返回既有 Run）；
 * - **回归对比**：`compare`（给定 Run 与 baseline Run，返回 `CompareReport`）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 * 🔴 基址 `/api/v1`（`lib/api.ts`）；`data` 即业务体（`{items}` / `{dataset,cases}` / `{run,results}`）。
 */
export const evaluationService = {
  /** 数据集列表（可选按 `workspace_id` 过滤）。 */
  listDatasets(workspaceId?: string | null): Promise<DatasetListResponse> {
    return api
      .get<DatasetListResponse>("/evaluation/datasets", {
        params: workspaceId ? { workspace_id: workspaceId } : undefined,
      })
      .then((r) => r.data);
  },

  /** 新建数据集（初始 `DRAFT`）。 */
  createDataset(payload: CreateDatasetRequest): Promise<DatasetOut> {
    return api.post<DatasetOut>("/evaluation/datasets", payload).then((r) => r.data);
  },

  /** 数据集详情（含用例数组）。 */
  getDataset(datasetId: string): Promise<DatasetDetailResponse> {
    return api.get<DatasetDetailResponse>(`/evaluation/datasets/${datasetId}`).then((r) => r.data);
  },

  /** 向数据集追加用例（`PUBLISHED` 数据集不可追加——由后端守卫）。 */
  addCase(datasetId: string, payload: AddCaseRequest): Promise<CaseOut> {
    return api
      .post<CaseOut>(`/evaluation/datasets/${datasetId}/cases`, payload)
      .then((r) => r.data);
  },

  /** 发布数据集（`DRAFT` → `PUBLISHED`；发布后用例不可修改）。 */
  publishDataset(datasetId: string): Promise<DatasetOut> {
    return api.post<DatasetOut>(`/evaluation/datasets/${datasetId}/publish`).then((r) => r.data);
  },

  /** 启动评测运行（固定 `dataset` + `agent_version`，幂等）。 */
  startRun(payload: StartRunRequest): Promise<RunOut> {
    return api.post<RunOut>("/evaluation/runs", payload).then((r) => r.data);
  },

  /** 运行详情（含逐例结果）。 */
  getRun(runId: string): Promise<RunDetailResponse> {
    return api.get<RunDetailResponse>(`/evaluation/runs/${runId}`).then((r) => r.data);
  },

  /** 回归对比（当前 Run 为 B；`baselineRunId` 为 A）。 */
  compare(runId: string, baselineRunId: string): Promise<CompareReport> {
    return api
      .get<CompareReport>(`/evaluation/runs/${runId}/compare`, {
        params: { baseline_run_id: baselineRunId },
      })
      .then((r) => r.data);
  },
};
