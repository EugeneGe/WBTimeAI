// @wbtime/api · usage 归一化（T3-02）。
//
// 口径来自 py 线 oracle（`_old/.../wbtime_ai_model/providers/base.py:74`）：
//   `normalize_usage` 只输出 `{prompt_tokens, completion_tokens, total_tokens}` 三键，
//   **源里没有的键不写**（不是补 0），空/`None` ⇒ `{}`。
//
// V0.3.0 的缓存观测是**可选超集**（增量纪律：零 DDL、零契约变更）：
//   * `cache_read_tokens` / `cache_write_tokens` 只在厂商**真的给了**才写；
//   * 未提供 ⇒ **整个键不出现**（不是写 0）—— 否则"没命中缓存"与"厂商没报"会混为一谈；
//   * **fake Provider 一律不产出 cache 键**（伪造指标是本项目头号事故类型，R3-19）。

/** 三个基础用量键（顺序即序列化顺序）。 */
export const USAGE_KEYS = ["prompt_tokens", "completion_tokens", "total_tokens"] as const;

/** 缓存用量的可选超集键。 */
export const CACHE_USAGE_KEYS = ["cache_read_tokens", "cache_write_tokens"] as const;

export type NormalizedUsage = {
  readonly prompt_tokens?: number;
  readonly completion_tokens?: number;
  readonly total_tokens?: number;
  readonly cache_read_tokens?: number;
  readonly cache_write_tokens?: number;
};

/** 是不是缓存键（fake provider 断言用）。 */
export function isCacheUsageKey(key: string): boolean {
  return (CACHE_USAGE_KEYS as readonly string[]).includes(key);
}

function asInt(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : null;
}

interface V4TokenGroup {
  readonly total?: unknown;
  readonly noCache?: unknown;
  readonly cacheRead?: unknown;
  readonly cacheWrite?: unknown;
}

interface FlatUsage {
  readonly prompt_tokens?: unknown;
  readonly completion_tokens?: unknown;
  readonly total_tokens?: unknown;
  readonly inputTokens?: unknown;
  readonly outputTokens?: unknown;
  readonly totalTokens?: unknown;
  readonly cache_read_tokens?: unknown;
  readonly cache_write_tokens?: unknown;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * 归一化用量。同时接受两种入参形态：
 *   1. **AI SDK v4 嵌套**：`{ inputTokens: { total }, outputTokens: { total }, totalTokens }`
 *   2. **py 线扁平**：`{ prompt_tokens, completion_tokens, total_tokens }`
 *
 * 返回对象**只含**有值的键（空对象是合法结果，不是错误）。
 */
export function normalizeUsage(raw: unknown): NormalizedUsage {
  if (!isObject(raw)) return {};

  const flat = raw as FlatUsage;
  const inputGroup = isObject(flat.inputTokens) ? (flat.inputTokens as V4TokenGroup) : null;
  const outputGroup = isObject(flat.outputTokens) ? (flat.outputTokens as V4TokenGroup) : null;

  const prompt = asInt(flat.prompt_tokens) ?? asInt(inputGroup?.total);
  const completion = asInt(flat.completion_tokens) ?? asInt(outputGroup?.total);
  // ⚠️ **不自动求和**：py oracle 的 `normalize_usage` 只复制厂商已存在的键，
  // 缺 `total` 就保持缺（"我们算的" 与 "厂商报的" 不能混）。需要合计时用 `sumUsage`。
  const total = asInt(flat.total_tokens) ?? asInt(flat.totalTokens);

  const usage: { -readonly [K in keyof NormalizedUsage]: NormalizedUsage[K] } = {};
  if (prompt !== null) usage.prompt_tokens = prompt;
  if (completion !== null) usage.completion_tokens = completion;
  if (total !== null) usage.total_tokens = total;

  // 缓存用量：**只在该层真的报数时才写**（`0` 是合法值，`undefined` 不算）。
  const cacheRead = asInt(inputGroup?.cacheRead) ?? asInt(flat.cache_read_tokens);
  const cacheWrite = asInt(inputGroup?.cacheWrite) ?? asInt(flat.cache_write_tokens);
  if (cacheRead !== null) usage.cache_read_tokens = cacheRead;
  if (cacheWrite !== null) usage.cache_write_tokens = cacheWrite;

  return usage;
}

/** 合并两份额用量（逐键相加；只对"两边都出现"或"单边出现"的键求和）。 */
export function sumUsage(left: NormalizedUsage, right: NormalizedUsage): NormalizedUsage {
  const out: { -readonly [K in keyof NormalizedUsage]: NormalizedUsage[K] } = {};
  for (const key of [...USAGE_KEYS, ...CACHE_USAGE_KEYS]) {
    const a = left[key];
    const b = right[key];
    if (a === undefined && b === undefined) continue;
    out[key] = (a ?? 0) + (b ?? 0);
  }
  return out;
}

/**
 * 断言不含缓存键（fake provider / 测试替身专用）。
 *
 * 不变量：**没接真实 Provider 就不许出现缓存指标** —— 一旦伪造，"缓存命中率"这类
 * 观测值将永远不可信，而它恰好是要拿去做产品决策的。
 */
export function assertNoCacheKeys(usage: NormalizedUsage): void {
  const offending = Object.keys(usage).filter(isCacheUsageKey);
  if (offending.length > 0) {
    throw new Error(`用量对象含缓存键（禁止伪造缓存指标）：${offending.join(", ")}`);
  }
}
