/**
 * T3-13 · `SafetyGate` —— 六挂点统一入口（R3-17：本版 6 个，S3 **不存在**且被门禁断言为 0）。
 *
 * 判定流水（每个挂点完全相同，差别只在 stage 与该阶段**允许的动作**）
 * ---------------------------------------------------------------
 *   1. 读开关（`safety.local_rules`，无行 = 开；`enabled=false` ⇒ 只有底线项判定）；
 *   2. 本地规则检测（`@wbtime/security.detectSensitive`）—— 抛错 ⇒ 失败策略矩阵；
 *   3. 命中 ⇒ 按「阶段允许动作 × 命中类别」折成 `DENY` / `REDACT`；
 *      未命中 ⇒ `ALLOW`（**审计照样落** —— "零判定记录"的反例要求每个 stage 有行）；
 *   4. 审计落 `audit_log`（`action='safety.decision'`，metadata 按 §10.2）。
 *
 * 两条折算规则（容易写错的地方）
 * -------------------------
 *   ① **注入类命中恒 `DENY`**：注入不是"敏感信息"，脱敏后放行没有意义 ——
 *      `ignore previous instructions` 被 `[REDACTED]` 掉并不会让攻击消失。
 *   ② **`model_request` 阶段无 `REDACT`**（§7 矩阵：S4 可用动作 = ALLOW/DENY）：
 *      改模型请求内容 = 改路由/改意图，选路归 `ModelGateway`，内容侧只能放行或拒绝。
 *      其余五个阶段：凭据 / PII 命中 ⇒ `REDACT`（若开关开），否则 `DENY`。
 *
 * `REDACT` 关闭 ≠ 放行（R3-16）：命中回落 `DENY`，**不得 `ALLOW`** ——
 * 由 `safety-degrade.test.mjs` 断言。
 */

import {
  baselineRuleIds,
  detectSensitive,
  redactSensitive,
  riskLevelOf,
  type Provenance,
  type SafetyHit,
} from "@wbtime/security";
import type { SafetyStage } from "@wbtime/domain";
import type { DrizzleDatabase, SqlDialect } from "@wbtime/db";

import { writeSafetyAudit } from "./audit.js";
import { decideOnFailure } from "./failure-policy.js";
import { readLocalRulesFlag } from "./feature.js";

/** 本版策略版本（进 `metadata.policy_version`；变更 ⇒ `recheck_of` 语义触发重判）。 */
export const SAFETY_POLICY_VERSION = "2026-10-22.a";
/** 规则集版本（与 policy_version 正交；规则表变更 ⇒ +1）。 */
export const SAFETY_RULE_SET_VERSION = "1";

/** 各阶段**允许**的决策（§7 矩阵「可用动作」列；未列出的决策在该阶段不可用）。 */
export const STAGE_ALLOWED_DECISIONS: Readonly<
  Record<SafetyStage, readonly ("ALLOW" | "DENY" | "REDACT" | "REQUIRE_APPROVAL")[]>
> = Object.freeze({
  input: ["ALLOW", "DENY", "REDACT", "REQUIRE_APPROVAL"],
  context: ["ALLOW", "REDACT", "DENY"],
  // S3 本版不装配（R3-17）—— 值域保留，供门禁断言「行数 == 0 是期望」。
  delegation: ["ALLOW", "DENY"],
  model_request: ["ALLOW", "DENY"],
  tool_args: ["ALLOW", "DENY", "REQUIRE_APPROVAL", "REDACT"],
  tool_result: ["ALLOW", "REDACT", "DENY"],
  output: ["ALLOW", "REDACT", "DENY", "REQUIRE_APPROVAL"],
});

/** evaluate 的入参。 */
export interface SafetyEvaluateInput {
  readonly stage: SafetyStage;
  readonly content: string;
  readonly provenance?: Provenance;
  readonly sourceKind?: string;
  /** `REDACT` 开关（缺省 `true`；关闭 ⇒ 命中回落 `DENY`，**不得 ALLOW**）。 */
  readonly redactEnabled?: boolean;
  readonly runId?: string | null;
  readonly toolCallId?: string | null;
  readonly requestId: string;
  readonly conversationId?: string | null;
  /** 流式期终态复核才发现违规时置 `true`（①′ 反例 #17 承接）。 */
  readonly incident?: boolean;
  readonly deliveredUnits?: number;
}

/** 判定结果。 */
export interface SafetyVerdict {
  readonly decision: "ALLOW" | "DENY" | "REDACT";
  readonly hits: readonly SafetyHit[];
  readonly degraded: boolean;
  readonly disabled: boolean;
  readonly detail: string;
  /** `decision === "REDACT"` 时给出脱敏后的文本（与检测**同源** —— R3-16）。 */
  readonly redactedContent?: string;
}

/** 依赖。 */
export interface SafetyGateDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
  readonly tenantId: string;
}

/** 六挂点统一入口。 */
export class SafetyGate {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #tenantId: string;

  constructor(deps: SafetyGateDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect;
    this.#tenantId = deps.tenantId;
  }

  /**
   * 判定一个挂点的内容。
   *
   * @returns 判定结果（**审计已同步落库** —— 「不沉默」原则 §9.1-5）。
   */
  async evaluate(input: SafetyEvaluateInput): Promise<SafetyVerdict> {
    const startedAt = Date.now();
    const stage = input.stage;
    const provenance = input.provenance ?? (stage === "tool_result" ? "untrusted" : "user");
    const riskLevel = riskLevelOf(stage, provenance);
    const redactEnabled = input.redactEnabled !== false;

    // ---- 1. 开关（R3-14）------------------------------------------------
    const flag = await readLocalRulesFlag(this.#db, this.#dialect);

    // ---- 2. 本地规则检测（含故障折算）------------------------------------
    let hits: SafetyHit[];
    let localFailed = false;
    try {
      hits =
        flag.enabled === false
          ? // 显式关闭 ⇒ 只有**底线项**仍判定（防"一关全关"）
            detectSensitive(input.content, { enabledRuleIds: baselineRuleIds() })
          : detectSensitive(input.content);
    } catch (error) {
      localFailed = true;
      const verdict = decideOnFailure({ riskLevel, localRulesFailed: true, semanticState: "not-configured" });
      const decision = verdict?.decision ?? "DENY";
      await this.#audit(input, decision, [], {
        degraded: false,
        disabled: flag.disabled,
        localFailed: true,
      });
      return {
        decision: decision as SafetyVerdict["decision"],
        hits: [],
        degraded: false,
        disabled: flag.disabled,
        detail: `本地规则故障：${error instanceof Error ? error.message : String(error)}`,
      };
    }

    // ---- 3. 折算（命中 → 决策）-------------------------------------------
    // 注意：本地规则**抛错**的路径已在上面 `catch` 里 `return` 了，所以这里 `hits`
    // 恒为已求得的结果 —— 早先这里还有一个 `if (localFailed)` 分支（AUD-09：不可达死码），
    // 已删除；行为不变。
    let decision: "ALLOW" | "DENY" | "REDACT";
    let detail: string;
    let redactedContent: string | undefined;

    if (hits.length === 0) {
      decision = "ALLOW";
      detail = "本地规则未命中";
      // 「语义未配置」的显式分支（R3 对齐注：不标 degraded）
      const semantic = decideOnFailure({ riskLevel, localRulesFailed: false, semanticState: "not-configured" });
      detail = semantic?.detail ?? detail;
    } else {
      const first = hits[0];
      const injectable = hits.some((hit) => hit.category === "injection");
      const stageAllowsRedact = STAGE_ALLOWED_DECISIONS[stage].includes("REDACT");

      if (injectable) {
        decision = "DENY";
        detail = `注入类规则命中（${first.ruleId}）⇒ DENY（注入不可脱敏放行）`;
      } else if (stageAllowsRedact && redactEnabled) {
        decision = "REDACT";
        redactedContent = redactSensitive(input.content).text;
        detail = `敏感信息命中（${first.ruleId}）⇒ REDACT（同源脱敏）`;
      } else if (stageAllowsRedact && !redactEnabled) {
        // REDACT 关闭 ⇒ 回落 DENY（**不得 ALLOW**，R3-16）
        decision = "DENY";
        detail = `敏感信息命中（${first.ruleId}）且 REDACT 已关闭 ⇒ 回落 DENY（不得放行）`;
      } else {
        decision = "DENY";
        detail = `命中（${first.ruleId}）且阶段 ${stage} 不允许 REDACT ⇒ DENY`;
      }
    }

    // ---- 4. 审计（不沉默原则）--------------------------------------------
    // R3-14 ②：显式关闭 ⇒ `disabled=true` 且 `degraded=true`（降级审计）。
    // 两条裁决的并读：R3 对齐注说"未配置外接 ≠ 降级"，但"规则集被关"是**显式降级**，
    // 两者不冲突 —— degraded 的两种来源：外接不可用（本版不可达）/ 规则集被关（本版可达）。
    await this.#audit(input, decision, hits, {
      degraded: flag.disabled,
      disabled: flag.disabled,
      localFailed,
      redactEnabled,
    });

    return {
      decision,
      hits,
      // AUD-07：判定对象与审计必须**同一口径**。这里原先是恒 `false`，而上面的审计写
      // `degraded: flag.disabled` ⇒ 「显式关闭规则集」在库里是降级、在返回值里不是。
      // 调用方（`SafetyHooks` / run 终态）据此判断"这次判定是否可信"，
      // 两个口径不一致等于把降级**藏了一半**。
      degraded: flag.disabled,
      disabled: flag.disabled,
      detail,
      ...(redactedContent === undefined ? {} : { redactedContent }),
    };
  }

  /** 落审计（所有分支都走这里 ⇒ 「该 stage 行数 == 0」的反例才有意义）。 */
  async #audit(
    input: SafetyEvaluateInput,
    decision: string,
    hits: readonly SafetyHit[],
    context: {
      degraded: boolean;
      disabled: boolean;
      localFailed?: boolean;
      redactEnabled?: boolean;
      failDetail?: string;
    }
  ): Promise<void> {
    const first = hits[0];
    await writeSafetyAudit(this.#db, this.#dialect, {
      tenantId: this.#tenantId,
      stage: input.stage,
      // decision 由调用方折算；本地规则故障时由 failure-policy 给出（恒 DENY）
      decision: (context.localFailed === true ? "DENY" : decision) as SafetyVerdict["decision"],
      reasonCode: context.localFailed === true ? "SAFETY_ENGINE_FAULT" : first ? "SAFETY_RULE_HIT" : "SAFETY_NO_HIT",
      ruleId: first?.ruleId ?? null,
      category: first?.category ?? null,
      policyVersion: SAFETY_POLICY_VERSION,
      ruleSetVersion: SAFETY_RULE_SET_VERSION,
      degraded: context.degraded,
      disabled: context.disabled,
      cacheHit: false,
      content: input.content,
      hitCount: hits.length,
      provenance: input.provenance ?? "user",
      sourceKind: input.sourceKind ?? "agent_executor",
      durationMs: 0,
      runId: input.runId ?? null,
      toolCallId: input.toolCallId ?? null,
      requestId: input.requestId,
      conversationId: input.conversationId ?? null,
      incident: input.incident,
      deliveredUnits: input.deliveredUnits,
    });
  }
}
