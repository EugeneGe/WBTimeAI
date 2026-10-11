import { api } from "@/lib/api";
import type { ScheduleResponse, TriggerScheduleResponse } from "@/types";

/**
 * 调度服务（`/schedules`，W7 / T2-39 既有 CSP；W10 / T2-50 前端接入）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 */
export const scheduleService = {
  /** 调度列表（当前租户）。 */
  list(): Promise<ScheduleResponse[]> {
    return api.get<ScheduleResponse[]>("/schedules").then((r) => r.data);
  },

  /** 显式触发一次调度（manual / webhook 路径；**幂等**，返回 `task_id`）。 */
  trigger(id: string): Promise<TriggerScheduleResponse> {
    return api.post<TriggerScheduleResponse>(`/schedules/${id}/trigger`).then((r) => r.data);
  },
};
