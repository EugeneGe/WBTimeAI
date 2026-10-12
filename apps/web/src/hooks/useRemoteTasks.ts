import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { remoteTaskService } from "@/services/remoteTask";
import { useAuthStore } from "@/stores/authStore";
import type {
  ApplyTaskRequest,
  CloneProjectRequest,
  PushTaskRequest,
  RemoteTaskSubmitRequest,
} from "@/types";

/** 远程任务状态快照（`id` 为空时不请求）。 */
export function useRemoteTask(id: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.remoteTask(id ?? ""),
    queryFn: () => remoteTaskService.getTask(id as string),
    enabled: isAuthenticated && Boolean(id),
  });
}

/** Attempt 列表（不透明 `checkout_ref`）。 */
export function useRemoteAttempts(id: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.remoteAttempts(id ?? ""),
    queryFn: () => remoteTaskService.listAttempts(id as string),
    enabled: isAuthenticated && Boolean(id),
  });
}

/**
 * 事件回放 / **断点续读**（`cursor` 变化即重取下一页）。
 *
 * 🔴 `retry: false`：过期 cursor → `EVENT_CURSOR_EXPIRED`（410）——**不重试**，由 Page 提示重取首页。
 */
export function useRemoteEvents(id: string | null, cursor: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.remoteEvents(id ?? "", cursor ?? ""),
    queryFn: () => remoteTaskService.listEvents(id as string, cursor),
    enabled: isAuthenticated && Boolean(id),
    retry: false,
  });
}

/** 日志行。 */
export function useRemoteLogs(id: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.remoteLogs(id ?? ""),
    queryFn: () => remoteTaskService.listLogs(id as string),
    enabled: isAuthenticated && Boolean(id),
  });
}

/**
 * 受限 Diff（`attempt` 缺省取最近完成 Attempt）。
 *
 * 🔴 `retry: false`：Diff 能力未装配 → **503**（`DEPENDENCY_MISSING`），由 Page 渲染降级态。
 */
export function useRemoteDiff(id: string | null, attempt: number | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.remoteDiff(id ?? "", attempt ?? 0),
    queryFn: () => remoteTaskService.getDiff(id as string, { attempt }),
    enabled: isAuthenticated && Boolean(id),
    retry: false,
  });
}

/** Artifact 元数据（未装配 → 503，不重试）。 */
export function useRemoteArtifacts(id: string | null, attempt: number | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.remoteArtifacts(id ?? ""),
    queryFn: () => remoteTaskService.listArtifacts(id as string, { attempt }),
    enabled: isAuthenticated && Boolean(id),
    retry: false,
  });
}

/** 远程 Project 状态（未装配 Sandbox → refs 降级；本查询本身稳定）。 */
export function useProjectStatus(id: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.projectStatus(id ?? ""),
    queryFn: () => remoteTaskService.projectStatus(id as string),
    enabled: isAuthenticated && Boolean(id),
    retry: false,
  });
}

/** Git 引用清单（仅经 Sandbox；未装配 → 503，不重试）。 */
export function useProjectGitRefs(id: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.projectGitRefs(id ?? ""),
    queryFn: () => remoteTaskService.listGitRefs(id as string),
    enabled: isAuthenticated && Boolean(id),
    retry: false,
  });
}

/** 提交远程任务 mutation（成功后失效任务列表）。 */
export function useSubmitRemoteTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RemoteTaskSubmitRequest) => remoteTaskService.submit(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

/** Project Clone mutation（异步 `202 {task_id}`）。 */
export function useCloneProject(projectId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CloneProjectRequest) =>
      remoteTaskService.cloneProject(projectId as string, payload),
    onSuccess: () => {
      if (projectId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.projectStatus(projectId) });
      }
    },
  });
}

/**
 * **显式 Apply** mutation（F-R6；**不** Push）。
 *
 * 🔴 成功 / 失败后均失效任务快照与 Attempt / Diff（Apply 改变服务器目标分支）。
 */
export function useApplyChange(taskId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ApplyTaskRequest) => remoteTaskService.apply(taskId as string, payload),
    onSettled: () => {
      if (taskId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.remoteTask(taskId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.remoteAttempts(taskId) });
      }
    },
  });
}

/**
 * **显式 Push** mutation（F-R7；**独立**权限）。
 *
 * 🔴 缺写凭证 → 422；任意 URL / 强推 / 删分支 → 403；推送被拒 → 409（保留原状）。
 */
export function usePushChange(taskId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PushTaskRequest) => remoteTaskService.push(taskId as string, payload),
    onSettled: () => {
      if (taskId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.remoteTask(taskId) });
      }
    },
  });
}

/** 取消远程任务 mutation（终态幂等）。 */
export function useCancelRemoteTask(taskId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => remoteTaskService.cancel(taskId as string),
    onSuccess: () => {
      if (taskId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.remoteTask(taskId) });
      }
    },
  });
}
