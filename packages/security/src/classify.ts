/**
 * T3-13 · 类别 / 风险等级的**纯映射**（安全补充 §9 矩阵的行判定）。
 *
 * 为什么放在 `@wbtime/security` 而不是编排层：它是**纯函数**（stage + provenance → 等级），
 * 没有任何 IO；且失败策略矩阵（`apps/api/modules/safety/failure-policy.ts`）与
 * 测试都要用它 —— 放编排层会逼着 security 的测试去引 api 的模块。
 */

/** 安全阶段（`@wbtime/domain` 的 7 值；此处只做映射不重定义）。 */
export type Stage = "input" | "context" | "delegation" | "model_request" | "tool_args" | "tool_result" | "output";

/** 内容来源可信度（§6.3；S2 按 `provenance` 逐段判定）。 */
export type Provenance = "user" | "system" | "untrusted";

/** 风险等级（§9 表头：高 = 有副作用 / 出网 / 凭据 / 进入执行链 / 间接注入入口）。 */
export type RiskLevel = "high" | "medium" | "low";

/**
 * stage（+ 可选 provenance）→ 风险等级。
 *
 * | stage | 等级 | 依据（§9 表后说明） |
 * |---|---|---|
 * | `delegation` | high | 有副作用 / 跨租户 |
 * | `tool_args` | high | 进入执行链 |
 * | `tool_result` | high | `provenance=untrusted` 的注入入口 |
 * | `context`（含 untrusted 段） | high | 间接注入入口 |
 * | `context`（仅 user/system） | medium | 可读、影响下一轮，但全段可信 |
 * | `input` | medium | 同上 |
 * | `model_request` | medium | 同上 |
 * | `output` | low | 只影响展示 |
 */
export function riskLevelOf(stage: Stage, provenance?: Provenance): RiskLevel {
  switch (stage) {
    case "delegation":
    case "tool_args":
    case "tool_result":
      return "high";
    case "context":
      // S2 按 provenance 分档：含 untrusted 段 = 间接注入入口 = 高
      return provenance === "untrusted" ? "high" : "medium";
    case "input":
    case "model_request":
      return "medium";
    case "output":
      return "low";
  }
}
