/**
 * V0.3.1 · **R-1 / G031-5 判据④**判据载体：
 * `message.delta` **逐 chunk 发帧**的**确定性计数**（不是存在性弱断言）。
 *
 * 为什么必须有这个文件（2026-10-23 QA 验收发现）
 * ------------------------------------------
 *   T031-05 的两笔提交（`90b6935` / `0e5fe01`）把 `message.delta` 改成逐 chunk 发帧，
 *   但**没有落任何入库判据载体** —— 全仓 `grep G031-5` 只命中 `driver.ts` 的一行注释，
 *   实测证据只在 `D:/Temp/.../probe-t03105.mjs`（临时探针，提交信息自陈"不入库"）。
 *   按本项目元规则（施工 README §9 纪律 4：给不出复跑命令的事项按**未发生**处理）
 *   ⇒ 判据④不能计入已通过。本文件把它补成**入库回归测试**。
 *
 * 判据形态（§8.1「判据形态升级」(a)，架构采纳）
 * ------------------------------------------
 *   原「帧数 > 1」是**存在性弱断言**（provider 多吐空 delta / 重试补发 / 心跳混入
 *   都能让它成立 ⇒ 假绿）。升级为**确定性计数**：
 *     provider 喂 **N 个已知 chunk** ⇒ `message.delta` 帧数 **== N**，
 *     且 N 帧的 `delta` 拼接 == 该条 assistant 消息全文。
 *   `> 1` **降为地板**（下方 R-1-5 保留作最小反例：仍一条一帧 ⇒ 红），不作主判据。
 *
 * 同时守住 U4 红线（§8.1 四条判据的 ③）
 * -----------------------------------
 *   只改**发帧次数**，不改 payload 形状与 golden：每帧键集合必须逐字等于
 *   `["run_id", "message_id", "role", "delta"]`（`contracts/sse/channels.json` 的
 *   `projected_fields`），一个键都不许多、不许少、不许换序。
 *
 * 反例（改坏必红，逐条对应下方用例）
 * ---------------------------------
 *   - 把 `appendAssistant` 改回"一条消息一帧" ⇒ R-1-1 / R-1-2 / R-1-5 必红；
 *   - 把分片缓冲跨轮不复位（多轮串在一起）⇒ R-1-3 必红；
 *   - 给 payload 加键 / 减键 / 换序 ⇒ R-1-4 必红；
 *   - 帧序错乱或拼接 != 落库全文 ⇒ R-1-2 必红。
 *
 * 复跑：cd D:/WBT/WBTimeAI && node --experimental-sqlite --test apps/api/tests/message-delta-chunk.test.mjs
 */

import assert from "node:assert/strict";
import test from "node:test";

import { FIXED_USAGE, makeRunApp } from "./invariants/_harness.mjs";

/** 喂给 provider 的已知分片（**N = 5**，判据的"已知"就落在这 5 段上）。 */
const CHUNKS = ["你好，", "这里是", "逐 chunk", "发帧的", "五段文本。"];
const FULL_TEXT = CHUNKS.join("");

/** `message.delta` 的帧数据键集合（`contracts/sse/channels.json` 的 `projected_fields`）。 */
const DELTA_KEYS = ["run_id", "message_id", "role", "delta"];

/** 把 SSE 响应体切成帧（只认带 `id:` 的正式数据帧；心跳 `: hb` 不带 `id:`，天然排除）。 */
function splitFrames(body) {
  return String(body)
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk !== "" && chunk.startsWith("id:"));
}

function parseFrame(frame) {
  const event = /^event: (.+)$/m.exec(frame)?.[1] ?? null;
  const id = /^id: (.+)$/m.exec(frame)?.[1] ?? null;
  const data = JSON.parse(/^data: (.+)$/m.exec(frame)?.[1] ?? "null");
  return { event, id, data };
}

/** 跑一次完整 run，返回它的 SSE 帧（真 HTTP 路由 + 真投影，不是内存里的桩）。 */
async function runAndStream(turns, message) {
  const fixture = await makeRunApp({ turns });
  try {
    const { response } = await fixture.startRun({ message });
    assert.equal(response.statusCode, 200, response.body);
    const runId = JSON.parse(response.body).data.id;
    const terminal = await fixture.waitTerminal(runId);
    assert.equal(terminal.status, "SUCCEEDED", `实测 ${terminal.status}`);

    const stream = await fixture.app.inject({
      method: "GET",
      url: `/api/v1/runs/${runId}/events`,
      headers: fixture.headers,
    });
    assert.equal(stream.statusCode, 200);
    return { runId, frames: splitFrames(stream.body).map(parseFrame) };
  } finally {
    await fixture.close();
  }
}

// ---------------------------------------------------------------------------
// R-1-1 · 主判据：N 个已知 chunk ⇒ N 帧（确定性计数，不是 "> 1"）
// ---------------------------------------------------------------------------

test("R-1-1 · 判据④：provider 喂 N 个已知 chunk ⇒ message.delta 帧数 == N", async () => {
  const { frames } = await runAndStream(
    [
      [
        ...CHUNKS.map((text) => ({ type: "text_delta", text })),
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "model_finish" },
      ],
    ],
    "R-1-1",
  );

  const deltaFrames = frames.filter((frame) => frame.event === "message.delta");
  assert.equal(
    deltaFrames.length,
    CHUNKS.length,
    `判据④：帧数必须 == 喂入 chunk 数 ${CHUNKS.length}，实测 ${deltaFrames.length}` +
      `（> 1 只是地板，主判据是 == N）`,
  );
});

// ---------------------------------------------------------------------------
// R-1-2 · N 帧 delta 拼接 == 该条 assistant 消息全文
// ---------------------------------------------------------------------------

test("R-1-2 · N 帧的 delta 拼接 == 该条 assistant 消息全文（逐段顺序一致）", async () => {
  const { frames } = await runAndStream(
    [
      [
        ...CHUNKS.map((text) => ({ type: "text_delta", text })),
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "model_finish" },
      ],
    ],
    "R-1-2",
  );

  const deltas = frames
    .filter((frame) => frame.event === "message.delta")
    .map((frame) => frame.data.delta);
  assert.deepEqual(deltas, CHUNKS, "逐 chunk 的内容与顺序必须与 provider 喂入严格一致");
  assert.equal(deltas.join(""), FULL_TEXT, "N 帧 delta 拼接必须 == 全文");
});

// ---------------------------------------------------------------------------
// R-1-3 · 多轮分片缓冲逐轮复位（防跨轮污染）
// ---------------------------------------------------------------------------

test("R-1-3 · 多轮：tool turn 1 chunk + final turn 3 chunks ⇒ 1 + 3 = 4 帧", async () => {
  const { frames } = await runAndStream(
    [
      [
        { type: "text_delta", text: "我调用工具。" },
        { type: "tool_call", id: "c1", name: "shell", input: { command: "echo hi" } },
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "tool_calls" },
      ],
      [
        { type: "text_delta", text: "第一段。" },
        { type: "text_delta", text: "第二段。" },
        { type: "text_delta", text: "第三段。" },
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "model_finish" },
      ],
    ],
    "R-1-3",
  );

  const deltas = frames
    .filter((frame) => frame.event === "message.delta")
    .map((frame) => frame.data.delta);
  assert.deepEqual(
    deltas,
    ["我调用工具。", "第一段。", "第二段。", "第三段。"],
    `多轮复位：1 + 3 = 4 且逐段对应，实测 ${JSON.stringify(deltas)}`,
  );
});

// ---------------------------------------------------------------------------
// R-1-4 · U4 红线：payload 形状与键序一个键都不变
// ---------------------------------------------------------------------------

test("R-1-4 · U4 红线：每帧键集合 == 契约 projected_fields（不多不少不换序）", async () => {
  const { runId, frames } = await runAndStream(
    [
      [
        ...CHUNKS.map((text) => ({ type: "text_delta", text })),
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "model_finish" },
      ],
    ],
    "R-1-4",
  );

  const deltaFrames = frames.filter((frame) => frame.event === "message.delta");
  assert.ok(deltaFrames.length > 0, "前置：本 run 必须有 message.delta 帧");
  for (const frame of deltaFrames) {
    assert.deepEqual(
      Object.keys(frame.data),
      DELTA_KEYS,
      `payload 键与键序必须与契约逐字一致（实测 ${JSON.stringify(Object.keys(frame.data))}）`,
    );
    assert.equal(frame.data.role, "assistant");
    assert.equal(frame.data.run_id, runId, "帧里的 run_id 必须是本 run");
  }
});

// ---------------------------------------------------------------------------
// R-1-5 · 地板反例：仍"一条消息一帧" ⇒ 必红（§8.1 判据 ④ 的 "> 1" 地板）
// ---------------------------------------------------------------------------

test("R-1-5 · 地板：帧数必须 > 1（仍一条一帧 ⇒ 红）", async () => {
  const { frames } = await runAndStream(
    [
      [
        ...CHUNKS.map((text) => ({ type: "text_delta", text })),
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "model_finish" },
      ],
    ],
    "R-1-5",
  );

  const count = frames.filter((frame) => frame.event === "message.delta").length;
  assert.ok(count > 1, `地板判据：仍一条一帧 ⇒ 必红，实测 ${count}`);
});
