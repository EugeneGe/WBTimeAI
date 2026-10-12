import { api } from "@/lib/api";
import type {
  ApplyTaskRequest,
  ApplyTaskResponse,
  CloneProjectRequest,
  CloneProjectResponse,
  GitRefResponse,
  ProjectStatusResponse,
  PushTaskRequest,
  PushTaskResponse,
  RemoteTaskSubmitRequest,
  RemoteTaskSubmitResponse,
  RemoteTaskViewResponse,
  TaskArtifactResponse,
  TaskAttemptResponse,
  TaskDiffResponse,
  TaskEventPageResponse,
  TaskLogResponse,
  TaskResponse,
} from "@/types";

/** 审阅相关查询参数（`attempt` 缺省取最近完成 Attempt）。 */
export interface AttemptParams {
  attempt?: number | null;
}

/**
 * 远程工作台服务（R3 / T2-60 + R3 / T2-61 + R4 / T2-62）。
 *
 * 面（`apps/api/src/astra_api/routers/v1/{tasks,projects}.py`）：
 *
 * - 远程提交 / 状态 / Attempt / Event（断点续读）/ Log / Diff / Artifact；
 * - **显式 Apply**：`POST /tasks/{task_id}/apply`（F-R6；**不** Push）；
 * - **显式 Push**：`POST /tasks/{task_id}/push`（F-R7；**独立**权限，`remote` 仅 `origin`）；
 * - Project Clone / 状态 / Git refs。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 * 🔴 **冻结路径**：Apply / Push **必须**命中 `/tasks/{id}/apply` · `/push`，
 *    **禁止**使用未注册的 `/tasks/{id}/diff/apply`（后端 → 404）。
 * 🔴 Diff / Artifact / Git 能力未装配时后端返回 **503**（`DEPENDENCY_MISSING`）——
 *    调用方（Hook / Page）以 `retry: false` + 降级态处理，**不**重试、**不**伪造。
 */
export const remoteTaskService = {
  /** 远程提交任务（`201`/`202` `{task_id}`；`EXECUTE + task.submit`）。 */
  submit(payload: RemoteTaskSubmitRequest): Promise<RemoteTaskSubmitResponse> {
    return api.post<RemoteTaskSubmitResponse>("/tasks", payload).then((r) => r.data);
  },

  /** 远程任务状态快照（跨租户 / 越界 → 404）。 */
  getTask(id: string): Promise<RemoteTaskViewResponse> {
    return api.get<RemoteTaskViewResponse>(`/tasks/${id}`).then((r) => r.data);
  },

  /** Attempt 列表（不透明 `checkout_ref`，**不含宿主路径**）。 */
  listAttempts(id: string): Promise<TaskAttemptResponse[]> {
    return api.get<TaskAttemptResponse[]>(`/tasks/${id}/attempts`).then((r) => r.data);
  },

  /**
   * 事件回放 / 断点续读（`cursor` 为空取首页；`seq` 单调）。
   *
   * 🔴 **不重试**：过期 cursor 返回 `EVENT_CURSOR_EXPIRED`（410），由调用方提示重取首页。
   */
  listEvents(id: string, cursor?: string | null): Promise<TaskEventPageResponse> {
    return api
      .get<TaskEventPageResponse>(`/tasks/${id}/events`, {
        params: { cursor: cursor ?? undefined },
      })
      .then((r) => r.data);
  },

  /** 日志行。 */
  listLogs(id: string): Promise<TaskLogResponse[]> {
    return api.get<TaskLogResponse[]>(`/tasks/${id}/logs`).then((r) => r.data);
  },

  /** 受限 Diff（`EXECUTE + git.diff`；`attempt` 缺省取最近完成 Attempt）。 */
  getDiff(id: string, params?: AttemptParams): Promise<TaskDiffResponse> {
    return api
      .get<TaskDiffResponse>(`/tasks/${id}/diff`, {
        params: { attempt: params?.attempt ?? undefined },
      })
      .then((r) => r.data);
  },

  /** Artifact 元数据（下载**逐项重新鉴权**）。 */
  listArtifacts(id: string, params?: AttemptParams): Promise<TaskArtifactResponse[]> {
    return api
      .get<TaskArtifactResponse[]>(`/tasks/${id}/artifacts`, {
        params: { attempt: params?.attempt ?? undefined },
      })
      .then((r) => r.data);
  },

  /** Artifact 内容（经鉴权下载，返回 Blob；**不含**宿主路径）。 */
  downloadArtifact(id: string, name: string, params?: AttemptParams): Promise<Blob> {
    return api
      .get<Blob>(`/tasks/${id}/artifacts/${name}`, {
        params: { attempt: params?.attempt ?? undefined },
        responseType: "blob",
      })
      .then((r) => r.data);
  },

  /** 取消任务（终态幂等；**远程任务**追加 `EXECUTE + task.cancel`）。 */
  cancel(id: string): Promise<TaskResponse> {
    return api.post<TaskResponse>(`/tasks/${id}/cancel`).then((r) => r.data);
  },

  /**
   * **显式 Apply**（F-R6；`EXECUTE + git.apply`；**不** Push）。
   *
   * 目标分支前进 / 脏工作树 / 冲突 → **409**（保留原 Project / Attempt）；缺能力 → 403。
   */
  apply(id: string, payload: ApplyTaskRequest): Promise<ApplyTaskResponse> {
    return api.post<ApplyTaskResponse>(`/tasks/${id}/apply`, payload).then((r) => r.data);
  },

  /**
   * **显式 Push**（F-R7；**独立** `EXECUTE + git.push`）。
   *
   * 未配置写凭证 → **422**；任意 URL / 强推 / 删分支 → **403**；推送被拒 → 409。
   */
  push(id: string, payload: PushTaskRequest): Promise<PushTaskResponse> {
    return api.post<PushTaskResponse>(`/tasks/${id}/push`, payload).then((r) => r.data);
  },

  /** 异步克隆 Project（`202 {task_id}`；`EXECUTE + project.clone`）。 */
  cloneProject(id: string, payload: CloneProjectRequest): Promise<CloneProjectResponse> {
    return api.post<CloneProjectResponse>(`/projects/${id}/clone`, payload).then((r) => r.data);
  },

  /** 远程 Project 状态（**不含宿主路径**）。 */
  projectStatus(id: string): Promise<ProjectStatusResponse> {
    return api.get<ProjectStatusResponse>(`/projects/${id}/status`).then((r) => r.data);
  },

  /** Git 引用清单（**仅经 Sandbox**；未装配 → 503）。 */
  listGitRefs(id: string): Promise<GitRefResponse[]> {
    return api.get<GitRefResponse[]>(`/projects/${id}/git/refs`).then((r) => r.data);
  },
};
