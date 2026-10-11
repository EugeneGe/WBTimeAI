import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { workspaceService } from "@/services/workspace";
import { useAuthStore } from "@/stores/authStore";
import type { CreateWorkspaceRequest, UpdateWorkspaceSettingsRequest } from "@/types";

/** 工作区列表。 */
export function useWorkspaces() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.workspaces,
    queryFn: () => workspaceService.list(),
    enabled: isAuthenticated,
  });
}

/** 工作区详情（`id` 为空时不请求）。 */
export function useWorkspace(id: string | null) {
  return useQuery({
    queryKey: queryKeys.workspace(id ?? ""),
    queryFn: () => workspaceService.get(id as string),
    enabled: Boolean(id),
  });
}

/** 创建工作区 mutation（成功失效列表）。 */
export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateWorkspaceRequest) => workspaceService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
    },
  });
}

/** 更新工作区设置 mutation（成功失效列表与详情）。 */
export function useUpdateWorkspaceSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; payload: UpdateWorkspaceSettingsRequest }) =>
      workspaceService.updateSettings(input.id, input.payload),
    onSuccess: (workspace) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspace(workspace.id) });
    },
  });
}
