import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { taskService } from "@/services/task";
import { useAuthStore } from "@/stores/authStore";
import type { TaskListFilters } from "@/types";

/** 任务列表（`task_type` / `status` 过滤）。 */
export function useTasks(filters: TaskListFilters) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const filterKey = `${filters.task_type ?? ""}:${filters.status ?? ""}`;
  return useQuery({
    queryKey: queryKeys.tasks(filterKey),
    queryFn: () => taskService.list(filters),
    enabled: isAuthenticated,
  });
}

/** 任务详情（`id` 为空时不请求）。 */
export function useTask(id: string | null) {
  return useQuery({
    queryKey: queryKeys.task(id ?? ""),
    queryFn: () => taskService.get(id as string),
    enabled: Boolean(id),
  });
}

/** 任务执行历史（`task_execution`，按 `attempt` 升序）。 */
export function useTaskExecutions(id: string | null) {
  return useQuery({
    queryKey: queryKeys.taskExecutions(id ?? ""),
    queryFn: () => taskService.listExecutions(id as string),
    enabled: Boolean(id),
  });
}

/** 取消任务 mutation（成功失效详情与列表）。 */
export function useCancelTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => taskService.cancel(id),
    onSuccess: (task) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.task(task.id) });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}
