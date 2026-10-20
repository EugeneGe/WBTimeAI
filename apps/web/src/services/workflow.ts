import { api } from "@/lib/api";
import type {
  CreateWorkflowRequest,
  PublishWorkflowRequest,
  WorkflowReplay,
  WorkflowResponse,
  WorkflowRunDetail,
  WorkflowRunDigest,
  WorkflowVersionResponse,
} from "@/types";

/**
 * 更新 Workflow 请求（缺省字段不变）。
 *
 * 与后端 `schemas/workflow.py::UpdateWorkflowRequest` 严格对齐：
 * `name?` / `description?` / `status?`，未提供的字段服务端保持原值。
 * （`apps/web/src/types` 由架构侧统一维护，本层就地声明避免跨波次改类型文件。）
 */
export interface UpdateWorkflowRequest {
  /** 新名称（≤255 字；缺省不改）。 */
  name?: string;
  /** 新描述（缺省不改）。 */
  description?: string | null;
  /** 新状态（缺省不改）。 */
  status?: string | null;
}

/**
 * 运行 Workflow 请求（↔ `schemas/workflow.py::RunWorkflowRequest`）。
 *
 * 🔴 `execution_mode` 仅用 `INLINE`（**同步执行到终态**）；`QUEUED` 依赖尚未装配的
 *    `QueuedRunner`，前端**不**使用。
 */
export interface RunWorkflowRequest {
  /** 执行模式（仅 `INLINE`；服务端缺省亦为 `INLINE`）。 */
  execution_mode?: "INLINE";
  /** 触发来源（人工触发固定 `user`）。 */
  trigger?: string;
  /** 运行输入载荷。 */
  input?: Record<string, unknown>;
}

/**
 * Workflow 服务（`/workflows/*` API，W4 / T2-25 契约；W6 / T2-35 前端接入）。
 *
 * - 定义：创建 / 列表 / 详情 / **更新 / 删除**（B-21：重命名与删除入口）；
 * - 版本：列表（**不可变快照**）；
 * - 发布：一次发布 = 一个新 `workflow_version`（保存画布即调用本方法）；
 * - **运行闭环**：运行（`INLINE` 同步）/ 运行重放快照 / 取消运行。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO（不重复解壳）；
 *    **例外**：`POST /run` 的 JSON 降级分支返回**裸 JSON**（非响应壳），拦截器判定非壳后
 *    原样放行 → `.then((r) => r.data)` 即运行摘要本身。
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
  /** 更新 Workflow（名称 / 描述 / 状态；缺省字段不变）。 */
  update(workflowId: string, payload: UpdateWorkflowRequest): Promise<WorkflowResponse> {
    return api.put<WorkflowResponse>(`/workflows/${workflowId}`, payload).then((r) => r.data);
  },
  /** 删除 Workflow（`204 No Content`，无响应体）。 */
  remove(workflowId: string): Promise<void> {
    return api.delete<null>(`/workflows/${workflowId}`).then(() => undefined);
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
  /**
   * 运行一次 Workflow（`INLINE` = **同步执行到终态**后返回）。
   *
   * 🔴 **必须**显式声明 `Accept: application/json`：后端 `_wants_sse()` 对缺省 / 通配符
   *    亦判定为 SSE，只有显式 json 才落到 JSON 降级分支（返回裸 JSON 摘要）。
   *    axios 默认 Accept 含通配符 → 必须覆盖，否则会拿到 `text/event-stream`。
   */
  run(workflowId: string, payload: RunWorkflowRequest): Promise<WorkflowRunDigest> {
    return api
      .post<WorkflowRunDigest>(`/workflows/${workflowId}/run`, payload, {
        headers: { Accept: "application/json" },
      })
      .then((r) => r.data);
  },
  /** 运行重放快照（Run + 各节点运行态；走统一响应壳）。 */
  getRun(workflowId: string, runId: string): Promise<WorkflowReplay> {
    return api.get<WorkflowReplay>(`/workflows/${workflowId}/runs/${runId}`).then((r) => r.data);
  },
  /** 取消一次运行（置终态 `CANCELLED`；走统一响应壳）。 */
  cancelRun(workflowId: string, runId: string): Promise<WorkflowRunDetail> {
    return api
      .post<WorkflowRunDetail>(`/workflows/${workflowId}/runs/${runId}/cancel`)
      .then((r) => r.data);
  },
};
