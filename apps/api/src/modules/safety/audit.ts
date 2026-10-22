/**
 * T3-13 · `audit_log` 落库（§10：唯一审计真相源，**零 DDL**）。
 *
 * 两条最容易写错的口径（§10.2 逐字）
 * -------------------------------
 *   ① **`outcome` 是「被审计动作的结果」，不是「安全决策是什么」**：
 *      `ALLOW`/`REDACT`/`REQUIRE_APPROVAL` ⇒ `SUCCESS`，`DENY` ⇒ `FAILURE`。
 *      真实决策只认 `metadata.decision`。
 *   ② **`content_hash` 是完整 sha256（64 hex），不是前缀截断**（P-2）。
 *      且**不落原文**（P-1）：审计里只有 hash + 长度 + 类别计数。
 *
 * 审计写入失败**不抛**（§9.1-6：审计不被 blanket 阻断）。
 */

import { createHash } from "node:crypto";

import { AuditLogRepo } from "@wbtime/db";
import type { DrizzleDatabase, SqlDialect } from "@wbtime/db";

/** 审计入参（字段名对齐 `audit_log.metadata` 清单，§10.2）。 */
export interface SafetyAuditInput {
  readonly tenantId: string;
  readonly stage: string;
  readonly decision: "ALLOW" | "DENY" | "REDACT" | "REQUIRE_APPROVAL";
  readonly reasonCode: string;
  readonly ruleId: string | null;
  readonly category: string | null;
  readonly policyVersion: string;
  readonly ruleSetVersion: string;
  readonly degraded: boolean;
  readonly disabled: boolean;
  readonly cacheHit: boolean;
  /** 被判定的原文（**只取 hash 与长度，绝不落库**）。 */
  readonly content: string;
  readonly hitCount: number;
  readonly provenance: "user" | "system" | "untrusted";
  readonly sourceKind: string;
  readonly durationMs: number;
  readonly runId?: string | null;
  readonly toolCallId?: string | null;
  readonly requestId: string;
  readonly conversationId?: string | null;
  readonly incident?: boolean;
  readonly deliveredUnits?: number;
  readonly advisory?: boolean;
}

/** 四值决策 → `outcome`（§10.2 映射表，逐字）。 */
export function outcomeFor(decision: SafetyAuditInput["decision"]): "SUCCESS" | "FAILURE" {
  if (decision === "DENY") return "FAILURE";
  return "SUCCESS";
}

/** 完整 sha256（64 hex；P-2）。 */
export function contentHashOf(content: string): string {
  return createHash("sha256").update(content, "utf8").digest("hex");
}

/** 落一条 `safety.decision` 审计（失败不抛）。 */
export async function writeSafetyAudit(
  db: DrizzleDatabase,
  dialect: SqlDialect,
  input: SafetyAuditInput
): Promise<boolean> {
  const metadata = {
    stage: input.stage,
    decision: input.decision,
    reason_code: input.reasonCode,
    rule_id: input.ruleId,
    category: input.category,
    policy_version: input.policyVersion,
    rule_set_version: input.ruleSetVersion,
    degraded: input.degraded,
    disabled: input.disabled,
    cache_hit: input.cacheHit,
    content_hash: contentHashOf(input.content),
    content_len: input.content.length,
    hit_count: input.hitCount,
    provenance: input.provenance,
    source_kind: input.sourceKind,
    conversation_id: input.conversationId ?? null,
    incident: input.incident ?? false,
    delivered_units: input.deliveredUnits ?? 0,
    advisory: input.advisory ?? false,
    recheck_of: null,
    exception_id: null,
    approver_id: null,
  };

  return new AuditLogRepo(db, dialect).create({
    tenantId: input.tenantId,
    action: "safety.decision",
    resourceType: "safety_stage",
    resourceId: input.stage,
    outcome: outcomeFor(input.decision),
    durationMs: input.durationMs,
    requestId: input.requestId,
    runId: input.runId ?? null,
    toolCallId: input.toolCallId ?? null,
    metadata,
  });
}
