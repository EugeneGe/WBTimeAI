/**
 * Phase 2c 前端领域 DTO（W10 / T2-50；设计 §2.12 / §2.13；裁定 R-W10-11 + W10-E1）。
 *
 * 与后端 `apps/api/src/astra_api/schemas/{project,approval,task}.py` 严格对齐；
 * 统一响应壳由 `lib/api.ts` 拦截器解壳，服务层直接拿到业务 DTO。
 *
 * 🔴 环境敏感项纪律（R-W10-02）：`EnvironmentVarResponse` 的敏感变量 `masked=true` 且
 *    `value` 恒为 `null`，前端**只展示引用**（`ref`，形如 `credential:<id>` / `secret:<NAME>`），
 *    **禁**展示或输入明文。
 * 🔴 Git 面（W10-E1）：本波未新增 git HTTP 端点；Page 仅展示 Project 元信息 + 降级标注，
 *    **禁止伪造实时 Git 状态**。
 */

// -- Project ---------------------------------------------------------------

/** 创建项目请求（`name` + `workspace_id` 必填）。 */
export interface CreateProjectRequest {
  name: string;
  workspace_id: string;
  description?: string | null;
  repo_url?: string | null;
  default_branch?: string | null;
  organization_id?: string | null;
  settings?: Record<string, unknown>;
}

/** 项目响应（`ProjectResponse`）。 */
export interface ProjectResponse {
  id: string;
  tenant_id?: string | null;
  organization_id?: string | null;
  workspace_id: string;
  name: string;
  description?: string | null;
  repo_url?: string | null;
  default_branch?: string | null;
  settings: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

// -- Workspace Files -------------------------------------------------------

/** 工作区文件对象元数据（`FileObjectResponse`）。 */
export interface FileObjectResponse {
  key: string;
  size: number;
  content_type?: string | null;
  etag?: string | null;
  created_at?: string | null;
}

/** 工作区文件内容（`FileContentResponse`；base64 承载，二进制安全）。 */
export interface FileContentResponse {
  path: string;
  size: number;
  encoding: string;
  content_base64: string;
}

// -- Workspace Environment -------------------------------------------------

/** 单个环境变量（敏感项 `masked=true`、`value=null`、仅含 `ref` 引用）。 */
export interface EnvironmentVarResponse {
  name: string;
  value?: string | null;
  ref?: string | null;
  masked: boolean;
}

/** 工作区运行环境（`EnvironmentResponse`）。 */
export interface EnvironmentResponse {
  id: string;
  tenant_id?: string | null;
  organization_id?: string | null;
  workspace_id: string;
  name: string;
  env_vars: EnvironmentVarResponse[];
  runtime: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

// -- Task ------------------------------------------------------------------

/** 任务响应（`TaskResponse`）。 */
export interface TaskResponse {
  id: string;
  tenant_id?: string | null;
  workspace_id?: string | null;
  type: string;
  status: string;
  priority: number;
  execution_mode: string;
  payload: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 任务执行记录（`TaskExecutionResponse`；W10-E2）。 */
export interface TaskExecutionResponse {
  id: string;
  task_id: string;
  attempt: number;
  worker_id?: string | null;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
}

/** 任务列表过滤（`GET /tasks` query）。 */
export interface TaskListFilters {
  task_type?: string | null;
  status?: string | null;
  limit?: number;
  offset?: number;
}

// -- Schedule --------------------------------------------------------------

/** 调度响应（`ScheduleResponse`；W7 / T2-39 既有 CSP）。 */
export interface ScheduleResponse {
  id: string;
  tenant_id?: string | null;
  organization_id?: string | null;
  workspace_id?: string | null;
  name: string;
  target_type: string;
  target_id: string;
  trigger: string;
  cron?: string | null;
  event_type?: string | null;
  payload: Record<string, unknown>;
  enabled: boolean;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 显式触发调度响应（`TriggerScheduleResponse`；返回幂等 `task_id`）。 */
export interface TriggerScheduleResponse {
  schedule_id: string;
  task_id: string;
}
