import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { workflowService } from "@/services/workflow";
import { useAuthStore } from "@/stores/authStore";
import type { CreateWorkflowRequest, PublishWorkflowRequest } from "@/types";

/**
 * Workflow hooks（TanStack Query；W4 / T2-25 契约；W6 / T2-35 前端）。
 *
 * 服务状态唯一真相源；`enabled` 依认证态（对齐 `hooks/useSkills.ts` 范式）。
 */

/** Workflow 列表。 */
export function useWorkflows() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.workflows,
    queryFn: () => workflowService.list(),
    enabled: isAuthenticated,
  });
}

/** Workflow 详情（`workflowId` 为空时不请求）。 */
export function useWorkflow(workflowId: string | null) {
  return useQuery({
    queryKey: queryKeys.workflow(workflowId ?? ""),
    queryFn: () => workflowService.get(workflowId as string),
    enabled: Boolean(workflowId),
  });
}

/** Workflow 版本列表（`workflowId` 为空时不请求）。 */
export function useWorkflowVersions(workflowId: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.workflowVersions(workflowId ?? ""),
    queryFn: () => workflowService.listVersions(workflowId as string),
    enabled: isAuthenticated && Boolean(workflowId),
  });
}

/** 创建 Workflow mutation。 */
export function useCreateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateWorkflowRequest) => workflowService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflows });
    },
  });
}

/** 发布新版本 mutation（保存画布 = 新 `workflow_version`》。 */
export function usePublishWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      workflowId,
      payload,
    }: {
      workflowId: string;
      payload: PublishWorkflowRequest;
    }) => workflowService.publish(workflowId, payload),
    onSuccess: (version) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflows });
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflow(version.workflow_id) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflowVersions(version.workflow_id),
      });
    },
  });
}
