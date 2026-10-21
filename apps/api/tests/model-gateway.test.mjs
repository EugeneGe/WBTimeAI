// T3-02 · ModelGateway / 工厂闸门 / 错误归一 / 请求指纹。
//
// 判据（任务卡 T3-02 验收 ①②④）：
//   · `stream()` 聚合文本正确、usage 已归一、成本经定价（无价目 ⇒ null）；
//   · 四类错误映射 + `invalid_request` 不重试；
//   · 同一请求两次 fingerprint 相等（确定性门禁）；
//   · fake 在生产模式装配 ⇒ `CONFIGURATION_ERROR`。

import assert from "node:assert/strict";
import test from "node:test";

import { BudgetLedger } from "@wbtime/domain";

import {
  PROVIDER_ERROR_CODE,
  ProviderError,
  classifyHttpStatus,
  isRetryableProviderErrorType,
  toProviderError,
} from "../dist/modules/model/errors.js";
import { createFakeProvider } from "../dist/modules/model/fake-provider.js";
import { ModelGateway } from "../dist/modules/model/gateway.js";
import { createPriceCatalog } from "../dist/modules/model/pricing.js";
import { assertFakeProviderAllowed, createProviderAdapter } from "../dist/modules/model/providers/factory.js";
import { fingerprint, stableSerialize } from "../dist/modules/model/request-normalizer.js";

const LIMITS = {
  maxWallTimeMs: 60_000,
  maxTokens: 10_000,
  maxCost: 10,
  maxTurns: 10,
  maxToolCalls: 10,
};

function makeContext() {
  return {
    runId: "run-1",
    tenantId: "tenant-1",
    signal: new AbortController().signal,
    deadlineMs: Date.now() + 60_000,
    budget: new BudgetLedger(LIMITS, () => 1_000),
    permissions: [],
    policyVersion: "v1",
  };
}

async function collect(iterable) {
  const out = [];
  for await (const chunk of iterable) out.push(chunk);
  return out;
}

test("stream()：聚合文本 + usage 帧 + finish（文本来自 fake 脚本）", async () => {
  const gateway = new ModelGateway({ provider: createFakeProvider({ text: "hello world" }) });
  const chunks = await collect(gateway.stream({ model: "m", messages: [] }, makeContext()));

  const text = chunks.filter((c) => c.type === "text_delta").map((c) => c.text).join("");
  assert.equal(text, "hello world");
  assert.deepEqual(chunks.find((c) => c.type === "usage"), { type: "usage", tokensIn: 12, tokensOut: 8 });
  assert.deepEqual(chunks.at(-1), { type: "finish", reason: "model_finish" });
});

test("usage 计入预算：prompt+completion = 20 记入 ledger", async () => {
  const context = makeContext();
  const gateway = new ModelGateway({ provider: createFakeProvider() });
  await collect(gateway.stream({ model: "m", messages: [] }, context));
  assert.equal(context.budget.snapshot().tokens, 20);
});

test("无价目：onUsage 记录 UNPRICED 且 cost 严格为 null", async () => {
  const records = [];
  const gateway = new ModelGateway({
    provider: createFakeProvider(),
    onUsage: (record) => records.push(record),
  });
  await collect(gateway.stream({ model: "m", messages: [] }, makeContext()));

  assert.equal(records.length, 1);
  assert.equal(records[0].provider, "fake");
  assert.equal(records[0].cost.costStatus, "UNPRICED");
  assert.equal(records[0].cost.cost, null);
});

test("有价目：PRICED + 精确金额（12 in / 8 out @1.5 / 6.0 每 1k ⇒ 0.066）", async () => {
  const catalog = createPriceCatalog([
    {
      provider: "fake",
      model: "m",
      currency: "USD",
      input_price_per_1k: 1.5,
      output_price_per_1k: 6,
      price_version: "test-1",
    },
  ]);
  const records = [];
  const gateway = new ModelGateway({
    provider: createFakeProvider(),
    priceCatalog: catalog,
    now: () => new Date("2026-10-22T00:00:00Z"),
    onUsage: (record) => records.push(record),
  });
  await collect(gateway.stream({ model: "m", messages: [] }, makeContext()));

  assert.equal(records[0].cost.costStatus, "PRICED");
  assert.equal(records[0].cost.cost, 0.066);
  assert.equal(records[0].cost.costPriceVersion, "test-1");
});

test("四类错误映射：429 / 503 / timeout / 400，且只有 invalid_request 不重试", () => {
  assert.equal(classifyHttpStatus(429), "rate_limited");
  assert.equal(classifyHttpStatus(500), "provider_5xx");
  assert.equal(classifyHttpStatus(503), "provider_5xx");
  assert.equal(classifyHttpStatus(400), "invalid_request");
  assert.equal(classifyHttpStatus(404), "invalid_request");
  assert.equal(classifyHttpStatus(418), "invalid_request", "4xx 一律调用方错误（不重试）");

  assert.equal(isRetryableProviderErrorType("rate_limited"), true);
  assert.equal(isRetryableProviderErrorType("provider_5xx"), true);
  assert.equal(isRetryableProviderErrorType("timeout"), true);
  assert.equal(isRetryableProviderErrorType("invalid_request"), false);
});

test("toProviderError：从 HTTP 状态归一，码固定 INTERNAL_ERROR", () => {
  const error = toProviderError({ status: 429 }, { provider: "openai", model: "gpt-x" });
  assert.equal(error.errorType, "rate_limited");
  assert.equal(error.retryable, true);
  assert.equal(error.httpStatus, 429);
  assert.equal(error.code, PROVIDER_ERROR_CODE);
  assert.equal(error.data.error_type, "rate_limited");

  const invalid = toProviderError({ statusCode: 400 }, { provider: "openai" });
  assert.equal(invalid.errorType, "invalid_request");
  assert.equal(invalid.retryable, false, "参数错误重试只会重复失败并放大计费");

  // 已是 ProviderError 的原样返回（不二次归类）
  const original = new ProviderError("boom", { errorType: "timeout" });
  assert.equal(toProviderError(original), original);
});

test("invalid_request 即使显式要求可重试也被压回 false", () => {
  const error = new ProviderError("bad", { errorType: "invalid_request", retryable: true });
  assert.equal(error.retryable, false);
});

test("fingerprint：同一请求两次相等；工具顺序变则不同；schema 键序不影响", () => {
  const request = {
    model: "m",
    messages: [
      { role: "system", content: "sys" },
      { role: "user", content: "hi" },
    ],
    tools: [
      { name: "read_file", inputSchema: { type: "object", properties: { path: { type: "string" } } } },
      { name: "write_file", inputSchema: { type: "object", properties: { path: { type: "string" } } } },
    ],
  };
  assert.equal(fingerprint(request), fingerprint(request));
  assert.equal(fingerprint(request), fingerprint(structuredClone(request)));

  // tools 顺序是语义的一部分 ⇒ 换序必须换指纹
  const swapped = { ...request, tools: [request.tools[1], request.tools[0]] };
  assert.notEqual(fingerprint(request), fingerprint(swapped));

  // schema 内部键序无语义 ⇒ 排序后指纹相同
  const reordered = {
    ...request,
    tools: [
      { name: "read_file", inputSchema: { properties: { path: { type: "string" } }, type: "object" } },
      request.tools[1],
    ],
  };
  assert.equal(fingerprint(request), fingerprint(reordered));
});

test("stableSerialize 剔除动态字段（run_id / 时间戳不进前缀）", () => {
  const base = { model: "m", messages: [{ role: "user", content: "hi" }] };
  const withDynamic = {
    ...base,
    run_id: "run-1",
    timestamp: 123,
    tools: [{ name: "t", inputSchema: { type: "object", run_id: "should-be-dropped" } }],
  };
  const withoutDynamic = {
    ...base,
    tools: [{ name: "t", inputSchema: { type: "object" } }],
  };
  assert.equal(stableSerialize(withDynamic), stableSerialize(withoutDynamic));
});

test("fake 闸门：生产环境抛 CONFIGURATION_ERROR；test 环境放行", () => {
  assert.throws(
    () => assertFakeProviderAllowed({ NODE_ENV: "production" }),
    /只允许在 NODE_ENV=test/,
  );
  assert.doesNotThrow(() => assertFakeProviderAllowed({ NODE_ENV: "test" }));
  assert.doesNotThrow(() => assertFakeProviderAllowed({ WBTIME_AI_ALLOW_FAKE_PROVIDER: "1" }));
});

test("createProviderAdapter(fake) 在禁用环境下拒绝装配", async () => {
  await assert.rejects(
    () => createProviderAdapter({ kind: "fake", env: { NODE_ENV: "production" } }),
    /只允许在 NODE_ENV=test/,
  );
});
