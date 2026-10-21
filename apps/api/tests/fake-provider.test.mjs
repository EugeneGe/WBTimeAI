// T3-02 · 假 Provider 测试（R3-19）。
//
// 判据：默认脚本确定性；usage 三键且**无缓存键**；脚本里塞 cache 键 ⇒ 构造期抛；取消即停。

import assert from "node:assert/strict";
import test from "node:test";

import { BudgetLedger } from "@wbtime/domain";

import {
  DEFAULT_FAKE_TEXT,
  DEFAULT_FAKE_USAGE,
  createFakeProvider,
} from "../dist/modules/model/fake-provider.js";

const LIMITS = {
  maxWallTimeMs: 60_000,
  maxTokens: 10_000,
  maxCost: 10,
  maxTurns: 10,
  maxToolCalls: 10,
};

function makeContext(signal = new AbortController().signal) {
  return {
    runId: "run-1",
    tenantId: "tenant-1",
    signal,
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

test("默认脚本：一段文本 + 三键 usage + finish（顺序固定）", async () => {
  const chunks = await collect(createFakeProvider().stream({ model: "m" }, makeContext()));
  assert.deepEqual(chunks.map((c) => c.type), ["text_delta", "usage", "finish"]);
  assert.equal(chunks[0].text, DEFAULT_FAKE_TEXT);
  assert.deepEqual({ ...chunks[1].usage }, { ...DEFAULT_FAKE_USAGE });
  assert.equal(chunks[2].reason, "model_finish");
});

test("确定性：同一 provider 连续两次调用，分片逐字节相同", async () => {
  const provider = createFakeProvider();
  const first = await collect(provider.stream({ model: "m" }, makeContext()));
  const second = await collect(provider.stream({ model: "m" }, makeContext()));
  assert.deepEqual(JSON.parse(JSON.stringify(second)), JSON.parse(JSON.stringify(first)));
});

test("脚本里塞 cache 键 ⇒ 构造期就抛（不等到运行）", () => {
  assert.throws(
    () =>
      createFakeProvider({
        script: [
          { type: "text_delta", text: "x" },
          { type: "usage", usage: { prompt_tokens: 1, cache_read_tokens: 5 } },
        ],
      }),
    /禁止伪造缓存指标/,
  );
});

test("自定义 usage 只给 prompt/completion：不补 total，也不补 cache", async () => {
  const provider = createFakeProvider({ usage: { prompt_tokens: 3, completion_tokens: 4 } });
  const chunks = await collect(provider.stream({ model: "m" }, makeContext()));
  const usage = chunks.find((c) => c.type === "usage").usage;
  assert.equal(Object.hasOwn(usage, "total_tokens"), false, "自定义 usage 未给 total ⇒ 不得凭空补");
  assert.equal(Object.hasOwn(usage, "cache_read_tokens"), false);
});

test("取消后不再产出分片", async () => {
  const controller = new AbortController();
  controller.abort();
  const chunks = await collect(createFakeProvider().stream({ model: "m" }, makeContext(controller.signal)));
  assert.deepEqual(chunks, []);
});

test("providerName 恒为 fake（审计口径）", () => {
  assert.equal(createFakeProvider().providerName, "fake");
  assert.equal(createFakeProvider().kind, "fake");
});
