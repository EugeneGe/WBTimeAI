import { useQuery } from "@tanstack/react-query";

import { auditService } from "@/services/audit";
import { useAuthStore } from "@/stores/authStore";
import type { AuditQuery } from "@/types";

/**
 * 审计 hooks（TanStack Query；W3 / T2-17；设计 §2.18）。
 *
 * queryKey **内联在本文件**（不扩 `lib/query.ts` 的冻结工厂）：审计检索维度
 * （`user_id` / `action` / 分页）随查询参数变化，key 必须携带**规整后**的参数，
 * 否则不同过滤条件会共用缓存。
 */

/** 审计记录 query key 根（结构：`["audit", <规整参数>]`）。 */
export const AUDIT_QUERY_ROOT = "audit";

/**
 * 规整查询参数（剔除空串 / `undefined`；`limit` / `offset` 保留数字）。
 *
 * 目的：让 **queryKey 具备结构稳定性** —— 同一组语义参数（含「未设置」与「空串」）
 * 映射到同一 key，避免缓存抖动。
 */
export function normalizeAuditQuery(params: AuditQuery = {}): AuditQuery {
  const normalized: AuditQuery = {};
  const textKeys = ["user_id", "action", "resource_type", "resource_id", "since", "until"] as const;
  for (const key of textKeys) {
    const value = params[key];
    if (value !== undefined && value !== "") {
      normalized[key] = value;
    }
  }
  if (params.limit !== undefined) {
    normalized.limit = params.limit;
  }
  if (params.offset !== undefined) {
    normalized.offset = params.offset;
  }
  return normalized;
}

/** 由查询参数派生 query key。 */
export function auditLogsQueryKey(params: AuditQuery = {}) {
  return [AUDIT_QUERY_ROOT, normalizeAuditQuery(params)] as const;
}

/**
 * 审计记录列表（`GET /audit`，只读）。
 *
 * ✅ 后端过滤与分页已下推到仓储（V0.4.6 缺陷 L-1 修复），过滤条件作用于**全量**记录，
 *    `offset` 只消费一次（中间页可达）。
 */
export function useAuditLogs(params: AuditQuery = {}) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const normalized = normalizeAuditQuery(params);
  return useQuery({
    queryKey: auditLogsQueryKey(normalized),
    queryFn: () => auditService.list(normalized),
    enabled: isAuthenticated,
  });
}
