// T3-02 · R3-19 判据 ④：**测试进程零外连**的机器证明。
//
// 判据原文（`00-施工期裁定.md` R3-19）：「断言测试进程零外连（拦截 net.connect / fetch）」。
//
// 做法：在测试进程里把 `net.connect` / `net.createConnection` / `http.request` /
// `https.request` / `globalThis.fetch` 全部换成**抛错桩**，然后跑一遍完整的模型链路
// （fake provider → gateway → 定价 → 预算）。只要有人偷偷联网，桩就会抛，测试立刻红。
//
// 自我反证（防"监控没装上"的假绿）：最后显式调用一次 `net.connect`，
// 必须抛 `egress blocked` —— 证明桩真的生效，前面的"零调用"才可信。

import assert from "node:assert/strict";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { after, before, test } from "node:test";

import { BudgetLedger } from "@wbtime/domain";

import { createFakeProvider } from "../dist/modules/model/fake-provider.js";
import { ModelGateway } from "../dist/modules/model/gateway.js";
import { createPriceCatalog } from "../dist/modules/model/pricing.js";

const attempts = [];
const originals = {
  connect: net.connect,
  createConnection: net.createConnection,
  httpRequest: http.request,
  httpsRequest: https.request,
  fetch: globalThis.fetch,
};

function blocker(label) {
  return (...args) => {
    attempts.push({ label, args: args.slice(0, 2) });
    throw new Error(`egress blocked (${label})`);
  };
}

before(() => {
  net.connect = blocker("net.connect");
  net.createConnection = blocker("net.createConnection");
  http.request = blocker("http.request");
  https.request = blocker("https.request");
  globalThis.fetch = blocker("fetch");
});

after(() => {
  net.connect = originals.connect;
  net.createConnection = originals.createConnection;
  http.request = originals.httpRequest;
  https.request = originals.httpsRequest;
  globalThis.fetch = originals.fetch;
});

test("整条模型链路在拦截网络后仍能跑完（fake → gateway → 定价 → 预算）", async () => {
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
    provider: createFakeProvider({ text: "offline" }),
    priceCatalog: catalog,
    onUsage: (record) => records.push(record),
  });

  const context = {
    runId: "run-offline",
    tenantId: "tenant-1",
    signal: new AbortController().signal,
    deadlineMs: Date.now() + 60_000,
    budget: new BudgetLedger(
      { maxWallTimeMs: 60_000, maxTokens: 10_000, maxCost: 10, maxTurns: 10, maxToolCalls: 10 },
      () => 1_000,
    ),
    permissions: [],
    policyVersion: "v1",
  };

  const texts = [];
  for await (const chunk of gateway.stream({ model: "m", messages: [{ role: "user", content: "hi" }] }, context)) {
    if (chunk.type === "text_delta") texts.push(chunk.text);
  }

  assert.equal(texts.join(""), "offline");
  assert.equal(records.length, 1);
  assert.equal(records[0].cost.costStatus, "PRICED");
  assert.equal(context.budget.snapshot().tokens, 20);
});

test("零外连：整段链路没有产生任何连接尝试", () => {
  assert.deepEqual(attempts, [], `发生了外连尝试：${JSON.stringify(attempts)}`);
});

test("反证：拦截桩本身有效（否则上一条的“零调用”是假绿）", () => {
  assert.throws(() => net.connect(80, "example.com"), /egress blocked/);
  assert.throws(() => https.request("https://example.com"), /egress blocked/);
  assert.throws(() => globalThis.fetch("https://example.com"), /egress blocked/);
  // 反证本身会产生 3 次"尝试"，清空以免污染后续断言
  attempts.length = 0;
});
