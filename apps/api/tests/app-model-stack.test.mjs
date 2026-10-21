// T3-02 · A02 —— `app.ts` 装配 ModelGateway。
//
// 判据（任务卡验收 ② + R3-19 + 施工记录 §6-2）：
//   · fake 只在 `NODE_ENV=test` / `WBTIME_AI_ALLOW_FAKE_PROVIDER=1` / 显式开关下装配；
//   · 生产缺对应 API key ⇒ **启动期** `ConfigError`（码 `CONFIGURATION_ERROR`），
//     **绝不静默回落 fake**；
//   · 未给 `model` ⇒ 不装配（CI 无 key ⇒ `pnpm test` 必须离线可跑，既有行为零变化）。
//
// 「改坏什么必红」登记（实测，见施工记录 §9）：
//   · 摘掉 `assertFakeProviderAllowed(...)` ⇒ 「生产禁 fake」用例必红；
//   · 摘掉装配期的空 key 检查 ⇒ 「openai-compatible 缺 key」用例必红
//     （openai/anthropic/google 三档靠工厂内的检查兜住，兼容档只有这里有闸）；
//   · 把 `if (options.model !== undefined)` 改成无条件装配 ⇒ 既有 239 条里的
//     `buildApp()` 用例必红（CI 无 key）—— 故默认必须是「不装配」。

import assert from "node:assert/strict";
import test from "node:test";

import { ConfigError, loadConfig } from "@wbtime/config";
import { BudgetLedger } from "@wbtime/domain";

import { buildApp, buildModelStack } from "../dist/app.js";
import { ModelGateway } from "../dist/modules/model/gateway.js";
import { DEFAULT_FAKE_TEXT } from "../dist/modules/model/fake-provider.js";

/** 断言抛的是 `ConfigError`（码 `CONFIGURATION_ERROR`）且消息命中。 */
function assertConfigError(fn, pattern) {
  assert.throws(fn, (error) => {
    assert.ok(
      error instanceof ConfigError,
      `必须是 ConfigError（CONFIGURATION_ERROR），实测 ${String(error)}`,
    );
    assert.equal(error.code, "CONFIGURATION_ERROR");
    assert.match(error.message, pattern);
    return true;
  });
}

/** fake 装配用的环境变量（测试档）。 */
const TEST_ENV = Object.freeze({ NODE_ENV: "test" });
/** 生产档环境变量（**刻意不含任何 `*_API_KEY`**）。 */
const PROD_ENV = Object.freeze({ NODE_ENV: "production" });

async function collect(iterable) {
  const out = [];
  for await (const chunk of iterable) out.push(chunk);
  return out;
}

function makeContext() {
  return {
    runId: "run-1",
    tenantId: "tenant-1",
    signal: new AbortController().signal,
    deadlineMs: Date.now() + 60_000,
    budget: new BudgetLedger(
      {
        maxWallTimeMs: 60_000,
        maxTokens: 10_000,
        maxCost: 10,
        maxTurns: 10,
        maxToolCalls: 10,
      },
      () => 1_000,
    ),
    permissions: [],
    policyVersion: "v1",
  };
}

test("NODE_ENV=test ⇒ 装配 fake，且网关是 ModelGateway 实例", () => {
  const stack = buildModelStack({ kind: "fake", env: TEST_ENV });
  assert.equal(stack.kind, "fake");
  assert.equal(stack.provider.providerName, "fake");
  assert.ok(stack.gateway instanceof ModelGateway);
  assert.equal(stack.gateway.providerName, "fake");
});

test("WBTIME_AI_ALLOW_FAKE_PROVIDER=1 ⇒ 装配 fake（生产档也放行，属显式授权）", () => {
  const stack = buildModelStack({ kind: "fake", env: { WBTIME_AI_ALLOW_FAKE_PROVIDER: "1" } });
  assert.equal(stack.provider.kind, "fake");
});

test("显式开关（config.modelAllowFakeProvider）⇒ 装配 fake", () => {
  const config = loadConfig({ WBTIME_AI_ALLOW_FAKE_PROVIDER: "1" });
  assert.equal(config.modelAllowFakeProvider, true, "环境变量确实进了 config（不是死配置）");
  const stack = buildModelStack({ kind: "fake", config, env: PROD_ENV });
  assert.equal(stack.provider.kind, "fake");
});

test("生产装配 fake ⇒ CONFIGURATION_ERROR（不得静默放行）", () => {
  assertConfigError(
    () => buildModelStack({ kind: "fake", env: PROD_ENV }),
    /只允许在 NODE_ENV=test/,
  );
});

test("同步通道不接受 fake：createSdkProviderAdapter 走 fake 也会炸（闸门不可绕过）", () => {
  // 装配期若误把 fake 当"真实厂商"直接建，必须炸而不是产出假模型。
  assertConfigError(
    () => buildModelStack({ kind: "fake", env: PROD_ENV, allowFakeProvider: false }),
    /只允许在 NODE_ENV=test/,
  );
});

test("生产缺 OPENAI_API_KEY ⇒ CONFIGURATION_ERROR（不是回落 fake）", () => {
  assertConfigError(
    () => buildModelStack({ kind: "openai", env: PROD_ENV }),
    /未配置 OPENAI_API_KEY/,
  );
});

test("生产缺 ANTHROPIC_API_KEY / GOOGLE key ⇒ 同样 fail loud", () => {
  assertConfigError(
    () => buildModelStack({ kind: "anthropic", env: PROD_ENV }),
    /未配置 ANTHROPIC_API_KEY/,
  );
  assertConfigError(
    () => buildModelStack({ kind: "google", env: PROD_ENV }),
    /未配置 GOOGLE_GENERATIVE_AI_API_KEY/,
  );
});

test("openai-compatible 缺 key ⇒ 装配期就炸（工厂只强制 baseURL，闸在这里）", () => {
  assertConfigError(
    () =>
      buildModelStack({
        kind: "openai-compatible",
        baseURL: "https://api.siliconflow.cn/v1",
        env: PROD_ENV,
      }),
    /未配置 OPENAI_COMPATIBLE_API_KEY/,
  );
});

test("openai-compatible 缺 baseURL ⇒ 装配期就炸", () => {
  assertConfigError(
    () =>
      buildModelStack({
        kind: "openai-compatible",
        apiKey: "fixture-key-not-real",
        env: PROD_ENV,
      }),
    /openai-compatible provider 必须给 baseURL/,
  );
});

test("NODE_ENV=test 但缺 key ⇒ 仍然炸（测试档也不许静默回落 fake）", () => {
  // 这条是"静默回落"最可能藏身的地方：既然是测试环境，最省事的做法就是
  // 没 key 时直接给个 fake —— 那会让"CI 全绿"变成"CI 在跑假模型"。
  assertConfigError(
    () => buildModelStack({ kind: "openai", env: TEST_ENV }),
    /未配置 OPENAI_API_KEY/,
  );
});

test("有 key ⇒ 装配真实厂商适配器（providerName 不是 fake）", () => {
  for (const kind of ["openai", "anthropic", "google"]) {
    const stack = buildModelStack({ kind, apiKey: "fixture-key-not-real", env: PROD_ENV });
    assert.equal(stack.kind, kind);
    assert.equal(stack.provider.providerName, kind);
    assert.notEqual(stack.provider.providerName, "fake", "有 key 时绝不能装配假模型");
  }
});

test("有 key + baseURL ⇒ openai-compatible 装配成功（真连烟测的同一条路径）", () => {
  const stack = buildModelStack({
    kind: "openai-compatible",
    apiKey: "fixture-key-not-real",
    baseURL: "https://api.siliconflow.cn/v1",
    env: PROD_ENV,
  });
  assert.equal(stack.provider.kind, "openai-compatible");
  assert.ok(stack.gateway instanceof ModelGateway);
});

test("装配出的网关真能跑一轮（空壳自证：fake 档走完 stream）", async () => {
  const stack = buildModelStack({ kind: "fake", env: TEST_ENV });
  const chunks = await collect(
    stack.gateway.stream({ model: "m", messages: [{ role: "user", content: "hi" }] }, makeContext()),
  );
  const text = chunks
    .filter((chunk) => chunk.type === "text_delta")
    .map((chunk) => chunk.text)
    .join("");
  assert.equal(text, DEFAULT_FAKE_TEXT, "网关不是空壳：确实把 provider 的分片透了出来");
  assert.equal(chunks.at(-1).type, "finish");
});

test("buildApp：未给 model ⇒ 不装配（既有行为零变化，CI 无 key 仍可起实例）", async () => {
  const app = buildApp({ enableLogging: false });
  assert.equal(app.modelGateway, undefined);
  await app.close();
});

test("buildApp({ model }) ⇒ 挂上 modelGateway", async () => {
  const app = buildApp({ enableLogging: false, model: { kind: "fake", env: TEST_ENV } });
  assert.ok(app.modelGateway instanceof ModelGateway);
  await app.close();
});

test("buildApp({ model }) 缺 key ⇒ 构建期即 CONFIGURATION_ERROR（启动失败）", () => {
  assertConfigError(
    () => buildApp({ enableLogging: false, model: { kind: "openai", env: PROD_ENV } }),
    /未配置 OPENAI_API_KEY/,
  );
});

test("buildApp({ model }) 生产装配 fake ⇒ 构建期即 CONFIGURATION_ERROR", () => {
  assertConfigError(
    () => buildApp({ enableLogging: false, model: { kind: "fake", env: PROD_ENV } }),
    /只允许在 NODE_ENV=test/,
  );
});
