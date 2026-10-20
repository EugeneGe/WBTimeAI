import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { projectService } from "@/services/project";
import { useAuthStore } from "@/stores/authStore";
import type { CreateProjectRequest } from "@/types";

/** 项目列表（`workspaceId` 为空时不请求）。 */
export function useProjects(workspaceId: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.projects(workspaceId ?? ""),
    queryFn: () => projectService.list(workspaceId as string),
    enabled: isAuthenticated && Boolean(workspaceId),
  });
}

/** 项目详情（`id` 为空时不请求）。 */
export function useProject(id: string | null) {
  return useQuery({
    queryKey: queryKeys.project(id ?? ""),
    queryFn: () => projectService.get(id as string),
    enabled: Boolean(id),
  });
}

/** 创建项目 mutation（成功失效所属工作区列表）。 */
export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateProjectRequest) => projectService.create(payload),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(project.workspace_id) });
    },
  });
}

/**
 * 工作区文件清单（`workspaceId` 为空时不请求）。
 *
 * 🔴 `retry: false`：文件能力未装配时后端返回 **503**——**不重试**，由 Page 渲染降级态。
 */
export function useWorkspaceFiles(workspaceId: string | null, prefix: string) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.workspaceFiles(workspaceId ?? "", prefix),
    queryFn: () => projectService.listFiles(workspaceId as string, { prefix: prefix || null }),
    enabled: isAuthenticated && Boolean(workspaceId),
    retry: false,
  });
}

/** 工作区运行环境清单（敏感项 masked）。 */
export function useWorkspaceEnvironments(workspaceId: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.workspaceEnvironments(workspaceId ?? ""),
    queryFn: () => projectService.listEnvironments(workspaceId as string),
    enabled: isAuthenticated && Boolean(workspaceId),
  });
}

/** 工作区运行环境详情（敏感项 masked）。 */
export function useWorkspaceEnvironment(workspaceId: string | null, environmentId: string | null) {
  return useQuery({
    queryKey: queryKeys.workspaceEnvironment(workspaceId ?? "", environmentId ?? ""),
    queryFn: () => projectService.getEnvironment(workspaceId as string, environmentId as string),
    enabled: Boolean(workspaceId) && Boolean(environmentId),
  });
}
