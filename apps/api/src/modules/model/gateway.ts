// @wbtime/api · ModelGateway（T3-02）—— `ModelGatewayPort` 的唯一实现。
//
// 三条约束：
//   1. **只有 `stream()` 一个执行方法**（R3-10）。没有 `complete()` / `resume()`：
//      非流式由调用方聚合，resume 归 run 层（重放）；
//   2. usage 一律经 `usage.ts` 归一（三键；缓存只在厂商真报了才写）；
//   3. 成本一律经 `pricing.ts`：**无价目 ⇒ `UNPRICED` + `cost = null`**，绝不写 0。
//
// 为什么成本不塞进 `ModelChunk`：端口类型是 T3-04 冻结面（`text_delta` / `usage` / `finish`），
// 往里加字段等于改冻结签名。成本通过 `onUsage` 回调外送 + 直接计入 `context.budget`。

import type { ModelChunk, ModelGatewayPort, ModelRequest, RunCallContext } from "@wbtime/domain";

import type { ProviderAdapter } from "./providers/factory.js";
import { toModelChunk } from "./providers/factory.js";
import { computeCost, EMPTY_PRICE_CATALOG, type CostSnapshot, type PriceCatalog } from "./pricing.js";
import { sumUsage, type NormalizedUsage } from "./usage.js";

/** 一次模型调用的用量 + 成本快照（供 RunCoordinator / 审计取用）。 */
export interface ModelUsageRecord {
  readonly provider: string;
  readonly model: string;
  readonly usage: NormalizedUsage;
  readonly cost: CostSnapshot;
}

export interface ModelGatewayOptions {
  readonly provider: ProviderAdapter;
  /** 价目目录；缺省空目录（⇒ 全部 `UNPRICED`）。 */
  readonly priceCatalog?: PriceCatalog;
  /** 时钟（成本按"调用发生时刻"取生效价目）；缺省 `() => new Date()`。 */
  readonly now?: () => Date;
  /** 用量外送回调（**不抛**：记录失败不得中断 run）。 */
  readonly onUsage?: (record: ModelUsageRecord) => void;
}

/**
 * Model 网关。
 *
 * 用法：`for await (const chunk of gateway.stream(req, ctx)) { ... }`
 * —— 文本增量直接消费；`usage` 帧已归一；`finish` 帧到达时成本已算好。
 */
export class ModelGateway implements ModelGatewayPort {
  readonly #provider: ProviderAdapter;
  readonly #catalog: PriceCatalog;
  readonly #now: () => Date;
  readonly #onUsage: ((record: ModelUsageRecord) => void) | undefined;

  constructor(options: ModelGatewayOptions) {
    this.#provider = options.provider;
    this.#catalog = options.priceCatalog ?? EMPTY_PRICE_CATALOG;
    this.#now = options.now ?? (() => new Date());
    this.#onUsage = options.onUsage;
  }

  /** 当前适配器的 provider 名（审计用）。 */
  get providerName(): string {
    return this.#provider.providerName;
  }

  async *stream(request: ModelRequest, context: RunCallContext): AsyncIterable<ModelChunk> {
    let accumulated: NormalizedUsage = {};

    for await (const chunk of this.#provider.stream(request, context)) {
      if (chunk.type === "usage") {
        accumulated = sumUsage(accumulated, chunk.usage);
        // 预算按 token 总量计：prompt + completion（缓存命中部分也消耗了上下文预算）。
        const tokens = (chunk.usage.prompt_tokens ?? 0) + (chunk.usage.completion_tokens ?? 0);
        if (tokens > 0) context.budget.addTokens(tokens);
      }

      if (chunk.type === "finish") {
        const priceItem = this.#catalog.priceFor(
          this.#provider.providerName,
          request.model,
          this.#now(),
        );
        const cost = computeCost({
          priceItem,
          inputTokens: accumulated.prompt_tokens ?? 0,
          outputTokens: accumulated.completion_tokens ?? 0,
        });
        if (this.#onUsage !== undefined) {
          try {
            this.#onUsage({
              provider: this.#provider.providerName,
              model: request.model,
              usage: accumulated,
              cost,
            });
          } catch {
            // 观测回调失败不得中断 run（观测不是业务路径）。
          }
        }
      }

      yield toModelChunk(chunk);
    }
  }
}
