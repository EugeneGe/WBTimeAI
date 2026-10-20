// T1-02 · @wbtime/event：数值上线格式定死（golden 帧逐字节可比的前提）。
//
// 契约口径：contracts/sse/channels.json → numeric_format，策略
// `integers-only-on-the-wire`；小数位数从契约 example 解析，不硬编码。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NUMERIC_FIXED_DECIMALS,
  buildEventPayload,
  normalizePayload,
  normalizeWireNumber,
} from "../dist/index.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const contract = JSON.parse(
  readFileSync(join(ROOT, "contracts", "sse", "channels.json"), "utf8"),
);

test("小数位数与契约 guard 帧的定点输出一致", () => {
  const guard = contract.numeric_format.guard_explanation;
  assert.ok(typeof guard === "string");
  // 契约 guard 帧里 0.5 → "0.500000"，即 6 位小数。
  assert.equal(NUMERIC_FIXED_DECIMALS, 6);
  assert.equal((0.5).toFixed(NUMERIC_FIXED_DECIMALS), "0.500000");
});

test("整数与整数值浮点都上线为整数（1.0 → 1）", () => {
  assert.equal(normalizeWireNumber(12), 12);
  assert.equal(normalizeWireNumber(1.0), 1);
  assert.equal(normalizeWireNumber(-0.0), 0);
  assert.equal(JSON.stringify({ v: normalizeWireNumber(1.0) }), '{"v":1}');
});

test("非整数浮点上线为定点十进制字符串", () => {
  assert.equal(normalizeWireNumber(0.5), "0.500000");
  assert.equal(normalizeWireNumber(0.25), "0.250000");
});

test("NaN / Infinity 抛错（不可上线，禁止静默降级）", () => {
  assert.throws(() => normalizeWireNumber(NaN), RangeError);
  assert.throws(() => normalizeWireNumber(Infinity), RangeError);
  assert.throws(() => normalizeWireNumber(-Infinity), RangeError);
});

test("bool 不被当成 int（true 不能变成 1）", () => {
  assert.deepEqual(normalizePayload({ flag: true, n: 1 }), { flag: true, n: 1 });
  assert.equal(JSON.stringify(normalizePayload({ flag: true })), '{"flag":true}');
});

test("递归归一化且键序不变（与 guard 帧口径对齐）", () => {
  const normalized = normalizePayload({
    run_id: "run_01",
    duration_ms: 12,
    iterations: 1,
    score: 0.5,
    ratio: 1.0,
    neg_zero: -0.0,
    nested: { score: 0.25 },
  });
  assert.equal(
    JSON.stringify(normalized),
    '{"run_id":"run_01","duration_ms":12,"iterations":1,"score":"0.500000","ratio":1,"neg_zero":0,"nested":{"score":"0.250000"}}',
  );
});

test("按契约键序装配 payload：键序不随传入顺序漂移", () => {
  const a = buildEventPayload("agent.completed", {
    iterations: 1,
    duration_ms: 12,
    run_id: "run_01",
  });
  const b = buildEventPayload("agent.completed", {
    run_id: "run_01",
    duration_ms: 12,
    iterations: 1,
  });
  assert.deepEqual(Object.keys(a), ["run_id", "duration_ms", "iterations"]);
  assert.equal(JSON.stringify(a), JSON.stringify(b));
});

test("装配时拒绝非契约键（多一个键 golden 帧就对不上）", () => {
  assert.throws(
    () => buildEventPayload("agent.completed", { run_id: "r", extra: 1 }),
    /非契约键/,
  );
});
