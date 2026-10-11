import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { scheduleService } from "@/services/schedule";
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
