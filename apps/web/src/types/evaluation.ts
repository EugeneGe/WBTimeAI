/**
 * Phase 2c / W9（T2-47）：Evaluation 前端 DTO（设计 §2.13.2；裁定 §2.3 / §5.5 / R11）。
 *
 * 与后端 `apps/api/src/astra_api/schemas/evaluation.py` **逐字对齐**；统一响应壳由
 * `lib/api.ts` 拦截器解壳，服务层直接拿到业务 DTO（`data` 即业务体）。
 *
 * 🔴 字段一律 **snake_case**（与后端契约逐字一致）。
 * 🔴 回归对比各指标为 `{a, b, delta}`；**缺失为 `null` → 页面渲染 `N/A`（不得视为 0）**。
 */

// -- 词表（↔ 后端 `String(50)` 词表列；无 DB enum） ---------------------------

/** 数据集状态词表（`evaluation_dataset.status`）。 */
export type DatasetStatus = "DRAFT" | "PUBLISHED" | "ARCHIVED";

/** 数据集状态词表（有序，供渲染）。 */
export const DATASET_STATUSES: readonly DatasetStatus[] = [
  "DRAFT",
  "PUBLISHED",
  "ARCHIVED",
] as const;

/** 评测运行状态词表（`evaluation_run.status`）。 */
export type RunStatus = "QUEUED" | "RUNNING" | "SUCCESS" | "FAILED" | "CANCELLED";

/** 评测运行状态词表（有序，供渲染）。 */
export const RUN_STATUSES: readonly RunStatus[] = [
  "QUEUED",
  "RUNNING",
  "SUCCESS",
  "FAILED",
  "CANCELLED",
] as const;

/** 单例结果状态词表（`evaluation_result.status`）。 */
export type ResultStatus = "SUCCESS" | "FAILED" | "CANCELLED";

// -- DTO ---------------------------------------------------------------------

/** 数据集响应（`DatasetOut`）。 */
export interface DatasetOut {
  id: string;
  name: string;
  version: number;
  parent_dataset_id: string | null;
  status: DatasetStatus;
  description: string | null;
  created_by: string | null;
  workspace_id: string | null;
  created_at: string;
  updated_at: string;
}

/** 用例响应（`CaseOut`）。 */
export interface CaseOut {
  id: string;
  dataset_id: string;
  case_key: string;
  input: unknown;
  expected: unknown | null;
  assertions: unknown;
  tags: unknown | null;
  position: number;
}

/** 评测运行响应（`RunOut`）。 */
export interface RunOut {
  id: string;
  dataset_id: string;
  agent_id: string;
  agent_version_id: string;
  status: RunStatus;
  idempotency_key: string | null;
  started_at: string | null;
  completed_at: string | null;
  summary: unknown | null;
  created_at: string;
  updated_at: string;
}

/** 逐例结果响应（`ResultOut`）。 */
export interface ResultOut {
  id: string;
  evaluation_run_id: string;
  case_id: string;
  agent_run_id: string | null;
  status: ResultStatus;
  score: number | null;
  assertion_results: unknown | null;
  duration_ms: number | null;
  token_usage: unknown | null;
  cost: number | null;
  error_type: string | null;
}

// -- 请求 DTO ----------------------------------------------------------------

/** 创建数据集请求（`POST /evaluation/datasets`）。 */
export interface CreateDatasetRequest {
  name: string;
  description?: string | null;
  workspace_id?: string | null;
}

/** 追加用例请求（`POST /evaluation/datasets/{id}/cases`）。 */
export interface AddCaseRequest {
  case_key: string;
  input: unknown;
  expected?: unknown | null;
  assertions?: unknown;
  tags?: string[] | null;
  position?: number;
}

/** 启动评测运行请求（`POST /evaluation/runs`，幂等）。 */
export interface StartRunRequest {
  dataset_id: string;
  agent_id: string;
  agent_version_id: string;
  idempotency_key?: string | null;
}

// -- 组合响应 ----------------------------------------------------------------

/** 数据集列表响应（`GET /evaluation/datasets`）。 */
export interface DatasetListResponse {
  items: DatasetOut[];
}

/** 数据集详情响应（`GET /evaluation/datasets/{id}`）。 */
export interface DatasetDetailResponse {
  dataset: DatasetOut;
  cases: CaseOut[];
}

/** 运行详情响应（`GET /evaluation/runs/{id}`）。 */
export interface RunDetailResponse {
  run: RunOut;
  results: ResultOut[];
}

// -- 回归对比（§5.5） --------------------------------------------------------

/** 单指标三元组（A / B / Δ）；任一缺失为 `null` → `N/A`（**不得视为 0**）。 */
export interface MetricTriple {
  a: number | null;
  b: number | null;
  delta: number | null;
}

/** 失败用例分组（仅 A / 仅 B / 两者皆失败），元素为 `case_key`。 */
export interface CompareFails {
  only_a: string[];
  only_b: string[];
  both: string[];
}

/** 回归对比报告（`CompareReport`；`GET /evaluation/runs/{id}/compare`）。 */
export interface CompareReport {
  dataset_id: string;
  dataset_version: number;
  agent_version_a: string;
  agent_version_b: string;
  pass_rate: MetricTriple;
  mean_score: MetricTriple;
  fails: CompareFails;
  duration_ms: MetricTriple;
  token_usage: MetricTriple;
  cost: MetricTriple;
}

// -- 类型守卫 ----------------------------------------------------------------

/** 判定是否为数据集状态字面值。 */
export function isDatasetStatus(value: unknown): value is DatasetStatus {
  return typeof value === "string" && (DATASET_STATUSES as readonly string[]).includes(value);
}

/** 判定是否为运行状态字面值。 */
export function isRunStatus(value: unknown): value is RunStatus {
  return typeof value === "string" && (RUN_STATUSES as readonly string[]).includes(value);
}

/** 判定是否为数据集列表响应（含 `items` 数组）。 */
export function isDatasetListResponse(value: unknown): value is DatasetListResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { items?: unknown }).items)
  );
}

/** 判定是否为数据集详情响应（含 `dataset` + `cases` 数组）。 */
export function isDatasetDetailResponse(value: unknown): value is DatasetDetailResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { dataset?: unknown; cases?: unknown };
  return (
    typeof candidate.dataset === "object" &&
    candidate.dataset !== null &&
    Array.isArray(candidate.cases)
  );
}

/** 判定是否为运行详情响应（含 `run` + `results` 数组）。 */
export function isRunDetailResponse(value: unknown): value is RunDetailResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { run?: unknown; results?: unknown };
  return (
    typeof candidate.run === "object" && candidate.run !== null && Array.isArray(candidate.results)
  );
}

/** 判定是否为回归对比报告（含指标三元组 + `fails`）。 */
export function isCompareReport(value: unknown): value is CompareReport {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { pass_rate?: unknown; fails?: unknown };
  return (
    typeof candidate.pass_rate === "object" &&
    candidate.pass_rate !== null &&
    typeof candidate.fails === "object" &&
    candidate.fails !== null
  );
}
