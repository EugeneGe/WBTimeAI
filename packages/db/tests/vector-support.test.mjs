/**
 * T1-07 · 缺 pgvector 的退化告警 —— 双向测试。
 *
 * 本机**没有 PostgreSQL**，所以这里不连真库，用「假 client」只模拟一件事：
 * `SELECT count(*) FROM pg_extension WHERE extname='vector'` 返回几。
 *
 * 四个断言方向：
 *   ① 扩不在（count=0）⇒ supported=false + **确实发出告警**（code=PGVECTOR_MISSING）+ degradation 存在；
 *   ② 扩在  （count=1）⇒ supported=true  + **一条告警都不发**（正向不能误报，否则告警会被无视）；
 *   ③ count 以 bigint 字符串（'0'）返回时同样判缺失（pg 驱动真实行为）；
 *   ④ 探测本身抛错 ⇒ fail-closed 判不支持，且告警 code=PGVECTOR_PROBE_FAILED。
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  PGVECTOR_MISSING,
  PGVECTOR_PROBE_FAILED,
  PGVECTOR_PROBE_SQL,
  VECTOR_COLUMN_DEGRADATION,
  detectVectorSupport,
} from "../dist/vector-support.js";

/** 假 client：只认识探测语句，其余一律抛错（防止将来悄悄换 SQL 后本测试仍然"绿"）。 */
function fakeClient(handler) {
  const calls = [];
  return {
    calls,
    query(sql) {
      calls.push(sql);
      if (sql !== PGVECTOR_PROBE_SQL) throw new Error(`假 client 不认识这条 SQL: ${sql}`);
      return handler();
    },
  };
}

/** 收集告警的注入出口。 */
function recorder() {
  const warnings = [];
  return { warnings, warn: (w) => warnings.push(w) };
}

test("扩不在（count=0）⇒ supported=false + 发 PGVECTOR_MISSING 告警 + 带 degradation", async () => {
  const client = fakeClient(() => ({ rows: [{ count: 0 }] }));
  const rec = recorder();

  const support = await detectVectorSupport(client, { warn: rec.warn });

  assert.equal(support.supported, false);
  assert.equal(support.reason, "pgvector extension missing");
  assert.equal(support.degradation, "vector columns fall back to JSONB");
  assert.equal(support.degradation, VECTOR_COLUMN_DEGRADATION);

  // 告警确实发出，且只发一条
  assert.equal(rec.warnings.length, 1);
  const w = rec.warnings[0];
  assert.equal(w.code, PGVECTOR_MISSING);
  assert.equal(w.level, "warn");
  assert.equal(w.reason, "pgvector extension missing");
  assert.equal(w.degradation, "vector columns fall back to JSONB");
  assert.match(w.message, /pgvector/);
  assert.ok(!Number.isNaN(Date.parse(w.at)), `at 应为可解析时间: ${w.at}`);

  // 探测语句真的是查 pg_extension
  assert.deepEqual(client.calls, [PGVECTOR_PROBE_SQL]);
  assert.match(PGVECTOR_PROBE_SQL, /pg_extension/);
  assert.match(PGVECTOR_PROBE_SQL, /'vector'/);
});

test("扩在（count=1）⇒ supported=true 且一条告警都不发", async () => {
  const client = fakeClient(() => ({ rows: [{ count: 1 }] }));
  const rec = recorder();

  const support = await detectVectorSupport(client, { warn: rec.warn });

  assert.equal(support.supported, true);
  assert.equal(support.degradation, null);
  assert.equal(rec.warnings.length, 0, "扩展存在时不得误报告警");
});

test("count 以字符串返回（pg bigint）⇒ 仍判缺失并发告警", async () => {
  const client = fakeClient(() => ({ rows: [{ count: "0" }] }));
  const rec = recorder();

  const support = await detectVectorSupport(client, { warn: rec.warn });

  assert.equal(support.supported, false);
  assert.equal(rec.warnings.length, 1);
  assert.equal(rec.warnings[0].code, PGVECTOR_MISSING);
});

test("探测抛错 ⇒ fail-closed 判不支持，告警 code=PGVECTOR_PROBE_FAILED", async () => {
  const client = fakeClient(() => {
    throw new Error("connection refused");
  });
  const rec = recorder();

  const support = await detectVectorSupport(client, { warn: rec.warn });

  assert.equal(support.supported, false);
  assert.match(support.reason, /pgvector probe failed: connection refused/);
  assert.equal(rec.warnings.length, 1);
  assert.equal(rec.warnings[0].code, PGVECTOR_PROBE_FAILED);
});

test("探测结果不可解析 ⇒ 不静默当成功，按探测失败告警", async () => {
  const client = fakeClient(() => ({ rows: [{}] }));
  const rec = recorder();

  const support = await detectVectorSupport(client, { warn: rec.warn });

  assert.equal(support.supported, false);
  assert.equal(rec.warnings.length, 1);
  assert.equal(rec.warnings[0].code, PGVECTOR_PROBE_FAILED);
});

test("不注入 warn ⇒ 默认出口落 console.warn（告警不会因为没接 logger 就消失）", async () => {
  const client = fakeClient(() => ({ rows: [{ count: 0 }] }));
  const original = console.warn;
  const printed = [];
  console.warn = (...args) => printed.push(args.join(" "));
  try {
    const support = await detectVectorSupport(client);
    assert.equal(support.supported, false);
  } finally {
    console.warn = original;
  }
  assert.equal(printed.length, 1);
  const parsed = JSON.parse(printed[0]);
  assert.equal(parsed.code, PGVECTOR_MISSING);
  assert.equal(parsed.degradation, VECTOR_COLUMN_DEGRADATION);
});
