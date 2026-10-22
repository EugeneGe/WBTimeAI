/**
 * T3-14 · **回放 + 续传 e2e**（DoD#4：`agent_event` 回放 + `Last-Event-ID` gap-aware 续读）。
 *
 * 判据
 * ---
 *   | 编号 | 断言 | 说明 |
 *   |---|---|---|
 *   | P-1 | 回放**幂等**：同一 run 连收两次，帧序列逐帧相同 | 回放是"把已发生的事再发一遍" |
 *   | P-2 | `Last-Event-ID` ⇒ **不重放**已收帧 | 游标语义 |
 *   | P-3 | **断流重连**：第一轮结束时 run **还没终态**（真的断了），带游标续读补齐；并集 == 全量且无重复 | 有限订阅 + 重连 = 本版的续传形态 |
 *   | P-4 | 取消 ⇒ `CANCELLED` ∧ 续读仍 `CANCELLED`（不复活）∧ 无 `agent.completed` | 与不变量 ⑤ 同一口径的 e2e 复核 |
 *
 * 为什么每个用例**各起一个服务**
 * ------------------------
 *   本文件用脚本化假 Provider，而"脚本序列按调用次数推进"是**每实例**计数的。
 *   共用一个服务会让"前一个用例跑完把脚本消耗光"，后一个用例拿到的永远是最后一段脚本
 *   —— 于是 P-3 的 run 会瞬间结束，续传路径**一次都没被走到**（假绿）。
 *   每个用例一份服务 ⇒ 脚本对齐，且"断流"真的可复现。
 *
 * 复跑：`node packages/e2e/tests/runtime/resume.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  assertRealPort,
  call,
  channelOf,
  collectRunFrames,
  createAgent,
  getRun,
  idOf,
  startRun,
  startRuntimeServer,
  streamOnce,
  waitTerminal,
} from "../../lib/runtime-server.mjs";
import { FIXED_USAGE, finalTurn } from "../../lib/fake-provider.mjs";

/** 12 帧（用于从库里算"期望帧 id"）。 */
const RUN_CHANNELS = [
  "agent.started",
  "agent.thinking",
  "message.delta",
  "tool.started",
  "tool.completed",
  "mcp.started",
  "mcp.completed",
  "agent.completed",
  "agent.error",
  "skill.resolved",
  "approval.requested",
  "approval.decided",
];

/**
 * 一轮"带延迟的慢工具调用"（让 run 活过第一轮订阅窗口 ≈2s）。
 *
 * @param {number} index 轮次。
 * @param {number} delayMs 文本增量前的延迟。
 * @returns {Array<object>} chunk 序列。
 */
function slowToolTurn(index, delayMs = 400) {
  return [
    { type: "text_delta", text: `第 ${index} 轮`, delayMs },
    { type: "tool_call", id: `slow-${index}`, name: "shell", input: { command: `echo slow-${index}` } },
    { type: "usage", usage: { ...FIXED_USAGE } },
    { type: "finish", reason: "tool_calls" },
  ];
}

/** 造 8 轮慢工具 + 收尾（≈3.2s，超过有限订阅的 ~2s 窗口）。 */
function slowTurns() {
  const turns = [];
  for (let index = 0; index < 8; index += 1) turns.push(slowToolTurn(index));
  turns.push(finalTurn("慢跑结束。"));
  return turns;
}

/**
 * 起一个服务并做真端口自证。
 *
 * @param {string} label 用例标签（库文件名前缀）。
 * @param {Array<Array<object>>} turns 脚本。
 * @returns {Promise<object>} 服务句柄。
 */
async function boot(label, turns) {
  const server = await startRuntimeServer({ label, turns });
  await assertRealPort(server);
  return server;
}

// ---------------------------------------------------------------------------
// P-1 / P-2 · 回放幂等 + 游标
// ---------------------------------------------------------------------------

test("P-1/P-2 · 回放两次逐帧一致 ∧ Last-Event-ID 不重放已收帧", async (t) => {
  const server = await boot("resume-replay", [finalTurn("回放我。")]);
  try {
    const agent = await createAgent(server, { name: "e2e 回放 Agent" });
    const run = await startRun(server, agent.agentId, { message: "回放我" });
    const terminal = await waitTerminal(server, run.id);
    assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

    const first = await streamOnce(server, run.id);
    const second = await streamOnce(server, run.id);
    t.diagnostic(`回放帧数=${first.length}`);
    assert.ok(first.length >= 4, `至少 4 帧（started/thinking/delta/completed），实测 ${first.length}`);
    assert.deepEqual(second.map(idOf), first.map(idOf), "回放必须幂等（同 run 两次收帧逐帧相同）");
    assert.deepEqual(second.map(channelOf), first.map(channelOf));

    const cursor = idOf(first[2]);
    const resumed = await streamOnce(server, run.id, { lastEventId: cursor });
    assert.deepEqual(
      resumed.map(idOf),
      first.slice(3).map(idOf),
      "带 Last-Event-ID 只能给游标之后的帧（不重放）"
    );

    // 回放不是另造一份：帧 id 必须等于库里「通道行」的 seq 子集
    const rows = server.raw
      .prepare("select seq, type from agent_event where run_id = ? order by seq")
      .all(run.id);
    const expected = rows
      .filter((row) => RUN_CHANNELS.includes(row.type))
      .map((row) => row.seq);
    assert.deepEqual(first.map(idOf), expected, "回放帧 id 必须等于库里通道行的 seq 子集");
  } finally {
    await server.stop();
  }
});

// ---------------------------------------------------------------------------
// P-3 · 断流重连（续传的真实路径）
// ---------------------------------------------------------------------------

test("P-3 · 断流重连：第一轮结束时 run 未终态 ⇒ 带游标补齐；并集 == 全量且无重复", async (t) => {
  const server = await boot("resume-gap", slowTurns());
  try {
    const agent = await createAgent(server, { name: "e2e 续传 Agent" });
    const run = await startRun(server, agent.agentId, { message: "慢一点" });

    // 第一轮：服务端有限订阅会先收尾（run 还没跑完）—— 这就是"断流"
    const firstRound = await streamOnce(server, run.id);
    const midRun = await getRun(server, run.id);
    t.diagnostic(`第一轮帧数=${firstRound.length} run.status=${midRun.status}`);
    assert.ok(firstRound.length > 0, "第一轮应至少收到 agent.started");
    assert.equal(
      midRun.status,
      "RUNNING",
      `第一轮结束时 run 必须还在跑（否则断流没发生，续传路径没被走到）：实测 ${midRun.status}`
    );

    // 带游标续读，直到终态
    const cursor = idOf(firstRound[firstRound.length - 1]);
    // 从第一轮最后的游标续读（**不从头重放**，否则并集里会出现重复帧）
    const resumed = await collectRunFrames(server, run.id, { maxRounds: 40, startCursor: cursor });
    const terminal = await waitTerminal(server, run.id);
    assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

    const allIds = [...firstRound.map(idOf), ...resumed.frames.map(idOf)];
    assert.equal(new Set(allIds).size, allIds.length, "首轮 + 续读不得有重复帧");
    assert.deepEqual(
      allIds,
      [...allIds].sort((a, b) => a - b),
      "并集必须升序（续传是「接着上次的游标往后发」）"
    );
    assert.ok(
      resumed.frames.every((frame) => idOf(frame) > cursor),
      "续读只能给游标之后的帧"
    );
    assert.ok(allIds.length > firstRound.length, "续读必须真的补到了新帧");

    // 终态后的完整回放必须与并集逐帧相同（不多不少、不重排）
    const finalReplay = await collectRunFrames(server, run.id);
    assert.deepEqual(
      finalReplay.frames.map(idOf),
      allIds,
      "终态回放必须与「首轮 + 续读」的并集逐帧相同"
    );
  } finally {
    await server.stop();
  }
});

// ---------------------------------------------------------------------------
// P-4 · 取消（e2e 级复核不变量 ⑤）
// ---------------------------------------------------------------------------

test("P-4 · 取消 ⇒ CANCELLED ∧ 续读仍 CANCELLED（不复活）∧ 无 agent.completed", async () => {
  const server = await boot("resume-cancel", slowTurns());
  try {
    const agent = await createAgent(server, { name: "e2e 取消 Agent" });
    const run = await startRun(server, agent.agentId, { message: "我要取消" });

    // 150ms 后取消（run 每轮 ~400ms × 8 轮 ≈ 3.2s ⇒ 取消必然落在执行中）
    await new Promise((resolve) => setTimeout(resolve, 150));
    const cancelled = await call({
      baseUrl: server.baseUrl,
      method: "POST",
      path: `/api/v1/runs/${run.id}/cancel`,
      token: server.token,
      body: {},
    });
    assert.equal(cancelled.status, 200, cancelled.text);
    assert.equal(cancelled.json.data.status, "CANCELLED", "cancel 响应本身就是 CANCELLED");

    const terminal = await waitTerminal(server, run.id);
    assert.equal(terminal.status, "CANCELLED", JSON.stringify(terminal));
    assert.equal(terminal.stop_reason, "cancelled");

    // 再等一会儿读一次：后台驱动收尾不得把 CANCELLED 覆盖成 SUCCEEDED
    await new Promise((resolve) => setTimeout(resolve, 800));
    const again = await getRun(server, run.id);
    assert.equal(again.status, "CANCELLED", `取消后被复活：${JSON.stringify(again)}`);

    const collected = await collectRunFrames(server, run.id);
    assert.ok(!collected.channels.has("agent.completed"), "被取消的 run 不得发 agent.completed");
    // 取消路径**不产生终态帧**：`cancel` 已把 run 推到终态，`RunEventWriter` 随即拒写
    // （这正是"终态零事件"的直接后果）。可断言的是：流里**没有**任何"冒充成功"的终态帧，
    // 且流本身照常收尾（帧数 > 0，说明客户端不会空等）。
    assert.ok(collected.frames.length > 0, "取消后仍应有已发生的帧可回放（流照常收尾）");
    // 取消前后写进去的帧都在，但**没有**终态帧把这次取消说成"完成"
    const lastChannel = collected.frames
      .map(channelOf)
      .filter((channel) => ["agent.completed", "agent.error"].includes(channel));
    assert.deepEqual(lastChannel, [], `取消的 run 不得有终态帧，实测 ${lastChannel.join(",")}`);
  } finally {
    await server.stop();
  }
});
