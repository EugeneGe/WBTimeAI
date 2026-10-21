// @wbtime/domain · T3-04 预算账本测试（R3-07 活动时钟）。
//
// 判据（任务卡 T3-04 验收口径 ③ + R3-07）：
//   · 审批等待 = 2 × max_wall_time_ms ⇒ run **不得** wall_time 超限；
//   · duration_ms（活动时钟）不含等待时长；等待单独可观测；
//   · 四项预算优先序 turns > tools > tokens > cost；
//   · 非法相位调用抛错（不静默纠正）。

import assert from "node:assert/strict";
import test from "node:test";

import { BudgetLedger } from "../dist/index.js";

const LIMITS = {
  maxWallTimeMs: 10_000,
  maxTokens: 1_000,
  maxCost: 1,
  maxTurns: 5,
  maxToolCalls: 8,
};

/** 假时钟：手动推进。 */
function fakeClock(start = 1_000_000) {
  let now = start;
  return { now: () => now, advance: (ms) => { now += ms; } };
}

test("审批等待 2× 墙钟预算：活动时钟不增长，恢复后仍可继续（R3-07 主判据）", () => {
  const clock = fakeClock();
  const ledger = new BudgetLedger(LIMITS, clock.now);

  ledger.start();
  clock.advance(3_000); // 已活动 3s
  ledger.pause(); // 进入 WAITING_APPROVAL
  clock.advance(20_000); // 等待 20s（= 2× maxWallTime）
  assert.equal(ledger.activeWallTimeMs, 3_000, "等待期间活动时钟必须冻结");
  assert.equal(ledger.isWallTimeExceeded(), false, "等待不得触发 wall_time");
  assert.equal(ledger.waitingWallTimeMs, 20_000, "等待单独计时");

  ledger.resume();
  clock.advance(2_000); // 再活动 2s ⇒ 合计 5s，仍 < 10s
  assert.equal(ledger.activeWallTimeMs, 5_000);
  assert.equal(ledger.isWallTimeExceeded(), false);

  ledger.stop();
  const snap = ledger.snapshot();
  assert.equal(snap.activeWallTimeMs, 5_000);
  assert.equal(snap.waitingWallTimeMs, 20_000);
  assert.ok(snap.activeWallTimeMs < 25_000, "duration 必须小于墙钟总耗时（等待不计入）");
});

test("活动时钟真的会超限（证明断言不是恒真）", () => {
  const clock = fakeClock();
  const ledger = new BudgetLedger(LIMITS, clock.now);
  ledger.start();
  clock.advance(LIMITS.maxWallTimeMs);
  assert.equal(ledger.isWallTimeExceeded(), true);
});

test("四项预算优先序与边界（>= 视为耗尽）", () => {
  const ledger = new BudgetLedger(LIMITS);
  ledger.start();

  ledger.addTokens(1_000); // 恰好等于上限
  assert.equal(ledger.exceeded(), "budget_tokens");

  ledger.addTurn();
  assert.equal(ledger.exceeded(), "budget_tokens", "turns 还没满");

  for (let i = 0; i < LIMITS.maxTurns - 1; i += 1) ledger.addTurn();
  assert.equal(ledger.exceeded(), "budget_turns", "turns 满后压过 tokens");

  for (let i = 0; i < LIMITS.maxToolCalls; i += 1) ledger.addToolCall();
  assert.equal(ledger.exceeded(), "budget_turns", "turns > tools 的优先序");

  ledger.addCost(1);
  assert.equal(ledger.exceeded(), "budget_turns", "cost 最末，不得抢答");
});

test("非法相位与非法输入都抛错", () => {
  const ledger = new BudgetLedger(LIMITS);
  assert.throws(() => ledger.pause(), /只能在 running/);
  assert.throws(() => ledger.resume(), /只能在 paused/);
  ledger.start();
  assert.throws(() => ledger.start(), /只能在 idle/);
  assert.throws(() => ledger.resume(), /只能在 paused/);
  ledger.pause();
  assert.throws(() => ledger.pause(), /只能在 running/);
  ledger.stop();
  assert.throws(() => ledger.addTokens(-1), /非负有限数/);
  assert.throws(() => ledger.addCost(Number.NaN), /非负有限数/);
  assert.throws(
    () => new BudgetLedger({ ...LIMITS, maxTurns: 0 }),
    /必须是有限正数/,
  );
});

test("重复 stop 幂等；stop 后活动时钟不再增长", () => {
  const clock = fakeClock();
  const ledger = new BudgetLedger(LIMITS, clock.now);
  ledger.start();
  clock.advance(500);
  ledger.stop();
  const frozen = ledger.activeWallTimeMs;
  clock.advance(10_000);
  assert.equal(ledger.activeWallTimeMs, frozen);
  assert.doesNotThrow(() => ledger.stop());
});
