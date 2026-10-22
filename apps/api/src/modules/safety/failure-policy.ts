/**
 * T3-13 · 失败策略矩阵（安全补充 §9 的**可执行形态**）。
 *
 * V0.3.0 的矩阵只需要三行（其余行语义上不可达）
 * ------------------------------------------
 *   语义审核**默认不装配**（R3 已拍板：未配置 = 未启用，不是降级）⇒
 *   「语义超时 / 不可用 / 不确定 / policy_version 不匹配」四行在本版**没有触发方**
 *   —— 它们由「已启用的外接 Provider」触发，而那个 Provider 本版不存在。
 *   所以 `failure-policy.ts` 只实现三行 + 一个"语义未配置"的显式分支：
 *
 *   | 形态 | 高 | 中 | 低 |
 *   |---|---|---|---|
 *   | 本地规则引擎故障 | DENY | DENY | DENY |
 *   | 语义未配置（**默认态**） | 不 blanket DENY；登记类别（§9.2，**默认空**）之外按本地规则 ALLOW，**不标 degraded** | 同左 | 同左 |
 *   | 审计写入失败 | 先本地落盘 + 告警；也失败 ⇒ DENY | 同左（但失败时 ALLOW + incident） | 同左 |
 *
 *   ⚠️ 「语义未配置」一行的判定结果与"本地规则正常跑完"**完全一样**（ALLOW 就是 ALLOW），
 *   唯一区别是**不标 `degraded`** —— R3 对齐注：「未启用 ≠ 降级；`degraded` 一词专指
 *   已启用后不可用」。这条被 `safety-degrade.test.mjs` 单独断言（未配置态跑完，
 *   `metadata.degraded === false`）。
 */

import type { RiskLevel } from "@wbtime/security";

/** 语义审核的可用状态（V0.3.0 恒为 `not-configured`）。 */
export type SemanticState = "not-configured" | "ok" | "timeout" | "unavailable" | "uncertain";

/** 失败策略的入参。 */
export interface FailurePolicyInput {
  readonly riskLevel: RiskLevel;
  /** 本地规则引擎是否故障（加载失败 / 抛异常）。 */
  readonly localRulesFailed: boolean;
  readonly semanticState: SemanticState;
}

/** 失败策略的判定结果。 */
export interface FailurePolicyVerdict {
  readonly decision: "ALLOW" | "DENY";
  /** 只有「已启用后不可用」才为 `true`；「未配置」恒 `false`（R3 对齐注）。 */
  readonly degraded: boolean;
  readonly detail: string;
}

/**
 * 按矩阵判定故障时的动作。
 *
 * @returns `null` 表示"没有故障，走正常判定路径"。
 */
export function decideOnFailure(input: FailurePolicyInput): FailurePolicyVerdict | null {
  if (!input.localRulesFailed && input.semanticState === "not-configured") {
    return null;
  }

  // 本地规则故障：**任何等级**都 DENY（§9.1-1：本地规则永不降级 —— 它坏了说明部署异常）。
  if (input.localRulesFailed) {
    return {
      decision: "DENY",
      degraded: false,
      detail: `本地规则引擎故障 ⇒ DENY（fail-closed，等级=${input.riskLevel}）`,
    };
  }

  // 语义未配置：**不是故障、不是降级**（R3 对齐注）。
  // §9.2 的"必须语义判定"清单默认为空 ⇒ 除该空清单外按本地规则放行，不标 degraded。
  if (input.semanticState === "not-configured") {
    return {
      decision: "ALLOW",
      degraded: false,
      detail: "语义审核未配置（=未启用，非降级）：本地规则未命中 ⇒ 按矩阵 ALLOW，不标 degraded",
    };
  }

  // 以下三态在本版不可达（语义审核未装配），但矩阵行保留 —— 装配后无需改本文件。
  if (input.semanticState === "timeout" || input.semanticState === "unavailable") {
    if (input.riskLevel === "high") {
      return { decision: "DENY", degraded: false, detail: `语义服务${input.semanticState} + 高风险 ⇒ DENY` };
    }
    return {
      decision: "ALLOW",
      degraded: true,
      detail: `语义服务${input.semanticState} + ${input.riskLevel}风险 ⇒ ALLOW + degraded 审计`,
    };
  }
  // uncertain
  if (input.riskLevel === "high" || input.riskLevel === "medium") {
    return {
      decision: "DENY",
      degraded: false,
      detail: `语义返回不确定 + ${input.riskLevel}风险 ⇒ DENY`,
    };
  }
  return {
    decision: "ALLOW",
    degraded: true,
    detail: "语义返回不确定 + 低风险 ⇒ ALLOW + advisory 审计",
  };
}
