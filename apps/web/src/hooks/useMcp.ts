import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { mcpService } from "@/services/mcp";
import { useAuthStore } from "@/stores/authStore";
import type { CreateMCPPermissionRequest, RegisterMCPServerRequest } from "@/types";

/**
 * MCP hooks（TanStack Query；W3 / T2-18；设计 §2.4）。
 *
 * 🔴 凭据**仅引用 / 仅掩码**（C-07）：本层**不缓存、不回显**任何明文密钥。
 */

/** MCP Server 列表。 */
export function useMcpServers() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.mcpServers,
    queryFn: () => mcpService.listServers(),
    enabled: isAuthenticated,
  });
}

/** MCP 工具目录（可按 `serverId` 过滤）。 */
export function useMcpTools(serverId?: string) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.mcpTools(serverId),
    queryFn: () => mcpService.listTools(serverId),
    enabled: isAuthenticated,
  });
}

/** 某 MCPTool 的授权列表（`mcpToolId` 为空时不请求）。 */
export function useMcpPermissions(mcpToolId: string | null) {
  return useQuery({
    queryKey: queryKeys.mcpPermissions(mcpToolId ?? ""),
    queryFn: () => mcpService.listPermissions(mcpToolId as string),
    enabled: Boolean(mcpToolId),
  });
}

/** 注册 MCP Server mutation。 */
export function useRegisterMcpServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RegisterMCPServerRequest) => mcpService.registerServer(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.mcpServers });
    },
  });
}

/** 删除 MCP Server mutation。 */
export function useDeleteMcpServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => mcpService.deleteServer(serverId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.mcpServers });
      void queryClient.invalidateQueries({ queryKey: ["mcp", "tools"] });
    },
  });
}

/** 发现 MCP 工具 mutation（落 `mcp_tool`）。 */
export function useDiscoverMcpTools() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => mcpService.discover(serverId),
    onSuccess: (_tools, serverId) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.mcpTools(serverId) });
      void queryClient.invalidateQueries({ queryKey: ["mcp", "tools"] });
    },
  });
}

/** 新增 MCP Tool 授权 mutation。 */
export function useCreateMcpPermission() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateMCPPermissionRequest) => mcpService.createPermission(payload),
    onSuccess: (permission) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.mcpPermissions(permission.mcp_tool_id),
      });
    },
  });
}
