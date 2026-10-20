import { api } from "@/lib/api";
import type { ApprovalResponse, ApprovalsQuery } from "@/types";

/**
 * Approval 服务（`/approvals/*` API；W10 / T2-49 契约）。
 *
 * - `GET  /approvals`：待办列表（**只返回 `PENDING`**，分页）；
 * - `GET  /approvals/{id}`：详情（不存在 / 跨租户 → 404）；
 * - `POST /approvals/{id}/approve`：决议通过（`PENDING → APPROVED`，已决议 → 409）；
 * - `POST /approvals/{id}/reject`：决议驳回（`PENDING → REJECTED`，同上）。
 *
 * 🔴 决议端点**无请求体**：决议人取当前登录用户（后端 `CurrentUser`），
 *    状态由端点语义固定——前端**不得**传 `{ status }` 一类的 body。
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO（不重复解壳）。
 */
export const approvalService = {
  /**
   * 待办审批列表（当前租户；仅 `PENDING`）。
   *
   * @param params 分页参数（缺省 → 后端默认值 `limit=50` / `offset=0`）。
   * @returns 审批响应数组（可能为空数组）。
   */
  list(params?: ApprovalsQuery): Promise<ApprovalResponse[]> {
    return api.get<ApprovalResponse[]>("/approvals", { params }).then((r) => r.data);
  },

  /**
   * 审批详情。
   *
   * @param approvalId 审批 id。
   * @returns 审批响应（任意状态）。
   */
  get(approvalId: string): Promise<ApprovalResponse> {
    return api.get<ApprovalResponse>(`/approvals/${approvalId}`).then((r) => r.data);
  },

  /**
   * 决议**通过**（`POST /approvals/{id}/approve`，无请求体）。
   *
   * @param approvalId 审批 id。
   * @returns 决议后的审批响应（`status = APPROVED`）。
   */
  approve(approvalId: string): Promise<ApprovalResponse> {
    return api.post<ApprovalResponse>(`/approvals/${approvalId}/approve`).then((r) => r.data);
  },

  /**
   * 决议**驳回**（`POST /approvals/{id}/reject`，无请求体）。
   *
   * @param approvalId 审批 id。
   * @returns 决议后的审批响应（`status = REJECTED`）。
   */
  reject(approvalId: string): Promise<ApprovalResponse> {
    return api.post<ApprovalResponse>(`/approvals/${approvalId}/reject`).then((r) => r.data);
  },
};
