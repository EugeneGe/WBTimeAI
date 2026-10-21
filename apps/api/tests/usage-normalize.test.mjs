// T3-02 · usage 归一化测试。
//
// 判据：三键纯净、缺键不写、缓存键"提供才写"（用 Object.hasOwn 严格断言）、fake 禁缓存。

import assert from "node:assert/strict";
import test from "node:test";

import {
  CACHE_USAGE_KEYS,
  USAGE_KEYS,
  assertNoCacheKeys,
  normalizeUsage,
  sumUsage,
} from "../dist/modules/model/usage.js";

test("扁平入参：只保留有值的键（缺的键不出现，不是 0）", () => {
  const usage = normalizeUsage({ prompt_tokens: 12, completion_tokens: 8 });
  assert.deepEqual({ ...usage }, { prompt_tokens: 12, completion_tokens: 8 });
  assert.equal(Object.hasOwn(usage, "total_tokens"), false, "未提供的 total 不得凭空出现");
});

test("total 缺失时**不自动求和**（与 py oracle 一致：只复制厂商报的键）", () => {
  const usage = normalizeUsage({ prompt_tokens: 3, completion_tokens: 4 });
  assert.equal(Object.hasOwn(usage, "total_tokens"), false, "我们算的合计不能冒充厂商报的 total");
  // 需要合计时用 sumUsage（显式意图）
  assert.equal(sumUsage(usage, {}).total_tokens, undefined);
});

test("厂商给了 total 就原样用（不重算）", () => {
  const usage = normalizeUsage({ prompt_tokens: 3, completion_tokens: 4, total_tokens: 99 });
  assert.equal(usage.total_tokens, 99);
});

test("AI SDK v4 嵌套入参：inputTokens/outputTokens → 三键", () => {
  const usage = normalizeUsage({
    inputTokens: { total: 120, noCache: 100, cacheRead: 20 },
    outputTokens: { total: 30 },
  });
  assert.equal(usage.prompt_tokens, 120);
  assert.equal(usage.completion_tokens, 30);
  assert.equal(Object.hasOwn(usage, "total_tokens"), false, "V4 没给 totalTokens 就不写 total");
  assert.equal(usage.cache_read_tokens, 20, "厂商真报了 cacheRead 才写");
  assert.equal(Object.hasOwn(usage, "cache_write_tokens"), false, "没报 cacheWrite 就不得出现");
});

test("空入参 / 非对象 ⇒ {}（合法结果，不是错误）", () => {
  assert.deepEqual({ ...normalizeUsage(null) }, {});
  assert.deepEqual({ ...normalizeUsage({}) }, {});
  assert.deepEqual({ ...normalizeUsage(undefined) }, {});
  assert.deepEqual({ ...normalizeUsage("nope") }, {});
});

test("缓存键语义：提供 0 也要写（0 与 undefined 不同）", () => {
  const usage = normalizeUsage({ prompt_tokens: 1, completion_tokens: 1, cache_read_tokens: 0 });
  assert.equal(Object.hasOwn(usage, "cache_read_tokens"), true);
  assert.equal(usage.cache_read_tokens, 0);
});

test("sumUsage 逐键相加，未出现的键保持不出现", () => {
  const a = normalizeUsage({ prompt_tokens: 1, completion_tokens: 2 });
  const b = normalizeUsage({ prompt_tokens: 10, cache_read_tokens: 5 });
  const sum = sumUsage(a, b);
  assert.equal(sum.prompt_tokens, 11);
  assert.equal(sum.completion_tokens, 2);
  assert.equal(sum.cache_read_tokens, 5);
});

test("assertNoCacheKeys：含缓存键即抛（fake provider 的硬闸）", () => {
  assert.doesNotThrow(() => assertNoCacheKeys(normalizeUsage({ prompt_tokens: 1 })));
  assert.throws(
    () => assertNoCacheKeys({ prompt_tokens: 1, cache_read_tokens: 9 }),
    /禁止伪造缓存指标/,
  );
});

test("键集合常量与文档一致", () => {
  assert.deepEqual([...USAGE_KEYS], ["prompt_tokens", "completion_tokens", "total_tokens"]);
  assert.deepEqual([...CACHE_USAGE_KEYS], ["cache_read_tokens", "cache_write_tokens"]);
});
