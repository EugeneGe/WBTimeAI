/**
 * T3-14 · **工具回路 e2e**（真端口 · 真 HTTP · `node:sqlite`）。
 *
 * 判据（DoD#1 的「调工具 → 沙箱执行」段 + T3-10 的四段边界）
 * -----------------------------------------------------
 *   | 编号 | 断言 | 外部证据 |
 *   |---|---|---|
 *   | L-1 | 一轮两个工具调用 ⇒ **两行** `tool_call`，各自终态 | 库里的行 |
 *   | L-2 | 未知工具 ⇒ 第 5 步（validate intents）就拒，**不进执行器** | 无 tool_call 行 + 拒绝型 observation |
 *   | L-3 | `filesystem.write` ⇒ 工作区**真有那个文件** | 文件系统 |
 *   | L-4 | `maxToolCallsPerTurn=1` 且一轮两调 ⇒ 只执行 1 个 ⇒ `budget_tools` | 行数 + stop_reason |
 *   | L-5 | 每个 `call_id` 恰一行终态（e2e 级复核不变量 ③） | 分组计数 |
 *
 * 为什么"未知工具"用 observation 而不是 500
 * ------------------------------------
 *   `AgentLoop` 第 5 步（validate intents）把未知工具拒成**拒绝型 observation**，
 *   模型因此能"看到自己的错并改正"。如果这里返回 500，一次模型幻觉就会让整个 run 崩，
 *   而模型恰恰是最需要看到"这个工具不存在"的一方。
 *
 * 复跑：`node packages/e2e/tests/runtime/tool-loop.mjs`
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test, { after, before } from "node:test";

import {
  assertRealPort,
  collectRunFrames,
  createAgent,
  startRun,
  startRuntimeServer,
  waitTerminal,
} from "../../lib/runtime-server.mjs";
import { FIXED_USAGE, finalTurn, toolTurn } from "../../lib/fake-provider.mjs";

/** 一轮里请求两个工具的脚本。 */
function twoToolTurn(prefix, commandA = "echo one", commandB = "echo two") {
  return [
    { type: "text_delta", text: "两个工具一起调。" },
    { type: "tool_call", id: `${prefix}-a`, name: "shell", input: { command: commandA } },
    { type: "tool_call", id: `${prefix}-b`, name: "shell", input: { command: commandB } },
    { type: "usage", usage: { ...FIXED_USAGE } },
    { type: "finish", reason: "tool_calls" },
  ];
}

let server = null;

before(async () => {
  const turns = [
    // L-1：一轮两调 → 最终答复
    twoToolTurn("multi"),
    finalTurn("两个都跑完了。"),
    // L-2：未知工具 → 最终答复
    toolTurn("unknown-1", "does_not_exist", { anything: true }),
    finalTurn("那我换个说法。"),
    // L-3：filesystem 写 → 最终答复
    toolTurn("fs-1", "filesystem", { action: "write", path: "loop-marker.txt", content: "wbtime-loop" }),
    finalTurn("文件写好了。"),
    // L-4：一轮两调 + 单轮上限 1 ⇒ 只执行 1 个后 budget_tools
    twoToolTurn("limit"),
  ];
  server = await startRuntimeServer({ label: "tool-loop", turns });
  await assertRealPort(server);
});

after(async () => {
  if (server !== null) await server.stop();
});

// ---------------------------------------------------------------------------
// L-1 / L-5 · 一轮两调
// ---------------------------------------------------------------------------

test("L-1/L-5 · 一轮两个工具调用 ⇒ 两行 tool_call，各自恰一终态", async (t) => {
  const agent = await createAgent(server, { name: "e2e 多工具 Agent" });
  const run = await startRun(server, agent.agentId, { message: "同时跑两个命令" });
  const terminal = await waitTerminal(server, run.id);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

  const rows = server.raw
    .prepare("select * from tool_call where run_id = ? order by created_at, id")
    .all(run.id);
  t.diagnostic(`tool_call 行数=${rows.length} :: ${rows.map((row) => `${row.id}:${row.status}`).join(",")}`);
  assert.equal(rows.length, 2, `一轮两调必须两行，实测 ${rows.length}`);
  for (const row of rows) {
    assert.equal(row.status, "SUCCESS", `${row.id} 实测 ${row.status}`);
    assert.ok(typeof row.duration_ms === "number", "终态行必须带 duration_ms");
  }

  // L-5：同一个 call_id 不得出现两行（单终态的结构性保证）
  const grouped = server.raw
    .prepare("select id, count(*) as n from tool_call where run_id = ? group by id")
    .all(run.id);
  for (const item of grouped) assert.equal(item.n, 1, `call_id ${item.id} 出现了 ${item.n} 行`);

  // 帧侧：两次 started / 两次 completed
  const collected = await collectRunFrames(server, run.id);
  const started = collected.frames.filter((frame) => /^event: tool\.started$/m.test(frame)).length;
  const completed = collected.frames.filter((frame) => /^event: tool\.completed$/m.test(frame)).length;
  assert.equal(started, 2, `tool.started 实测 ${started}`);
  assert.equal(completed, 2, `tool.completed 实测 ${completed}`);
});

// ---------------------------------------------------------------------------
// L-2 · 未知工具
// ---------------------------------------------------------------------------

test("L-2 · 未知工具 ⇒ 不进执行器（无 tool_call 行）∧ intents.validated 可审计 ∧ run 继续", async (t) => {
  const agent = await createAgent(server, { name: "e2e 未知工具 Agent" });
  const run = await startRun(server, agent.agentId, { message: "调一个不存在的工具" });
  const terminal = await waitTerminal(server, run.id);
  t.diagnostic(`unknown-tool run ⇒ ${terminal.status}/${terminal.stop_reason}`);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

  const rows = server.raw.prepare("select * from tool_call where run_id = ?").all(run.id);
  assert.equal(rows.length, 0, `未知工具不得产生 tool_call 行，实测 ${rows.length}`);

  // ⚠️ 已知缺口（登记为 T3-14 遗留，**不在本卡修**）：第 5 步（validate intents）
  // 拒绝的意图**不会**生成 tool 消息 —— `agent-loop.ts` 头注释承诺"拒绝型 observation"，
  // 但 `agent-loop.test.mjs` 的 A-3 明确断言 `toolMessages.length === 0`（闭版口径）。
  // 两条互相矛盾，本卡按**闭版断言**为准（不改 T3-09 的已闭版行为），
  // 并把"模型收不到第 5 步拒绝的回音"如实断言出来 —— 而不是假装它收到了。
  const toolMessages = server.raw
    .prepare("select content from message where conversation_id = ? and role = 'tool'")
    .all(run.conversation_id)
    .map((row) => row.content);
  assert.equal(
    toolMessages.length,
    0,
    `现行为：第 5 步拒绝不产生 tool 消息（实测 ${toolMessages.length} 条）—— 见施工记录遗留 R-3`
  );

  // 内部行 `intents.validated` 里能查到这条被拒意图（可审计）
  const validated = server.raw
    .prepare("select payload from agent_event where run_id = ? and type = 'intents.validated'")
    .get(run.id);
  assert.ok(validated !== undefined, "必须有 intents.validated 内部行");
  const payload = JSON.parse(validated.payload);
  assert.equal(payload.rejected.length, 1, `实测 rejected=${JSON.stringify(payload.rejected)}`);
  assert.equal(payload.accepted, 0);
});

// ---------------------------------------------------------------------------
// L-3 · filesystem 写：工作区真有那个文件
// ---------------------------------------------------------------------------

test("L-3 · filesystem.write ⇒ 工作区真有该文件（内容一致）", async (root) => {
  const agent = await createAgent(server, { name: "e2e 文件写 Agent" });
  const run = await startRun(server, agent.agentId, { message: "写一个文件" });
  const terminal = await waitTerminal(server, run.id);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

  const markerPath = join(server.workspaceRoot, run.id, "loop-marker.txt");
  assert.equal(existsSync(markerPath), true, `工作区应有 ${markerPath}`);
  assert.equal(readFileSync(markerPath, "utf8"), "wbtime-loop");
  void root;
});

// ---------------------------------------------------------------------------
// L-4 · 单轮工具上限
// ---------------------------------------------------------------------------

test("L-4 · maxToolCallsPerTurn=1 且一轮两调 ⇒ 只执行 1 个 ⇒ budget_tools(FAILED)", async () => {
  const agent = await createAgent(server, {
    name: "e2e 单轮上限 Agent",
    runtimeConfig: { limits: { maxToolCallsPerTurn: 1 } },
  });
  const run = await startRun(server, agent.agentId, { message: "一次调两个" });
  const terminal = await waitTerminal(server, run.id);
  assert.equal(terminal.status, "FAILED", JSON.stringify(terminal));
  assert.equal(terminal.stop_reason, "budget_tools");

  const rows = server.raw.prepare("select * from tool_call where run_id = ?").all(run.id);
  assert.equal(rows.length, 1, `超出单轮上限的调用不得执行，实测 ${rows.length} 行`);
  assert.equal(rows[0].status, "SUCCESS");

  // 内部行 `tools.executed` 里 skipped_for_turn_limit == 1（可审计的"没执行"证据）
  const executed = server.raw
    .prepare("select payload from agent_event where run_id = ? and type = 'tools.executed'")
    .get(run.id);
  const payload = JSON.parse(executed.payload);
  assert.equal(payload.skipped_for_turn_limit, 1, JSON.stringify(payload));
});
