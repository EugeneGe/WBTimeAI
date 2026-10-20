import { api } from "@/lib/api";
import type { AuditLogResponse, AuditQuery } from "@/types";

/**
 * 审计服务（`/audit/*` API，W3 / T2-17；设计 §2.18）。
 *
 * `GET /audit` → 审计记录（**只读消费**，只需登录，无 capability 码）。
 *
 * ✅ 后端过滤（`user_id` / `action` / `resource_*` / `since` / `until`）与分页
 *    （`limit` / `offset`）已**整体下推**到仓储（SQL `WHERE` + `LIMIT` / `OFFSET`，
 *    V0.4.6 缺陷 L-1 修复），故条件作用于**全量记录**、`offset` 只消费一次，中间页可达。
 */

/** 将查询参数规整为 axios `params`（剔除 `undefined` / 空串，保持后端字段名）。 */
function toRequestParams(params: AuditQuery): Record<string, string | number> {
  const query: Record<string, string | number> = {};
  if (params.user_id !== undefined && params.user_id !== "") {
    query.user_id = params.user_id;
  }
  if (params.action !== undefined && params.action !== "") {
    query.action = params.action;
  }
  if (params.resource_type !== undefined && params.resource_type !== "") {
    query.resource_type = params.resource_type;
  }
  if (params.resource_id !== undefined && params.resource_id !== "") {
    query.resource_id = params.resource_id;
  }
  if (params.since !== undefined && params.since !== "") {
    query.since = params.since;
  }
  if (params.until !== undefined && params.until !== "") {
    query.until = params.until;
  }
  if (params.limit !== undefined) {
    query.limit = params.limit;
  }
  if (params.offset !== undefined) {
    query.offset = params.offset;
  }
  return query;
}

export const auditService = {
  /** 审计记录列表（按创建时间倒序；支持过滤 + 分页）。 */
  list(params: AuditQuery = {}): Promise<AuditLogResponse[]> {
    return api
      .get<AuditLogResponse[]>("/audit", { params: toRequestParams(params) })
      .then((r) => r.data);
  },
};
