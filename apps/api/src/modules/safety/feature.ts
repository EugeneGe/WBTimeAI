/**
 * T3-13 · R3-14 平台级开关：`safety.local_rules`（`feature_flag` **无行 = 默认开**）。
 *
 * 三个口径（裁定 R3-14 逐字）
 * -----------------------
 *   ① 无行 ⇒ 规则生效（命中用例 DENY）；
 *   ② 写入 `enabled=false` ⇒ 该规则不再判定 + `audit_log` 有 `disabled=true` 行 +
 *      **底线项**（凭据形态）仍 DENY（**双断言**，防"一关全关"）；
 *   ③ **不存在** `safety.local_rules.<tenant>` 形态的租户级键 —— 租户开关登记为 1.1+。
 */

import { FeatureFlagRepo } from "@wbtime/db";
import type { DrizzleDatabase, SqlDialect } from "@wbtime/db";

/** 开关名（唯一，`feature_flag.name` 有唯一索引）。 */
export const SAFETY_LOCAL_RULES_FLAG = "safety.local_rules";

/** 读取结果。 */
export interface LocalRulesFlag {
  /** 规则集是否判定（无行 = `true`）。 */
  readonly enabled: boolean;
  /** 是否为**显式关闭**（审计 `metadata.disabled=true` 只在这一情形为真）。 */
  readonly disabled: boolean;
}

/** 读开关（**每次读库** —— `GET /settings/features` 改完立刻生效）。 */
export async function readLocalRulesFlag(
  db: DrizzleDatabase,
  dialect: SqlDialect
): Promise<LocalRulesFlag> {
  const row = await new FeatureFlagRepo(db, dialect).findByName(SAFETY_LOCAL_RULES_FLAG);
  if (row === null) {
    return { enabled: true, disabled: false };
  }
  return { enabled: row.enabled, disabled: !row.enabled };
}
