// @wbtime/api · 成本计价（T3-02）。
//
// 口径来自 py 线域层 `wbtime_ai_domain/value_objects/model.py`：
//   * `PriceItem`：**每 1000 token** 单价 + 币种 + 不可变 `price_version` + 生效区间；
//   * `effective_from` **含**、`effective_to` **不含**（半开区间，`is_effective_at` 原文）；
//   * 金额量化到 **6 位小数**（对齐 `agent_run.cost Numeric(18,6)`，`ROUND_HALF_UP`）；
//   * **无匹配价目 ⇒ `UNPRICED` 且金额为 `null`，绝不记 0**
//     （`constants.py:106-107`；`entities/conversation.py:93` 原话"无匹配价目不得记作 0"）。
//
// 金额算法：先换算成**整数微元**（1e-6）再相加，最后除回 —— 避免 `0.1 + 0.2` 这类
// 浮点误差污染落库值。正数上 `Math.round` 与 py 的 `ROUND_HALF_UP` 等价。

/** 成本状态（与 `agent_run.cost_status` 同值域）。 */
export const COST_STATUSES = ["PRICED", "UNPRICED"] as const;

export type CostStatus = (typeof COST_STATUSES)[number];

/** 6 位小数的整数缩放因子（1e-6 为 1 个微元）。 */
const MICROS_PER_UNIT = 1_000_000;

/** 单价计价单位：每 1000 token。 */
const TOKENS_PER_PRICE_UNIT = 1000;

/** 一条价目（版本化；同一 provider+model 在任一时点至多一条生效）。 */
export interface PriceItem {
  readonly provider: string;
  readonly model: string;
  readonly currency: string;
  /** 每 1000 输入 token 的价格。 */
  readonly input_price_per_1k: number;
  /** 每 1000 输出 token 的价格。 */
  readonly output_price_per_1k: number;
  /** 不可变价目版本（落 `agent_run.cost_price_version`）。 */
  readonly price_version: string;
  /** 生效起点（含）；`null` = 自始生效。 */
  readonly effective_from?: Date | null;
  /** 失效起点（**不含**）；`null` = 长期有效。 */
  readonly effective_to?: Date | null;
}

/** 一次调用的成本快照（落库 / 返回体两处同源）。 */
export interface CostSnapshot {
  readonly costStatus: CostStatus;
  /** `PRICED` 时是 6 位小数金额；`UNPRICED` 时**必须是 `null`**。 */
  readonly cost: number | null;
  readonly costPriceVersion: string | null;
  readonly currency: string | null;
}

/** 未命中价目时的固定结果（唯一合法写法 —— 不允许 `cost: 0`）。 */
export const UNPRICED_SNAPSHOT: CostSnapshot = Object.freeze({
  costStatus: "UNPRICED",
  cost: null,
  costPriceVersion: null,
  currency: null,
});

/** 判断价目在某时刻是否生效（半开区间 `[from, to)`）。 */
export function isPriceEffective(item: PriceItem, at: Date): boolean {
  const start = item.effective_from ?? null;
  const end = item.effective_to ?? null;
  if (start !== null && at.getTime() < start.getTime()) return false;
  if (end !== null && at.getTime() >= end.getTime()) return false;
  return true;
}

/**
 * 把 token 数换算为整数微元。
 *
 * `tokens × price / 1000` 元 ⇒ 微元 = `tokens × price × 1e6 / 1000`。
 */
function toMicros(tokens: number, pricePer1k: number): number {
  if (tokens <= 0 || pricePer1k <= 0) return 0;
  return Math.round((tokens * pricePer1k * MICROS_PER_UNIT) / TOKENS_PER_PRICE_UNIT);
}

/**
 * 计算一次调用的成本。
 *
 * @param args.priceItem 命中的价目；`null` ⇒ 返回 {@link UNPRICED_SNAPSHOT}（`cost === null`）。
 * @param args.inputTokens 输入 token 数（负数按 0 处理，不抛——计数异常不该让 run 崩）。
 */
export function computeCost(args: {
  readonly priceItem: PriceItem | null;
  readonly inputTokens: number;
  readonly outputTokens: number;
}): CostSnapshot {
  const { priceItem, inputTokens, outputTokens } = args;
  if (priceItem === null) return UNPRICED_SNAPSHOT;

  const micros =
    toMicros(inputTokens, priceItem.input_price_per_1k) +
    toMicros(outputTokens, priceItem.output_price_per_1k);

  return Object.freeze({
    costStatus: "PRICED" as const,
    cost: micros / MICROS_PER_UNIT,
    costPriceVersion: priceItem.price_version,
    currency: priceItem.currency,
  });
}

/** 价目目录：按 `(provider, model)` 建索引，同一时刻取**第一条生效**的项。 */
export interface PriceCatalog {
  /** 命中价目；无 ⇒ `null`。 */
  priceFor(provider: string, model: string, at: Date): PriceItem | null;
  /** 目录里的全部价目（只读快照）。 */
  readonly items: readonly PriceItem[];
}

/**
 * 建目录。
 *
 * ⚠️ **本版不内置任何厂商价目**：价格是会变的商业事实，写死在代码里等于凭空造数
 * （纪律「凭空写数字是红线」）。默认目录为空 ⇒ 所有调用 `UNPRICED` + `cost=null`，
 * 这是**诚实**的结果；价目由装配方（配置/DB/运维导入）注入。
 */
export function createPriceCatalog(items: readonly PriceItem[] = []): PriceCatalog {
  const frozen = Object.freeze(items.map((item) => Object.freeze({ ...item })));
  return Object.freeze({
    items: frozen,
    priceFor(provider: string, model: string, at: Date): PriceItem | null {
      for (const item of frozen) {
        if (item.provider !== provider || item.model !== model) continue;
        if (!isPriceEffective(item, at)) continue;
        return item;
      }
      return null;
    },
  });
}

/** 空目录（生产默认；也可用于测试基線）。 */
export const EMPTY_PRICE_CATALOG: PriceCatalog = createPriceCatalog();
