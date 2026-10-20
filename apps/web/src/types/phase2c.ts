/**
 * Phase 2c 前端领域 DTO（W10 / T2-50；设计 §2.12 / §2.13；裁定 R-W10-11 + W10-E1）。
 *
 * 与后端 `apps/api/src/wbtime_ai_api/schemas/{project,approval,task}.py` 严格对齐；
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

/**
 * 任务响应（`TaskResponse`）。
 *
 * 🔴 `execution_mode` 的真实取值只有 `INLINE` / `QUEUED`（后端
 *    `packages/task/src/wbtime_ai_task/models.py`），**不是**「本地 / 远程」的判据；
 *    任务是否属于远程工作台由 **`project_id` 非空** 判定（后端
 *    `routers/v1/tasks.py::_is_remote_task` 亦按 `payload["project_id"]` 判定）。
 */
export interface TaskResponse {
  id: string;
  tenant_id?: string | null;
  workspace_id?: string | null;
  type: string;
  status: string;
  priority: number;
  execution_mode: string;
  /**
   * R3 加性远程字段；本地任务为 `null`。
   *
   * 口径差异（两者都要兼容）：
   * - 不按项目过滤的列表 / 详情：`payload.project_id` 有值，本字段缺省；
   * - 按项目过滤（`_to_remote_view_as_task`）：本字段有值，**不带** `payload`。
   */
  project_id?: string | null;
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

// -- R4 / T2-62：远程工作台（Project Clone / 远程 Task / 审阅 / Apply / Push）------
//
// 与后端 `apps/api/src/wbtime_ai_api/schemas/{task,project}.py` 的 R3 远程视图 + R3/T2-61
// 变更审阅视图严格对齐。🔴 一律**不含**宿主绝对路径（只暴露不透明 `checkout_ref`）；
// 🔴 Apply / Push 走**冻结路径** `POST /tasks/{id}/apply` · `/push`（**非** `/diff/apply`）。

/** 远程任务提交请求（`RemoteTaskSubmitRequest`；`agent_version_id` | `workflow_version_id` 二选一）。 */
export interface RemoteTaskSubmitRequest {
  workspace_id: string;
  project_id: string;
  agent_version_id?: string | null;
  workflow_version_id?: string | null;
  requirement?: string;
  base_ref?: string | null;
  environment_id?: string | null;
  idempotency_key?: string | null;
  limits?: Record<string, unknown>;
}

/** 远程任务提交响应（`202 {task_id}`）。 */
export interface RemoteTaskSubmitResponse {
  task_id: string;
}

/** 远程任务状态快照视图（`RemoteTaskViewResponse`；**不含宿主路径**）。 */
export interface RemoteTaskViewResponse {
  task_id: string;
  type: string;
  status: string;
  tenant_id?: string | null;
  workspace_id?: string | null;
  project_id?: string | null;
  attempt_count: number;
  checkout_ref?: string | null;
  base_commit?: string | null;
  result_commit?: string | null;
  environment_digest?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** Attempt 视图（`TaskAttemptResponse`；**不含宿主路径**）。 */
export interface TaskAttemptResponse {
  attempt: number;
  status: string;
  checkout_ref?: string | null;
  base_commit?: string | null;
  result_commit?: string | null;
  environment_digest?: string | null;
  worker_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
  artifact_refs?: Record<string, unknown> | null;
}

/** 任务级事件帧（`TaskEventResponse`；`seq` 单调，可经不透明 `cursor` 续读）。 */
export interface TaskEventResponse {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  created_at?: string | null;
}

/** 事件分页响应（`TaskEventPageResponse`；含下一页**不透明** cursor）。 */
export interface TaskEventPageResponse {
  events: TaskEventResponse[];
  next_cursor: string;
}

/** 任务日志行（`TaskLogResponse`）。 */
export interface TaskLogResponse {
  seq: number;
  attempt: number;
  level: string;
  message: string;
  created_at?: string | null;
}

/** 受限 Diff 的单个文件变更摘要（`DiffFileResponse`）。 */
export interface DiffFileResponse {
  path: string;
  change_type: string;
  additions: number;
  deletions: number;
}

/** 某 Attempt 的**受限** Diff（`TaskDiffResponse`；只读）。 */
export interface TaskDiffResponse {
  attempt: number;
  checkout_ref?: string | null;
  base_commit?: string | null;
  result_commit?: string | null;
  available: boolean;
  files: DiffFileResponse[];
  truncated: boolean;
}

/** Artifact 元数据（`TaskArtifactResponse`；下载**逐项重新鉴权**）。 */
export interface TaskArtifactResponse {
  name: string;
  ref: string;
  size?: number | null;
  content_type?: string | null;
}

/** 显式 Apply 请求（`ApplyTaskRequest`；F-R6；**不** Push）。 */
export interface ApplyTaskRequest {
  target_ref?: string | null;
  idempotency_key?: string | null;
}

/** 显式 Apply 响应（`ApplyTaskResponse`；**只**更新服务器目标分支）。 */
export interface ApplyTaskResponse {
  task_id: string;
  target_ref: string;
  base_commit?: string | null;
  result_commit?: string | null;
  applied_commit?: string | null;
  already_applied: boolean;
}

/** 显式 Push 请求（`PushTaskRequest`；F-R7；**独立**权限）。`remote` 仅接受 `origin`。 */
export interface PushTaskRequest {
  target_ref?: string | null;
  remote?: string;
}

/** 显式 Push 响应（`PushTaskResponse`；**不含**任何凭证）。 */
export interface PushTaskResponse {
  task_id: string;
  target_ref: string;
  remote: string;
  ref: string;
  pushed: boolean;
  already_up_to_date: boolean;
}

/** Project Clone 请求（`CloneProjectRequest`）。 */
export interface CloneProjectRequest {
  base_ref?: string | null;
  idempotency_key?: string | null;
}

/** Project Clone 响应（`202 {task_id}`）。 */
export interface CloneProjectResponse {
  task_id: string;
}

/** 远程 Project 状态视图（`ProjectStatusResponse`；**不含宿主路径**）。 */
export interface ProjectStatusResponse {
  project_id: string;
  name: string;
  workspace_id: string;
  tenant_id?: string | null;
  default_branch?: string | null;
  repo_configured: boolean;
  clone_task_id?: string | null;
  refs_available: boolean;
}

/** Git 引用视图（`GitRefResponse`；**不含宿主路径**）。 */
export interface GitRefResponse {
  name: string;
  commit?: string | null;
  kind: string;
}
