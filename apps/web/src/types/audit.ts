/**
 * 审计 DTO（`/audit` API，W3 / T2-17；设计 §2.18 / §2.12）。
 *
 * 契约对齐后端 `wbtime_ai_api.schemas.audit`（**逐字** snake_case）：
 * `GET /audit` → `AuditLogResponse[]`（只需登录，无 capability 码）。
 *
 * ✅ 后端 `list_audit`（`routers/v1/audit.py`）的过滤与分页已**整体下推**到仓储
 *    （`AuditRepository.list_page` → SQL `WHERE` + `LIMIT` / `OFFSET`，V0.4.6 缺陷 L-1 修复）：
 *    `offset` 只被消费一次，命中的中间页记录**可达**，`action` / 时间等条件作用于**全量**记录。
 *    （修复前为「先 `list_by_tenant(limit=offset+limit)` 拉取 → 内存过滤 → 再切片」，
 *    会永久丢掉窗口外的命中记录。）
 */

/** 审计结果（后端为自由字符串；`SUCCESS` / `FAILURE` 为已知取值）。 */
export type AuditOutcome = "SUCCESS" | "FAILURE";

/** 审计记录响应（**四要素**：who / action / resource / outcome）。 */
export interface AuditLogResponse {
  /** 记录标识。 */
  id: string;
  /** 租户标识。 */
  tenant_id: string | null;
  /** who（用户，可空）。 */
  user_id: string | null;
  /** who（Agent，可空）。 */
  agent_id: string | null;
  /** 运行标识（可空）。 */
  run_id: string | null;
  /** action（动作）。 */
  action: string;
  /** resource 类型（可空）。 */
  resource_type: string | null;
  /** resource 标识（可空）。 */
  resource_id: string | null;
  /** outcome（结果；缺省 `SUCCESS`）。 */
  outcome: string;
  /** 耗时（毫秒，可空）。 */
  duration_ms: number | null;
  /** 请求标识（可空）。 */
  request_id: string | null;
  /** 创建时间（ISO8601，可空）。 */
  created_at: string | null;
}

/**
 * 审计查询参数（对齐后端 query 约束）。
 *
 * - `limit`：1–200，后端缺省 50；
 * - `offset`：≥ 0；
 * - `since` / `until`：ISO8601。
 */
export interface AuditQuery {
  /** 按 who（用户）过滤（**精确匹配**）。 */
  user_id?: string;
  /** 按 action 过滤（**精确匹配**）。 */
  action?: string;
  /** 按 resource 类型过滤（**精确匹配**）。 */
  resource_type?: string;
  /** 按 resource 标识过滤（**精确匹配**）。 */
  resource_id?: string;
  /** 起始时间（ISO8601）。 */
  since?: string;
  /** 结束时间（ISO8601）。 */
  until?: string;
  /** 分页大小（1–200）。 */
  limit?: number;
  /** 分页偏移（≥ 0）。 */
  offset?: number;
}
