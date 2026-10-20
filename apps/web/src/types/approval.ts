/**
 * 审批域前端 DTO（W10 / T2-49 契约；`/approvals/*` API）。
 *
 * 与后端 `apps/api/src/wbtime_ai_api/schemas/approval.py::ApprovalResponse` 严格对齐；
 * 统一响应壳由 `lib/api.ts` 拦截器解壳，服务层直接拿到业务 DTO。
 *
 * 🔴 状态口径以领域枚举为准
 *    （`packages/domain/src/wbtime_ai_domain/approval.py::ApprovalStatus`）：
 *    `PENDING` / `APPROVED` / `REJECTED` / `EXPIRED`（终态三者不可再转移）。
 * 🔴 `GET /approvals` **只返回 `PENDING`**；决议 / 过期记录仅经详情端点可取。
 * 🔴 决议（approve / reject）**无请求体**——决议人取当前登录用户，状态由端点语义固定。
 */

/** 审批状态（与后端 `ApprovalStatus` 同口径的字符串字面量联合）。 */
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED";

/**
 * 审批记录响应（`Approval` 领域实体的对外视图）。
 *
 * 字段与后端 pydantic 模型一一对应（**全可选的可空字段**在后端均有默认值，
 * 故此处按「可能为 `null`」声明，渲染层需自行兜底）。
 */
export interface ApprovalResponse {
  /** 审批 id。 */
  id: string;
  /** 所属租户（跨租户访问 → 404，隔离 I-1）。 */
  tenant_id?: string | null;
  /** 主体类型（`tool` / `mcp` / `workflow_node`）。 */
  subject_type: string;
  /** 主体标识（如工作流节点 id）。 */
  subject_ref: string;
  /** 发起人用户 id。 */
  requested_by?: string | null;
  /** 当前状态（缺省 `PENDING`）。 */
  status: ApprovalStatus | string;
  /** 决议人用户 id（未决议 → `null`）。 */
  decided_by?: string | null;
  /** 决议时刻（未决议 → `null`）。 */
  decided_at?: string | null;
  /** 审批载荷（结构由主体类型决定，前端只做只读 JSON 预览）。 */
  payload: Record<string, unknown>;
  /** 过期时刻（缺省 / `null` → 不过期）。 */
  expires_at?: string | null;
  /** 创建时间。 */
  created_at?: string | null;
  /** 更新时间。 */
  updated_at?: string | null;
}

/**
 * 待办列表查询参数（`GET /approvals?limit=&offset=`）。
 *
 * 后端约束：`limit` ∈ [1, 200]（默认 50），`offset` ≥ 0（默认 0）。
 */
export interface ApprovalsQuery {
  /** 分页大小（默认 50）。 */
  limit?: number;
  /** 分页偏移（默认 0）。 */
  offset?: number;
}
