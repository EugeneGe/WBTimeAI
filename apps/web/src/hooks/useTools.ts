import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { toolService } from "@/services/tool";
import { useAuthStore } from "@/stores/authStore";
import type { ToolPermissionRequest } from "@/types";

/** 内置工具浏览器（5 个内置 Tool）。 */
export function useTools() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.tools,
    queryFn: () => toolService.list(),
    enabled: isAuthenticated,
  });
}

/** 某 Agent 的 Tool 权限列表（`agentId` 为空时不请求）。 */
export function useToolPermissions(agentId: string | null) {
  return useQuery({
    queryKey: queryKeys.toolPermissions(agentId ?? ""),
    queryFn: () => toolService.listPermissions(agentId as string),
    enabled: Boolean(agentId),
  });
}

/** 授予 / 更新 Tool 权限 mutation。 */
export function useGrantToolPermission() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ToolPermissionRequest) => toolService.grant(payload),
    onSuccess: (permission) => {
      if (permission.agent_id) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.toolPermissions(permission.agent_id),
        });
      }
    },
  });
}

/** 撤销 Tool 权限 mutation。 */
export function useRevokeToolPermission(agentId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (permissionId: string) => toolService.revoke(permissionId),
    onSuccess: () => {
      if (agentId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.toolPermissions(agentId) });
      }
    },
  });
}
