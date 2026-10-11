import { api } from "@/lib/api";
import type {
  CreateWorkflowRequest,
  PublishWorkflowRequest,
  WorkflowResponse,
  WorkflowVersionResponse,
} from "@/types";

/**
 * Workflow 服务（`/workflows/*` API，W4 / T2-25 契约；W6 / T2-35 前端接入）。
 *
 * - 定义：创建 / 列表 / 详情；
 * - 版本：列表（**不可变快照**）；
 * - 发布：一次发布 = 一个新 `workflow_version`（保存画布即调用本方法）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO（不重复解壳）。
 */
export const workflowService = {
  /** Workflow 列表（当前租户）。 */
  list(): Promise<WorkflowResponse[]> {
    return api.get<WorkflowResponse[]>("/workflows").then((r) => r.data);
  },
  /** Workflow 详情。 */
  get(workflowId: string): Promise<WorkflowResponse> {
    return api.get<WorkflowResponse>(`/workflows/${workflowId}`).then((r) => r.data);
  },
  /** 创建 Workflow（`DRAFT`）。 */
  create(payload: CreateWorkflowRequest): Promise<WorkflowResponse> {
    return api.post<WorkflowResponse>("/workflows", payload).then((r) => r.data);
  },
  /** Workflow 版本列表（不可变快照）。 */
  listVersions(workflowId: string): Promise<WorkflowVersionResponse[]> {
    return api
      .get<WorkflowVersionResponse[]>(`/workflows/${workflowId}/versions`)
      .then((r) => r.data);
  },
  /** 发布新版本（保存画布 = 新 `workflow_version`）。 */
  publish(workflowId: string, payload: PublishWorkflowRequest): Promise<WorkflowVersionResponse> {
    return api
      .post<WorkflowVersionResponse>(`/workflows/${workflowId}/publish`, payload)
      .then((r) => r.data);
  },
};
