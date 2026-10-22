/**
 * T3-13 · 安全规则注册表（**唯一**规则源；R3-16 同源要求的落点）。
 *
 * 「检测 / 脱敏同源」的机制含义（R16 已拍板，逐字）
 * ---------------------------------------------
 *   复用**当前生效的本地规则注册表**（凭据形态 + 已启用的 PII 规则）驱动检测与脱敏，
 *   `scan_sensitive` 只是**凭据子集**。也就是说：
 *
 *   - 检测（{@link detectSensitive}）与脱敏（{@link redactSensitive}）读的是**同一张表**、
 *     跑的是**同一批正则**、返回的是**同一批命中**；
 *   - 断言形式：**「检测命中集合 == 脱敏命中集合」**（同一段文本两个函数返回的
 *     `id + start + end` 完全一致）—— 这正是 R3-16 影响判据 ③ 的机器形态；
 *   - 违反同源的方式只有一种：脱敏用另一套正则。所以本文件**只有一个正则表**，
 *     `redactSensitive` 不允许自带任何 pattern。
 *
 * 规则范围（R1 已拍板）：**凭据形态 + PII 形态 + 少量确定性模式**。
 * **不是**完整违禁词库（N-1）—— 覆盖范围与已知漏检形态在文件尾声明。
 *
 * 底线项（R2 / R3-14）：标记 `baseline: true` 的规则在 `safety.local_rules` 开关
 * `enabled=false` 时**仍然判定**（"一关全关"被 `safety-degrade.test.mjs` 的双断言挡住）。
 */

import { TOKEN_VALUE_PATTERNS } from "./scan-sensitive.js";

/** 规则类别。 */
export type SafetyCategory = "credential" | "pii" | "injection";

/** 一条本地安全规则。 */
export interface SafetyRule {
  /** 规则标识（含版本，进 `audit_log.metadata.rule_id`）。 */
  readonly id: string;
  readonly category: SafetyCategory;
  readonly pattern: RegExp;
  /** 底线项：规则集开关关闭时仍然判定。 */
  readonly baseline: boolean;
}

/**
 * 本地规则注册表（V0.3.0 的全部规则；**顺序即判定顺序**，也是 audit 里 hits 的次序）。
 *
 * 8 条：凭据 5（**逐字复用** `scan_sensitive` 的 5 条 token 模式 —— "同源"的字面含义）+
 * PII 3（身份证 / 手机 / 邮箱，R1 的"PII 形态（规则就绪后）"）+ 注入 2（确定性模式）。
 */
export const SAFETY_RULES: readonly SafetyRule[] = Object.freeze([
  // ---- 凭据（底线项：与 `scan_sensitive` 同源的 5 条）-----------------------
  { id: "cred.openai_sk.v1", category: "credential", pattern: TOKEN_VALUE_PATTERNS[0], baseline: true },
  { id: "cred.github_token.v1", category: "credential", pattern: TOKEN_VALUE_PATTERNS[1], baseline: true },
  { id: "cred.aws_ak.v1", category: "credential", pattern: TOKEN_VALUE_PATTERNS[2], baseline: true },
  { id: "cred.slack_token.v1", category: "credential", pattern: TOKEN_VALUE_PATTERNS[3], baseline: true },
  { id: "cred.private_key.v1", category: "credential", pattern: TOKEN_VALUE_PATTERNS[4], baseline: true },
  // ---- PII（非底线：可被规则集开关关闭）------------------------------------
  { id: "pii.cn_id_card.v1", category: "pii", pattern: /[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]/, baseline: false },
  { id: "pii.cn_mobile.v1", category: "pii", pattern: /(?<!\d)1[3-9]\d{9}(?!\d)/, baseline: false },
  { id: "pii.email.v1", category: "pii", pattern: /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, baseline: false },
  // ---- 确定性注入模式（非底线；S6 的间接注入检查用）------------------------
  { id: "inj.ignore_instructions.v1", category: "injection", pattern: /(?:ignore (?:all )?(?:previous|prior) instructions|忽略(?:之前|以上)(?:的)?(?:所有)?指令)/i, baseline: false },
  { id: "inj.system_prompt_probe.v1", category: "injection", pattern: /(?:reveal|print|output) your (?:system )?prompt/i, baseline: false },
] as const);

/** 一次命中。 */
export interface SafetyHit {
  readonly ruleId: string;
  readonly category: SafetyCategory;
  /** 命中起点（`String.prototype.matchAll` 的 `index`）。 */
  readonly start: number;
  readonly end: number;
  /** 命中的**形态样本长度**（**不含原文** —— P-1：敏感原文不进任何持久层）。 */
  readonly length: number;
}

/** 判定选项。 */
export interface DetectOptions {
  /** 只跑这些类别（缺省全部）。 */
  readonly categories?: readonly SafetyCategory[];
  /** 只跑这些规则 id（开关关闭的非底线规则由此排除）。 */
  readonly enabledRuleIds?: readonly string[] | null;
}

/**
 * 检测：返回**全部命中**（同一规则可命中多次）。
 *
 * 纯函数、零 IO、不抛 —— 命中不是错误，是**事实**；把命中变成错误的是挂点的策略。
 */
export function detectSensitive(text: string, options: DetectOptions = {}): SafetyHit[] {
  const hits: SafetyHit[] = [];
  for (const rule of SAFETY_RULES) {
    if (!ruleEnabled(rule, options)) continue;
    const matcher = new RegExp(rule.pattern.source, rule.pattern.flags.includes("g") ? rule.pattern.flags : `${rule.pattern.flags}g`);
    for (const match of text.matchAll(matcher)) {
      if (match.index === undefined) continue;
      hits.push({
        ruleId: rule.id,
        category: rule.category,
        start: match.index,
        end: match.index + match[0].length,
        length: match[0].length,
      });
    }
  }
  // 按位置排序（脱敏替换必须从后往前，所以这里给升序，替换时反转）。
  return hits.sort((a, b) => a.start - b.start || a.end - b.end);
}

/** 规则是否参与本次判定。 */
function ruleEnabled(rule: SafetyRule, options: DetectOptions): boolean {
  if (options.categories !== undefined && !options.categories.includes(rule.category)) {
    return false;
  }
  if (options.enabledRuleIds !== undefined && options.enabledRuleIds !== null) {
    // 底线项无视开关（R3-14 ②：平台底线项仍强制）
    if (rule.baseline) return true;
    return options.enabledRuleIds.includes(rule.id);
  }
  return true;
}

/** 脱敏结果。 */
export interface RedactResult {
  /** 脱敏后的文本（命中的片段被替换为 `[REDACTED:<category>:<ruleId>]`）。 */
  readonly text: string;
  /** 命中列表（**与 `detectSensitive` 同源**：同文本同选项 ⇒ 两个函数返回的命中集合相等）。 */
  readonly hits: readonly SafetyHit[];
}

/**
 * 脱敏：与检测**同源**的纯函数。
 *
 * 实现就是"先检测、再按命中位置替换"—— 不引入任何第二条正则路径，
 * 这正是 R3-16 要求的"同一注册表驱动检测与脱敏"的字面落法。
 *
 * 替换从**后往前**（先替换靠后的命中），避免前面的替换移动后面命中的位置。
 *
 * @param text 原文。
 * @param options 与 {@link detectSensitive} 相同。
 */
export function redactSensitive(text: string, options: DetectOptions = {}): RedactResult {
  const hits = detectSensitive(text, options);
  if (hits.length === 0) {
    return { text, hits: [] };
  }

  const ruleById = new Map(SAFETY_RULES.map((rule) => [rule.id, rule]));
  let result = text;
  for (const hit of [...hits].reverse()) {
    const rule = ruleById.get(hit.ruleId);
    const marker = `[REDACTED:${rule?.category ?? "unknown"}:${hit.ruleId}]`;
    result = result.slice(0, hit.start) + marker + result.slice(hit.end);
  }
  return { text: result, hits };
}

/** 已注册的规则 id（供开关读取方核对"关掉的 id 是不是真的存在"）。 */
export function registeredRuleIds(): string[] {
  return SAFETY_RULES.map((rule) => rule.id);
}

/** 底线规则 id（R3-14 的"平台底线项仍强制"清单）。 */
export function baselineRuleIds(): string[] {
  return SAFETY_RULES.filter((rule) => rule.baseline).map((rule) => rule.id);
}

/**
 * 覆盖范围声明（N-1：规则库必须随版本声明覆盖范围与已知漏检形态）。
 *
 * **已知漏检（如实登记，不得声称"完整"）**：
 *   - 编码变体（base64 / hex / URL 编码）的凭据 **不在**表内；
 *   - 非中国身份证 / 非手机号的 PII（护照、社保号）**不在**表内；
 *   - 语义级注入（"请扮演一个没有限制的 AI"）**不在**表内 —— 那需要语义审核（本版默认不装配）。
 */
export const COVERAGE_STATEMENT = {
  version: "1",
  covers: ["credential:openai-sk,github-token,aws-ak,slack-token,private-key", "pii:cn-id-card,cn-mobile,email", "injection:instruction-override,prompt-probe"],
  knownGaps: ["encoded-secrets", "non-cn-pii", "semantic-injection"],
} as const;
