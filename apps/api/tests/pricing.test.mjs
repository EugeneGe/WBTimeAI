// T3-02 · 计价测试。
//
// 判据：无价目 ⇒ UNPRICED 且 cost 严格等于 null（不是 0/undefined）；有价目 ⇒ 6 位小数精确；
//       生效区间半开 [from, to)。

import assert from "node:assert/strict";
import test from "node:test";

import {
  EMPTY_PRICE_CATALOG,
  computeCost,
  createPriceCatalog,
  isPriceEffective,
} from "../dist/modules/model/pricing.js";

const ITEM = {
  provider: "openai",
  model: "gpt-x",
  currency: "USD",
  input_price_per_1k: 0.15,
  output_price_per_1k: 0.6,
  price_version: "2026-10-01",
};

test("无价目：UNPRICED + cost 严格为 null（绝不记 0）", () => {
  const snap = computeCost({ priceItem: null, inputTokens: 1000, outputTokens: 500 });
  assert.equal(snap.costStatus, "UNPRICED");
  assert.equal(snap.cost, null);
  assert.notEqual(snap.cost, 0, "0 会被下游当成'免费'，与'没价目'语义完全不同");
  assert.equal(snap.costPriceVersion, null);
  assert.equal(snap.currency, null);
});

test("有价目：1000 输入 @0.15/1k + 500 输出 @0.6/1k ⇒ 0.45（6 位小数）", () => {
  const snap = computeCost({ priceItem: ITEM, inputTokens: 1000, outputTokens: 500 });
  assert.equal(snap.costStatus, "PRICED");
  assert.equal(snap.cost, 0.45);
  assert.equal(snap.costPriceVersion, "2026-10-01");
  assert.equal(snap.currency, "USD");
});

test("小数不产生浮点尾巴：333 输入 @0.15 + 777 输出 @0.6", () => {
  const snap = computeCost({ priceItem: ITEM, inputTokens: 333, outputTokens: 777 });
  // 333*0.15/1000 = 0.049950；777*0.6/1000 = 0.466200 ⇒ 0.516150
  assert.equal(snap.cost, 0.51615);
  assert.equal(String(snap.cost).includes("0000000001"), false);
});

test("0 token ⇒ 0（有价目时 0 是真实的 0，不是 UNPRICED）", () => {
  const snap = computeCost({ priceItem: ITEM, inputTokens: 0, outputTokens: 0 });
  assert.equal(snap.costStatus, "PRICED");
  assert.equal(snap.cost, 0);
});

test("生效区间是半开 [from, to)", () => {
  const from = new Date("2026-10-01T00:00:00Z");
  const to = new Date("2026-11-01T00:00:00Z");
  const item = { ...ITEM, effective_from: from, effective_to: to };
  assert.equal(isPriceEffective(item, new Date("2026-09-30T23:59:59Z")), false, "起点之前不生效");
  assert.equal(isPriceEffective(item, from), true, "起点含");
  assert.equal(isPriceEffective(item, new Date("2026-10-31T23:59:59Z")), true);
  assert.equal(isPriceEffective(item, to), false, "终点不含");
});

test("目录：按 provider+model 命中，未命中返回 null；空目录全 UNPRICED", () => {
  const catalog = createPriceCatalog([ITEM]);
  assert.equal(catalog.priceFor("openai", "gpt-x", new Date())?.price_version, "2026-10-01");
  assert.equal(catalog.priceFor("openai", "gpt-y", new Date()), null);
  assert.equal(catalog.priceFor("anthropic", "gpt-x", new Date()), null);
  assert.equal(EMPTY_PRICE_CATALOG.priceFor("openai", "gpt-x", new Date()), null);
  assert.equal(EMPTY_PRICE_CATALOG.items.length, 0);
});

test("目录命中后再算成本：端到端 0.45", () => {
  const catalog = createPriceCatalog([ITEM]);
  const snap = computeCost({
    priceItem: catalog.priceFor("openai", "gpt-x", new Date()),
    inputTokens: 1000,
    outputTokens: 500,
  });
  assert.equal(snap.cost, 0.45);
});
