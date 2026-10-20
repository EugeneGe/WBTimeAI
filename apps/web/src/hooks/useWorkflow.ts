import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import {
  workflowService,
  type RunWorkflowRequest,
  type UpdateWorkflowRequest,
} from "@/services/workflow";
import { useAuthStore } from "@/stores/authStore";
import {
  isTerminalWorkflowRunStatus,
  type CreateWorkflowRequest,
  type PublishWorkflowRequest,
} from "@/types";

/**
 * Workflow hooks（TanStack Query；W4 / T2-25 契约；W6 / T2-35 前端）。
 *
 * 服务状态唯一真相源；`enabled` 依认证态（对齐 `hooks/useSkills.ts` 范式）。
 *
 * 运行相关 3 个 hook（`useRunWorkflow` / `useWorkflowRun` / `useCancelWorkflowRun`）的
 * query key **就地内联**（`lib/query.ts` 的 `queryKeys` 由架构侧独占维护，本文件不改动）。
 */

/** 某 Workflow 的运行集合 key（取消后失效用）。 */
function workflowRunsKey(workflowId: string) {
  return ["workflows", workflowId, "runs"] as const;
}

/** 单次运行的 key（重放快照）。 */
function workflowRunKey(workflowId: string, runId: string) {
  return ["workflows", workflowId, "runs", runId] as const;
}

/** 非终态轮询间隔（毫秒）：`PENDING` / `RUNNING` / `WAITING_APPROVAL` 时拉重放快照。 */
const RUN_POLL_INTERVAL_MS = 2_000;

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

/**
 * 更新 Workflow mutation（B-21：重命名只传 `{ name }`）。
 *
 * 成功后失效「列表」与「详情」；版本列表不含名称 → 无需失效。
 */
export function useUpdateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ workflowId, payload }: { workflowId: string; payload: UpdateWorkflowRequest }) =>
      workflowService.update(workflowId, payload),
    onSuccess: (workflow) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflows });
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflow(workflow.id) });
    },
  });
}

/**
 * 删除 Workflow mutation（B-21；`DELETE` → `204`）。
 *
 * 成功后失效列表，并**移除**该工作流的详情 / 版本缓存（已不存在，避免 404 噪音重取）。
 */
export function useDeleteWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: string) => workflowService.remove(workflowId),
    onSuccess: (_result, workflowId) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflows });
      queryClient.removeQueries({ queryKey: queryKeys.workflow(workflowId) });
      queryClient.removeQueries({ queryKey: queryKeys.workflowVersions(workflowId) });
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

/**
 * 运行 Workflow mutation（`POST /workflows/{id}/run`；`INLINE` 同步执行）。
 *
 * 🔴 请求**阻塞到工作流跑完**才 resolve（同步语义，见服务层 `run()`）；
 *    返回裸 JSON 摘要（`run_id` / `status` / `error`），不含节点运行态。
 */
export function useRunWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ workflowId, payload }: { workflowId: string; payload: RunWorkflowRequest }) =>
      workflowService.run(workflowId, payload),
    onSuccess: (_digest, variables) => {
      void queryClient.invalidateQueries({ queryKey: workflowRunsKey(variables.workflowId) });
    },
  });
}

/**
 * 运行重放快照（`GET /workflows/{id}/runs/{run_id}`；透传四态）。
 *
 * **轮询**：非终态（`PENDING` / `RUNNING` / `WAITING_APPROVAL`）每 2s 拉一次，
 * 终态（`SUCCEEDED` / `FAILED` / `CANCELLED`）返回 `false` 停止；
 * **错误态亦停止**（4xx/5xx 不会自愈 —— 404 属租户/归属问题，重试只会持续打后端），
 * 恢复走面板上的显式「重试」（`refetch()`）而非隐式轮询。
 * （写法对齐 `hooks/useKnowledge.ts::useDocuments` 的 `refetchInterval` 范式。）
 */
export function useWorkflowRun(workflowId: string | null, runId: string | null, enabled = true) {
  return useQuery({
    queryKey: workflowRunKey(workflowId ?? "", runId ?? ""),
    queryFn: () => workflowService.getRun(workflowId as string, runId as string),
    enabled: enabled && Boolean(workflowId) && Boolean(runId),
    refetchInterval: (query) =>
      query.state.status === "error" || isTerminalWorkflowRunStatus(query.state.data?.status)
        ? false
        : RUN_POLL_INTERVAL_MS,
  });
}

/**
 * 取消运行 mutation（`POST /workflows/{id}/runs/{run_id}/cancel`）。
 *
 * 成功后失效「该 run」与「该 Workflow 的运行列表」；`INLINE` 下请求返回时通常已是终态，
 * 取消属兜底能力（`WAITING_APPROVAL` / 长流程）。
 */
export function useCancelWorkflowRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ workflowId, runId }: { workflowId: string; runId: string }) =>
      workflowService.cancelRun(workflowId, runId),
    onSuccess: (_detail, variables) => {
      void queryClient.invalidateQueries({
        queryKey: workflowRunKey(variables.workflowId, variables.runId),
      });
      void queryClient.invalidateQueries({ queryKey: workflowRunsKey(variables.workflowId) });
    },
  });
}
