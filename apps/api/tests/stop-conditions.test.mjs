/**
 * T3-09 · 停止条件矩阵（Harness §8）逐项证明。
 *
 * 判据（卡面验收 ② + 反例 1/2）
 * ---------------------------
 *   **六项各 1 条用例**：`max_model_turns` / `max_tool_calls` / `max_tool_calls_per_turn` /
 *   `max_wall_time_ms` / `max_tokens` / `max_cost` —— 每项耗尽 ⇒ **可解释终态 +
 *   `stop_reason` 精确**（R3-01）。
 *   反例 1「预算耗尽但不终态」⇒ 每项用例都断 `stop === true` 且带 `terminalStatus`。
 *   反例 2「`stop_reason` 与耗尽项不匹配（如 tokens 耗尽写 `budget_turns`）」⇒
 *   A-7 用一张**期望映射表**逐项比对 `source ↔ stopReason`，写错即红。
 *
 * 为什么可以纯函数测：`evaluateStop` 不碰 IO —— 账本是内存对象，上限是入参。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/stop-conditions.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { BudgetLedger } from "@wbtime/domain";

import {
  DEFAULT_STOP_LIMITS,
  evaluateStop,
  needsContinuation,
  NOT_STOPPED,
  toBudgetLimits,
} from "../dist/modules/runtime/stop-conditions.js";

/** 一套宽松上限（单项测试时只收紧要测的那一项）。 */
function looseLimits(overrides = {}) {
  return {
    maxModelTurns: 100,
    maxToolCalls: 100,
    maxToolCallsPerTurn: 100,
    maxWallTimeMs: 10_000_000,
    maxTokens: 1_000_000,
    maxCost: 1_000_000,
    ...overrides,
  };
}

/** 造账本并 start（相位机要求：未 start 时墙钟为 0）。 */
function startedLedger(limits) {
  const ledger = new BudgetLedger(toBudgetLimits(limits));
  ledger.start();
  return ledger;
}

/**
 * 造一个**可控时钟**的账本并把时间推过 `advanceMs`。
 *
 * 为什么必须注入时钟：`BudgetLedger` 的墙钟读 `nowMs()`，真实 `Date.now()` 在
 * 毫秒级上限（如 `maxWallTimeMs: 1`）下**不一定推进** —— 首版用例就是这样假红的
 * （不是实现错，是测法错）。注入时钟后，"超时"成为确定性事实。
 */
function ledgerPastWallClock(limits, advanceMs = 10) {
  let now = 1_000_000;
  const ledger = new BudgetLedger(toBudgetLimits(limits), () => now);
  ledger.start();
  now += advanceMs;
  return ledger;
}

// ---------------------------------------------------------------------------
// A 组 · 六项各一
// ---------------------------------------------------------------------------

test("A-1 · max_model_turns 耗尽 ⇒ FAILED + budget_turns", () => {
  const limits = looseLimits({ maxModelTurns: 2 });
  const ledger = startedLedger(limits);
  ledger.addTurn();
  ledger.addTurn();

  const verdict = evaluateStop(ledger, limits, 0);
  assert.equal(verdict.stop, true, "耗尽必须停（反例 1：不停 ⇒ 红）");
  assert.equal(verdict.source, "max_model_turns");
  assert.equal(verdict.stopReason, "budget_turns", "stop_reason 必须精确");
  assert.equal(verdict.terminalStatus, "FAILED", "预算类只能是 FAILED（R3-04 矩阵）");
  assert.match(verdict.detail, /预算耗尽/);
});

test("A-2 · max_tool_calls 耗尽 ⇒ FAILED + budget_tools", () => {
  const limits = looseLimits({ maxToolCalls: 2 });
  const ledger = startedLedger(limits);
  ledger.addToolCall();
  ledger.addToolCall();

  const verdict = evaluateStop(ledger, limits, 1);
  assert.equal(verdict.stop, true);
  assert.equal(verdict.source, "max_tool_calls");
  assert.equal(verdict.stopReason, "budget_tools");
  assert.equal(verdict.terminalStatus, "FAILED");
});

test("A-3 · max_tool_calls_per_turn 耗尽 ⇒ FAILED + budget_tools（source 可区分）", () => {
  // 累计预算**没耗尽**，只有单轮上限耗尽 —— 这是本条与 A-2 的唯一区别。
  const limits = looseLimits({ maxToolCallsPerTurn: 3 });
  const ledger = startedLedger(limits);

  const verdict = evaluateStop(ledger, limits, 3);
  assert.equal(verdict.stop, true);
  assert.equal(verdict.source, "max_tool_calls_per_turn", "source 必须能区分单轮与累计");
  assert.equal(
    verdict.stopReason,
    "budget_tools",
    "契约 11 值里没有 per-turn 专用码 ⇒ 复用 budget_tools，不自造码"
  );
  assert.equal(verdict.terminalStatus, "FAILED");
  assert.match(verdict.detail, /本轮工具调用超限/);
});

test("A-4 · max_wall_time_ms 耗尽 ⇒ FAILED + wall_time", () => {
  const limits = looseLimits({ maxWallTimeMs: 1 });
  const ledger = ledgerPastWallClock(limits, 10);
  const verdict = evaluateStop(ledger, limits, 0);
  assert.equal(verdict.stop, true);
  assert.equal(verdict.source, "max_wall_time_ms");
  assert.equal(verdict.stopReason, "wall_time");
  assert.equal(verdict.terminalStatus, "FAILED");
});

test("A-5 · max_tokens 耗尽 ⇒ FAILED + budget_tokens", () => {
  const limits = looseLimits({ maxTokens: 100 });
  const ledger = startedLedger(limits);
  ledger.addTokens(60);
  ledger.addTokens(40);

  const verdict = evaluateStop(ledger, limits, 0);
  assert.equal(verdict.stop, true);
  assert.equal(verdict.source, "max_tokens");
  assert.equal(verdict.stopReason, "budget_tokens");
  assert.equal(verdict.terminalStatus, "FAILED");
});

test("A-6 · max_cost 耗尽 ⇒ FAILED + budget_cost", () => {
  const limits = looseLimits({ maxCost: 1 });
  const ledger = startedLedger(limits);
  ledger.addCost(0.4);
  ledger.addCost(0.6);

  const verdict = evaluateStop(ledger, limits, 0);
  assert.equal(verdict.stop, true);
  assert.equal(verdict.source, "max_cost");
  assert.equal(verdict.stopReason, "budget_cost");
  assert.equal(verdict.terminalStatus, "FAILED");
});

// ---------------------------------------------------------------------------
// B 组 · 反例 2：映射必须精确
// ---------------------------------------------------------------------------

test("B-1 · `source ↔ stopReason` 期望映射逐项比对（写错即红）", () => {
  // 这张表就是"耗尽项与 stop_reason 必须匹配"的机器形态。
  const expected = {
    max_model_turns: "budget_turns",
    max_tool_calls: "budget_tools",
    max_tool_calls_per_turn: "budget_tools",
    max_wall_time_ms: "wall_time",
    max_tokens: "budget_tokens",
    max_cost: "budget_cost",
  };

  const cases = [
    ["max_model_turns", looseLimits({ maxModelTurns: 1 }), (l) => l.addTurn(), 0],
    ["max_tool_calls", looseLimits({ maxToolCalls: 1 }), (l) => l.addToolCall(), 0],
    ["max_tool_calls_per_turn", looseLimits({ maxToolCallsPerTurn: 1 }), () => {}, 1],
    ["max_wall_time_ms", looseLimits({ maxWallTimeMs: 1 }), () => {}, 0],
    ["max_tokens", looseLimits({ maxTokens: 1 }), (l) => l.addTokens(1), 0],
    ["max_cost", looseLimits({ maxCost: 1 }), (l) => l.addCost(1), 0],
  ];

  for (const [source, limits, apply, turnToolCalls] of cases) {
    // 墙钟那一项用可控时钟（`maxWallTimeMs: 1` 靠真实时钟不可靠），其余用普通账本。
    const ledger =
      source === "max_wall_time_ms" ? ledgerPastWallClock(limits, 10) : startedLedger(limits);
    apply(ledger);
    const verdict = evaluateStop(ledger, limits, turnToolCalls);
    assert.equal(verdict.source, source, `${source} 的触发源不符`);
    assert.equal(
      verdict.stopReason,
      expected[source],
      `${source} 的 stop_reason 必须是 ${expected[source]}，实测 ${verdict.stopReason}`
    );
  }
});

test("B-2 · 多预算同时耗尽 ⇒ 按 R3-01 固定优先序取最先命中者（turns > tools）", () => {
  const limits = looseLimits({ maxModelTurns: 1, maxToolCalls: 1, maxTokens: 1, maxCost: 1 });
  const ledger = startedLedger(limits);
  ledger.addTurn();
  ledger.addToolCall();
  ledger.addTokens(5);
  ledger.addCost(5);

  const verdict = evaluateStop(ledger, limits, 0);
  assert.equal(verdict.source, "max_model_turns", "四项同爆时取 turns（账本优先序）");
  assert.equal(verdict.stopReason, "budget_turns");
});

test("B-3 · 墙钟优先于单轮上限（外层保护先说话）", () => {
  const limits = looseLimits({ maxWallTimeMs: 1, maxToolCallsPerTurn: 1 });
  const ledger = ledgerPastWallClock(limits, 10);
  const verdict = evaluateStop(ledger, limits, 5);
  assert.equal(verdict.source, "max_wall_time_ms", "墙钟是最外层保护，优先判定");
});

test("B-4 · 未耗尽 ⇒ NOT_STOPPED（stop=false 且三个结果字段全 null）", () => {
  const limits = looseLimits();
  const ledger = startedLedger(limits);
  ledger.addTurn();
  const verdict = evaluateStop(ledger, limits, 0);
  assert.deepEqual(verdict, NOT_STOPPED);
  assert.equal(verdict.stop, false);
  assert.equal(verdict.stopReason, null);
});

// ---------------------------------------------------------------------------
// C 组 · needsContinuation（验收 ③）
// ---------------------------------------------------------------------------

test("C-1 · needsContinuation：三条件缺一即 false", () => {
  const controller = new AbortController();
  const notStopped = NOT_STOPPED;

  assert.equal(
    needsContinuation({ verdict: notStopped, signal: controller.signal, strategyWantsContinue: true }),
    true,
    "未停 + 未取消 + 策略要继续 ⇒ 继续"
  );
  assert.equal(
    needsContinuation({ verdict: notStopped, signal: controller.signal, strategyWantsContinue: false }),
    false,
    "策略说停 ⇒ 停"
  );

  controller.abort();
  assert.equal(
    needsContinuation({ verdict: notStopped, signal: controller.signal, strategyWantsContinue: true }),
    false,
    "已取消 ⇒ 停（即使策略想继续）"
  );
});

test("C-2 · 停止判定命中 ⇒ needsContinuation 恒 false（策略无权推翻）", () => {
  const limits = looseLimits({ maxModelTurns: 1 });
  const ledger = startedLedger(limits);
  ledger.addTurn();
  const verdict = evaluateStop(ledger, limits, 0);

  const controller = new AbortController();
  assert.equal(
    needsContinuation({ verdict, signal: controller.signal, strategyWantsContinue: true }),
    false,
    "预算耗尽时策略不得强行继续"
  );
});

// ---------------------------------------------------------------------------
// D 组 · 配置校验
// ---------------------------------------------------------------------------

test("D-1 · 上限非正数 ⇒ 抛错（0 不等于「不限」）", () => {
  assert.throws(() => toBudgetLimits(looseLimits({ maxModelTurns: 0 })), /必须是有限正数/);
  assert.throws(() => toBudgetLimits(looseLimits({ maxTokens: -1 })), /必须是有限正数/);
});

test("D-2 · 缺省上限是保守值且全部为正", () => {
  for (const [key, value] of Object.entries(DEFAULT_STOP_LIMITS)) {
    assert.ok(Number.isFinite(value) && value > 0, `${key} 必须是正数`);
  }
});
