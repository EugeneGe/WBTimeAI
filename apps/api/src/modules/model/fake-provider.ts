// @wbtime/api · 确定性假 Provider（T3-02 / R3-19）。
//
// 为什么必须有它：CI 没有任何真实模型 key，而 `pnpm test` 必须离线可跑。用真 Provider
// 会恒红/不稳定；**造假 usage** 又会让"缓存命中率 / 成本"这类观测永远不可信。
// 所以假 Provider 的定位是：**只提供确定性文本与确定性的计数常量**，且**不提供缓存指标**。
//
// 两条硬约束：
//   1. `token_usage` **只有三键**；出现 `cache_*` 键 ⇒ 构造期就抛（伪造指标是头号事故类型）；
//   2. 闸门在 `providers/factory.ts::assertFakeProviderAllowed`（生产误配 ⇒ `CONFIGURATION_ERROR`）。
//
// ⚠️ 与 R3-19 原文的偏差（已登记）：裁定写「`token_usage.fake=true` 标注来源」，但任务卡
// 验收 ② 要求 `token_usage ⊆ 三键`——`fake` 会变成第四键，二者互斥。本实现按任务卡：
// usage 保持纯净，来源放在 `provider: "fake"`（不是计数，不该混进用量）。

import type { ModelRequest, RunCallContext } from "@wbtime/domain";

import type { ProviderAdapter, ProviderChunk } from "./providers/factory.js";
import { assertNoCacheKeys } from "./usage.js";

/** 默认假文本（固定值 —— 断言可直接比）。 */
export const DEFAULT_FAKE_TEXT = "fake-provider: ok";

/** 默认假用量（固定常量；三键，无缓存）。 */
export const DEFAULT_FAKE_USAGE = Object.freeze({
  prompt_tokens: 12,
  completion_tokens: 8,
  total_tokens: 20,
});

export interface FakeProviderOptions {
  /** 自定义脚本（覆盖默认的 text → usage → finish 三段式）。 */
  readonly script?: readonly ProviderChunk[];
  /** 文本增量（默认 {@link DEFAULT_FAKE_TEXT} 全文一块）。 */
  readonly text?: string;
  /** 用量（默认 {@link DEFAULT_FAKE_USAGE}）。 */
  readonly usage?: { readonly prompt_tokens?: number; readonly completion_tokens?: number; readonly total_tokens?: number };
}

/** 默认脚本：一段文本 + 一次 usage + 一次 finish。 */
function defaultScript(options: FakeProviderOptions): ProviderChunk[] {
  // total **只在显式给出时**才写：默认脚本给全三键；调用方自定义时若没给 total，就保持缺
  // （与 `normalizeUsage` 同一纪律——不拿"我们算的"冒充"厂商报的"）。
  const usage: { prompt_tokens: number; completion_tokens: number; total_tokens?: number } = {
    prompt_tokens: options.usage?.prompt_tokens ?? DEFAULT_FAKE_USAGE.prompt_tokens,
    completion_tokens: options.usage?.completion_tokens ?? DEFAULT_FAKE_USAGE.completion_tokens,
  };
  const total =
    options.usage?.total_tokens ??
    (options.usage === undefined ? DEFAULT_FAKE_USAGE.total_tokens : undefined);
  if (total !== undefined) usage.total_tokens = total;
  return [
    { type: "text_delta", text: options.text ?? DEFAULT_FAKE_TEXT },
    { type: "usage", usage },
    { type: "finish", reason: "model_finish" },
  ];
}

/**
 * 建假 Provider。
 *
 * @throws {Error} 脚本里出现缓存用量键（构造期即失败，不等到运行）。
 */
export function createFakeProvider(options: FakeProviderOptions = {}): ProviderAdapter {
  const script = Object.freeze(
    (options.script ?? defaultScript(options)).map((chunk) => {
      if (chunk.type === "usage") assertNoCacheKeys(chunk.usage);
      return Object.freeze({ ...chunk });
    }),
  );

  return {
    kind: "fake",
    providerName: "fake",
    async *stream(_request: ModelRequest, context: RunCallContext): AsyncIterable<ProviderChunk> {
      if (context.signal.aborted) return;
      // 每次都从同一脚本起播 ⇒ 确定性（不随调用次数变化）。
      for (const chunk of script) {
        if (context.signal.aborted) return;
        yield chunk;
      }
    },
  };
}
