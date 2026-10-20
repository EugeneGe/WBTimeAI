import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import {
  scheduleService,
  type CreateSchedulePayload,
  type UpdateSchedulePayload,
} from "@/services/schedule";
import { useAuthStore } from "@/stores/authStore";

/** 调度列表（当前租户）。 */
export function useSchedules() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.schedules,
    queryFn: () => scheduleService.list(),
    enabled: isAuthenticated,
  });
}

/**
 * 新建调度 mutation（B-20；成功失效调度列表）。
 *
 * 🔴 新建只影响调度列表（不会立即产出任务），故不刷任务列表。
 */
export function useCreateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateSchedulePayload) => scheduleService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schedules });
    },
  });
}

/** 显式触发调度 mutation（成功失效调度列表与任务列表）。 */
export function useTriggerSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => scheduleService.trigger(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schedules });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

/** 部分更新调度的入参（`id` + 变更字段）。 */
export interface UpdateScheduleVariables extends UpdateSchedulePayload {
  /** 调度 id。 */
  id: string;
}

/**
 * 部分更新调度 mutation（M04-03：启用开关；B-20：编辑弹窗）。
 *
 * 🔴 仅失效调度列表：启停 / 改配置都不直接产生任务，无需刷任务列表。
 */
export function useUpdateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: UpdateScheduleVariables) =>
      scheduleService.update(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schedules });
    },
  });
}

/** 删除调度 mutation（B-20；成功失效调度列表）。 */
export function useDeleteSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => scheduleService.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.schedules });
    },
  });
}
