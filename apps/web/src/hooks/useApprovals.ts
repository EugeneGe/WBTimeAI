import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { approvalService } from "@/services/approval";
import { useAuthStore } from "@/stores/authStore";
import type { ApprovalsQuery } from "@/types";

/**
 * Approval hooks（TanStack Query；W10 / T2-49 契约）。
 *
 * 🔴 **queryKey 内联在本文件**（`["approvals", ...]`）——本波 `src/lib/query.ts` 由另一路独占，
 *    故不向 `queryKeys` 工厂追加条目；失效一律以 `["approvals"]` **前缀命中**列表 + 详情。
 * 🔴 `enabled` 依认证态（对齐 `hooks/useWorkflow.ts` 范式）：未登录不发请求。
 */

/** 审批列表 query key（`params` 归一为 `null` 便于稳定序列化比对）。 */
function approvalsListKey(params?: ApprovalsQuery) {
  return ["approvals", params ?? null] as const;
}

/** 审批详情 query key。 */
function approvalDetailKey(approvalId: string) {
  return ["approvals", approvalId] as const;
}

/** 列表族前缀（失效时前缀命中列表 + 详情缓存）。 */
const APPROVALS_PREFIX = ["approvals"] as const;

/**
 * 待办审批列表（仅 `PENDING`）。
 *
 * @param params 分页参数（缺省 → 后端默认值）。
 * @returns TanStack Query 结果（`data` 为审批数组）。
 */
export function useApprovals(params?: ApprovalsQuery) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: approvalsListKey(params),
    queryFn: () => approvalService.list(params),
    enabled: isAuthenticated,
  });
}

/**
 * 审批详情（`approvalId` 为空时不请求）。
 *
 * @param approvalId 审批 id（`null` → 不请求）。
 * @returns TanStack Query 结果（`data` 为审批响应）。
 */
export function useApproval(approvalId: string | null) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: approvalDetailKey(approvalId ?? ""),
    queryFn: () => approvalService.get(approvalId as string),
    enabled: isAuthenticated && Boolean(approvalId),
  });
}

/**
 * 决议**通过** mutation。
 *
 * 成功后失效列表（该条已离开待办）与详情（状态已变）。
 */
export function useApproveApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (approvalId: string) => approvalService.approve(approvalId),
    onSuccess: (approval) => {
      void queryClient.invalidateQueries({ queryKey: APPROVALS_PREFIX });
      void queryClient.invalidateQueries({ queryKey: approvalDetailKey(approval.id) });
    },
  });
}

/**
 * 决议**驳回** mutation（调用方需先经二次确认弹窗）。
 *
 * 成功后失效列表与详情（同 {@link useApproveApproval}）。
 */
export function useRejectApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (approvalId: string) => approvalService.reject(approvalId),
    onSuccess: (approval) => {
      void queryClient.invalidateQueries({ queryKey: APPROVALS_PREFIX });
      void queryClient.invalidateQueries({ queryKey: approvalDetailKey(approval.id) });
    },
  });
}
