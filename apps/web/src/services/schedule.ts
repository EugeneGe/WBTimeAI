import { api } from "@/lib/api";
import type { ScheduleResponse, TriggerScheduleResponse } from "@/types";

/**
 * 调度服务（`/schedules`，W7 / T2-39 既有 CSP；W10 / T2-50 前端接入；
 * M04-03 补 update；**B-20 补 create / get / remove + 扩展 update 字段**）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 * 🔴 `PUT /schedules/{id}` 为**部分更新**（后端 `UpdateScheduleRequest` 全字段可选）。
 * 🔴 后端 `UpdateScheduleRequest` **不含** `target_type` / `target_id`：
 *    调度的目标在创建后不可变更，编辑弹窗必须把这两个字段置灰。
 */

/**
 * 创建调度请求体（`CreateScheduleRequest`）。
 *
 * 后端默认值：`target_type="agent"`、`trigger="manual"`、`payload={}`、`enabled=true`；
 * 本层仍**显式**传出这些字段，避免前后端默认值漂移。
 */
export interface CreateSchedulePayload {
  /** 名称（必填）。 */
  name: string;
  /** 目标类型（`agent` | `workflow`）。 */
  target_type?: string;
  /** 目标 id（必填）。 */
  target_id: string;
  /** 触发方式（`cron` | `event` | `webhook` | `manual`）。 */
  trigger?: string;
  /** cron 表达式（`trigger=cron` 时必填；否则显式传 `null`）。 */
  cron?: string | null;
  /** 事件类型（`trigger=event` 时必填；否则显式传 `null`）。 */
  event_type?: string | null;
  /** 触发载荷（对象，默认 `{}`）。 */
  payload?: Record<string, unknown>;
  /** 启用态（默认 `true`）。 */
  enabled?: boolean;
}

/**
 * 调度部分更新请求体（`UpdateScheduleRequest`；字段缺省 = 不变更）。
 *
 * 🔴 **不含** `target_type` / `target_id`（后端不支持，创建后不可改）。
 */
export interface UpdateSchedulePayload {
  /** 名称。 */
  name?: string;
  /** 触发方式。 */
  trigger?: string;
  /** cron 表达式（切到 `event` 时显式传 `null` 清空）。 */
  cron?: string | null;
  /** 事件类型（切到 `cron` 时显式传 `null` 清空）。 */
  event_type?: string | null;
  /** 触发载荷。 */
  payload?: Record<string, unknown>;
  /** 启用态（`true` 启用 / `false` 停用）。 */
  enabled?: boolean;
  /** 下次运行时间（后端计算字段，前端只在需要时透传）。 */
  next_run_at?: string | null;
}

export const scheduleService = {
  /** 调度列表（当前租户）。 */
  list(): Promise<ScheduleResponse[]> {
    return api.get<ScheduleResponse[]>("/schedules").then((r) => r.data);
  },

  /** 调度详情（不存在 / 跨租户 → 404）。 */
  get(id: string): Promise<ScheduleResponse> {
    return api.get<ScheduleResponse>(`/schedules/${id}`).then((r) => r.data);
  },

  /** 新建调度（`POST /schedules` → 201）。 */
  create(payload: CreateSchedulePayload): Promise<ScheduleResponse> {
    return api.post<ScheduleResponse>("/schedules", payload).then((r) => r.data);
  },

  /** 显式触发一次调度（manual / webhook 路径；**幂等**，返回 `task_id`）。 */
  trigger(id: string): Promise<TriggerScheduleResponse> {
    return api.post<TriggerScheduleResponse>(`/schedules/${id}/trigger`).then((r) => r.data);
  },

  /** 部分更新调度（`PUT /schedules/{id}`；不支持的字段见 {@link UpdateSchedulePayload}）。 */
  update(id: string, payload: UpdateSchedulePayload): Promise<ScheduleResponse> {
    return api.put<ScheduleResponse>(`/schedules/${id}`, payload).then((r) => r.data);
  },

  /** 删除调度（`DELETE /schedules/{id}` → 204，无响应体）。 */
  remove(id: string): Promise<void> {
    return api.delete<void>(`/schedules/${id}`).then(() => undefined);
  },
};
