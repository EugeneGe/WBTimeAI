import { api } from "@/lib/api";
import type { TaskExecutionResponse, TaskListFilters, TaskResponse } from "@/types";

/**
 * 任务服务（`/tasks`，W6 / T1-29 + W10 / T2-49 扩展；W10-E2 执行历史）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 */
export const taskService = {
  /** 任务列表（`task_type` / `status` 过滤 + 分页）。 */
  list(filters?: TaskListFilters): Promise<TaskResponse[]> {
    return api
      .get<TaskResponse[]>("/tasks", {
        params: {
          task_type: filters?.task_type ?? undefined,
          status: filters?.status ?? undefined,
          limit: filters?.limit,
          offset: filters?.offset,
        },
      })
      .then((r) => r.data);
  },

  /** 任务详情（跨租户 / 不存在 → 404）。 */
  get(id: string): Promise<TaskResponse> {
    return api.get<TaskResponse>(`/tasks/${id}`).then((r) => r.data);
  },

  /** 任务执行历史（`task_execution`，按 `attempt` 升序；W10-E2）。 */
  listExecutions(id: string): Promise<TaskExecutionResponse[]> {
    return api.get<TaskExecutionResponse[]>(`/tasks/${id}/executions`).then((r) => r.data);
  },

  /** 取消任务（终态幂等返回既有状态）。 */
  cancel(id: string): Promise<TaskResponse> {
    return api.post<TaskResponse>(`/tasks/${id}/cancel`).then((r) => r.data);
  },
};
