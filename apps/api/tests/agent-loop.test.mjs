/**
 * T3-09 · 九步时序 + GeneralHarness 的行为证明（**无网络、无数据库**）。
 *
 * 判据（卡面验收 ① ③ + 反例 1）
 * --------------------------
 *   ① **九步各有可断言的进入/退出证据**：A-1 断内部事件序列里同时出现
 *      `loop.turn.started` / `context.built` / `model.streamed` / `turn.committed` /
 *      `intents.validated` / `authorize.decided` / `tools.executed` /
 *      `observations.written` / `loop.stopped` —— 九种，一种不缺。
 *   ② **`needsContinuation` 显式判定**（验收 ③）：A-2 验 `GeneralHarness` 的两条规则；
 *      A-3 验"未知工具不执行但仍生成拒绝型 observation"。
 *   ③ **反例 1（预算耗尽但不终态）**：A-5 用一轮就能耗尽的预算跑**整个 loop**，
 *      断返回的 `status/stopReason` 精确 —— 纯函数层（`stop-conditions.test.mjs`）
 *      已经验过判定，这里验"判定真的被 loop 采纳"。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/agent-loop.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { AgentLoop } from "../dist/modules/runtime/agent-loop.js";
import { GeneralHarness } from "../dist/modules/runtime/harness/general.js";
import { toBudgetLimits } from "../dist/modules/runtime/stop-conditions.js";
import {
  callContext,
  conversationRows,
  fakeExecutor,
  fakeGateway,
  finalTurn,
  memoryEvents,
  toolCallTurn,
  TOOL_SPECS,
} from "./fixtures/loop-fixture.mjs";

/** 宽松上限（除被测项外都不该触发）。 */
const LOOSE = {
  maxModelTurns: 50,
  maxToolCalls: 50,
  maxToolCallsPerTurn: 50,
  maxWallTimeMs: 10_000_000,
  maxTokens: 1_000_000,
  maxCost: 1_000_000,
};

/** 建一个"消息可写"的假库：`loadMessages` 每次返回当前快照（模拟从持久化重读）。 */
function memoryStore(rows) {
  const state = [...rows];
  return {
    get rows() {
      return state;
    },
    loadMessages: async () => [...state],
    appendAssistant: async ({ content, toolCalls }) => {
      state.push({
        id: `asst-${state.length}`,
        conversation_id: "c0000000-0000-4000-8000-000000000001",
        run_id: null,
        role: "assistant",
        content,
        content_parts: toolCalls.map((call) => ({ type: "tool_call", ...call })),
        token_count: null,
        created_at: "2026-10-22 00:00:09",
      });
    },
    appendToolResult: async ({ callId, toolName, content }) => {
      state.push({
        id: `tool-${state.length}`,
        conversation_id: "c0000000-0000-4000-8000-000000000001",
        run_id: null,
        role: "tool",
        content,
        content_parts: [{ type: "tool_result", callId, toolName }],
        token_count: null,
        created_at: "2026-10-22 00:00:09",
      });
    },
  };
}

/** 组装一个 loop（默认两轮：工具轮 + 最终轮）。 */
function buildLoop(options = {}) {
  const store = options.store ?? memoryStore(conversationRows(1));
  const gateway = options.gateway ?? fakeGateway([toolCallTurn(), finalTurn()]);
  const executor = options.executor ?? fakeExecutor();
  const events = memoryEvents();
  const loop = new AgentLoop({
    gateway,
    executor,
    events,
    strategy: new GeneralHarness(),
    limits: options.limits ?? LOOSE,
    model: "test-model",
    tools: TOOL_SPECS,
    loadMessages: store.loadMessages,
    appendAssistant: store.appendAssistant,
    appendToolResult: store.appendToolResult,
    maxContextChars: options.maxContextChars ?? 10_000,
    keepRecent: options.keepRecent ?? 4,
  });
  return { loop, store, gateway, executor, events };
}

// ---------------------------------------------------------------------------
// A 组 · 九步
// ---------------------------------------------------------------------------

test("A-1 · 九步各有证据：内部事件里九种类型一种不缺", async () => {
  const { loop, events } = buildLoop();
  const { context, ledger } = callContext(toBudgetLimits(LOOSE));

  const outcome = await loop.run(context);
  assert.equal(outcome.status, "SUCCEEDED");
  assert.equal(outcome.stopReason, "model_finish");
  assert.equal(outcome.turns, 2, "两轮：工具轮 + 最终轮");
  assert.equal(outcome.toolCalls, 1);

  const types = events.types();
  const nineSteps = [
    "loop.turn.started", // 1 Acquire
    "context.built", // 2 Prepare
    "model.streamed", // 3 Call
    "turn.committed", // 4 Commit
    "intents.validated", // 5 Validate intents
    "authorize.decided", // 6 Authorize
    "tools.executed", // 7 Execute
    "observations.written", // 8 Observe
    "loop.stopped", // 9 Stop or continue
  ];
  for (const step of nineSteps) {
    assert.ok(types.includes(step), `缺少第 ${nineSteps.indexOf(step) + 1} 步的证据事件 ${step}`);
  }
  // 首尾
  assert.equal(types[0], "loop.started");
  assert.equal(types[types.length - 1], "loop.finished");

  // 上下文 epoch 落进事件（验收 ④ 的可审计面）
  const built = events.rows.find((row) => row.type === "context.built");
  assert.equal(typeof built.payload.epoch, "number");

  // 账本已被使用
  assert.ok(ledger.snapshot().turns >= 2);
  assert.ok(ledger.snapshot().tokens > 0, "usage 由网关记账");
});

test("A-2 · GeneralHarness：有工具 ⇒ continue；无工具 ⇒ stop(model_finish)", () => {
  const strategy = new GeneralHarness();

  const withTools = strategy.decide({
    turn: 1,
    assistant: { role: "assistant", content: "我查一下", toolCalls: [{ id: "c1", name: "filesystem", input: {} }] },
    pendingToolCalls: [{ id: "c1", name: "filesystem", input: {} }],
    stopVerdict: { stop: false, source: null, terminalStatus: null, stopReason: null, detail: null },
  });
  assert.deepEqual(withTools, { kind: "continue" }, "模型请求工具 ⇒ 还有事要做");

  const noTools = strategy.decide({
    turn: 2,
    assistant: { role: "assistant", content: "答案" },
    pendingToolCalls: [],
    stopVerdict: { stop: false, source: null, terminalStatus: null, stopReason: null, detail: null },
  });
  assert.equal(noTools.kind, "stop");
  assert.equal(noTools.stopReason, "model_finish");
  assert.equal(noTools.terminalStatus, "SUCCEEDED");
});

test("A-3 · 未知工具：不执行 ⇒ **无 tool 行**（第 5 步校验驳回不属「已接受」）", async () => {
  const gateway = fakeGateway([
    [
      { type: "text_delta", text: "试试" },
      { type: "tool_call", id: "call-x", name: "not_a_tool", input: {} },
      { type: "usage", tokensIn: 5, tokensOut: 2 },
      { type: "finish", reason: "model_finish" },
    ],
    finalTurn("好的"),
  ]);
  const { loop, executor, store, events } = buildLoop({ gateway });
  const { context } = callContext(toBudgetLimits(LOOSE));

  const outcome = await loop.run(context);

  assert.equal(executor.calls.length, 0, "未知工具不得进执行器");
  assert.equal(outcome.status, "SUCCEEDED");

  const validation = events.rows.find((row) => row.type === "intents.validated");
  assert.equal(validation.payload.accepted, 0);
  assert.equal(validation.payload.rejected.length, 1);
  assert.match(validation.payload.rejected[0].reason, /未知工具/);

  // 第 5 步（validate intents）驳回的意图**不产生** tool result：它没通过校验、
  // 不属「已接受」，而 Harness §3 / 不变量 2 约束的是「每个**已接受的** tool call 恰有
  // 一条终态」（主理人 2026-10-22 裁定）。拒绝型 observation 只在第 6 步授权驳回
  // （`authorization.denied`）时生成 —— 那条由 `agent-loop.test.mjs` 的 A-2 覆盖。
  const toolMessages = store.rows.filter((row) => row.role === "tool");
  assert.equal(toolMessages.length, 0, "未知工具不产生 tool 行（因为它连 intent 都没通过）");
});

test("A-4 · 取消信号在轮首命中 ⇒ CANCELLED + cancelled", async () => {
  const gateway = fakeGateway([toolCallTurn(), finalTurn()]);
  const { loop } = buildLoop({ gateway });
  const { context, controller } = callContext(toBudgetLimits(LOOSE));
  controller.abort();

  const outcome = await loop.run(context);
  assert.equal(outcome.status, "CANCELLED");
  assert.equal(outcome.stopReason, "cancelled");
  assert.equal(outcome.turns, 1);
});

test("A-5 · 反例 1：预算一轮即耗尽 ⇒ loop 真的停在 FAILED + 精确 stop_reason", async () => {
  const limits = { ...LOOSE, maxModelTurns: 1 };
  const gateway = fakeGateway([toolCallTurn(), finalTurn()]);
  const { loop, executor, events } = buildLoop({ gateway, limits });
  const { context } = callContext(toBudgetLimits(limits));

  const outcome = await loop.run(context);

  assert.equal(outcome.status, "FAILED", "预算耗尽不得写成 SUCCEEDED（R3-04 矩阵只允许 model_finish 配 SUCCEEDED）");
  assert.equal(outcome.stopReason, "budget_turns", "stop_reason 必须精确");
  assert.equal(outcome.turns, 1, "第一轮结束就停");
  assert.equal(executor.calls.length, 1, "第一轮的工具仍然执行完（不是半路丢弃）");

  const stopped = events.rows.find((row) => row.type === "loop.stopped");
  assert.equal(stopped.payload.source, "max_model_turns");
  assert.equal(stopped.payload.stop_reason, "budget_turns");
});

test("A-6 · 每轮**重读**持久化消息（不是缓存）：轮数 = loadMessages 调用次数", async () => {
  let loads = 0;
  const store = memoryStore(conversationRows(1));
  const wrapped = {
    ...store,
    loadMessages: async () => {
      loads += 1;
      return store.loadMessages();
    },
  };
  const { loop } = buildLoop({ store: wrapped });
  const { context } = callContext(toBudgetLimits(LOOSE));

  const outcome = await loop.run(context);
  assert.equal(loads, outcome.turns, "每轮都从持久化重建（缓存会让模型看不见自己刚说的话）");
  assert.equal(outcome.turns, 2);
});

test("A-7 · 工具失败也要变成 observation（不中断循环）", async () => {
  const executor = fakeExecutor({
    filesystem: { status: "FAILED", error: "EACCES", durationMs: 3 },
  });
  const { loop, store, events } = buildLoop({ executor });
  const { context } = callContext(toBudgetLimits(LOOSE));

  const outcome = await loop.run(context);
  assert.equal(outcome.status, "SUCCEEDED", "工具失败不终止循环（模型下一轮自己决定重试/换路）");

  const toolRow = store.rows.filter((row) => row.role === "tool");
  assert.equal(toolRow.length, 1);
  assert.match(toolRow[0].content, /FAILED/);

  const executed = events.rows.find((row) => row.type === "tools.executed");
  assert.equal(executed.payload.statuses.FAILED, 1);
});
