/**
 * T3-14 · 不变量 ⑤：**取消不复活** + 回放/续传（`Last-Event-ID` gap-aware）。
 *
 * 判据（DoD#1 前 5 条不变量的第 5 条 + DoD#4）
 * ----------------------------------------
 *   | 编号 | 断言 | 机器形态 |
 *   |---|---|---|
 *   | R-1 | 回放：终态 run 的帧按 `id: 1..N` **连续**下发，帧集合 ⊆ 12 帧 | 逐帧 id |
 *   | R-2 | 续读：带 `Last-Event-ID` ⇒ **不重放**已收到的帧 | 帧 id 起点 |
 *   | R-3 | gap-aware：库里缺 `seq=2` ⇒ 只发 `seq=1`（**遇洞即停**，不跳过） | 帧数 + id |
 *   | R-4 | 洞补上后从 `after_seq` 续传 ⇒ 只发洞之后的连续段（不重发 1） | 帧 id 序列 |
 *   | R-5 | **取消不复活**：cancel 后 run 停在 `CANCELLED`，500ms 后仍是（且无 `agent.completed`） | 二次读 + 帧集合 |
 *
 * 为什么 R-5 要"等一会儿再读一次"
 * --------------------------
 *   取消与收尾是两条并发路径：`cancel()` 落终态，后台驱动随后才从内核返回。
 *   若收尾不问"是否已终态"就 `finalize(SUCCEEDED)`，取消会被**覆盖**——而覆盖发生在
 *   cancel 之后几十毫秒，只读一次是抓不到的。所以要等、要二次读。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/invariants/resume.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { finalTurn, makeRunApp, slowToolTurn, sleep, toolTurn } from "./_harness.mjs";

/** 12 帧白名单（R3-11a 的"可下发"集合）。 */
const RUN_CHANNELS = new Set([
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
]);

/** 把 SSE 响应体切成帧块。 */
function splitFrames(body) {
  return String(body)
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk !== "");
}

/** 一帧的 `id:` 值。 */
function idOf(frame) {
  return Number(/^id: (\d+)$/m.exec(frame)?.[1]);
}

/** 一帧的 `event:` 值。 */
function channelOf(frame) {
  return /^event: (.+)$/m.exec(frame)?.[1];
}

/** GET 事件流（真 HTTP 路由；`inject` 不绑端口，但走完整 handler）。 */
async function streamEvents(fixture, runId, options = {}) {
  const response = await fixture.app.inject({
    method: "GET",
    url: `/api/v1/runs/${runId}/events${options.afterSeq === undefined ? "" : `?after_seq=${options.afterSeq}`}`,
    headers: {
      ...fixture.headers,
      ...(options.lastEventId === undefined ? {} : { "last-event-id": String(options.lastEventId) }),
    },
  });
  assert.equal(response.statusCode, 200, response.body);
  assert.match(String(response.headers["content-type"] ?? ""), /text\/event-stream/);
  return splitFrames(response.body);
}

/**
 * 期望的帧 id 序列（= **通道行**的 seq；内部行 `loop.*` / `context.built` 等不进 SSE）。
 *
 * 为什么要从库里算而不是写死 `1..N`：`agent_event` 里混着 turn/step 级**内部行**
 * （R3-11），它们占 seq 但不下发 —— `frameOf` 跳过它们、游标照样前进。
 * 所以帧 id 是"通道行的 seq 子集"，写成 `1..N` 会把正确实现判红。
 */
function expectedFrameIds(fixture, runId) {
  return fixture
    .eventsOf(runId)
    .filter((row) => RUN_CHANNELS.has(row.type))
    .map((row) => row.seq);
}

/** 跑一次成功 run，返回 runId。 */
async function succeededRun(fixture) {
  const started = await fixture.startRun();
  assert.equal(started.response.statusCode, 200, started.response.body);
  const run = JSON.parse(started.response.body).data;
  const terminal = await fixture.waitTerminal(run.id);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));
  return run.id;
}

// ---------------------------------------------------------------------------
// R-1 / R-2 · 回放与续读
// ---------------------------------------------------------------------------

test("R-1/R-2 · 回放逐帧连续 ∧ Last-Event-ID 不重放已收帧", async () => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    const runId = await succeededRun(fixture);

    const expected = expectedFrameIds(fixture, runId);
    assert.ok(expected.length >= 4, `至少 agent.started/thinking/delta/completed 四帧，实测 ${expected.length}`);

    const all = await streamEvents(fixture, runId);
    assert.deepEqual(all.map(idOf), expected, "回放必须逐帧给出全部通道行（不漏、不重、有序）");
    for (const frame of all) {
      assert.ok(RUN_CHANNELS.has(channelOf(frame)), `未知通道 ${channelOf(frame)}`);
    }

    // 续读：从第 2 帧之后 ⇒ 只剩第 3 帧起（不重放已收到的两帧）
    const resumed = await streamEvents(fixture, runId, { lastEventId: expected[1] });
    assert.deepEqual(
      resumed.map(idOf),
      expected.slice(2),
      "带 Last-Event-ID 时不得重放已收到的帧",
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// R-3 / R-4 · gap-aware
// ---------------------------------------------------------------------------

test("R-3/R-4 · 洞 ⇒ 停在洞前；洞补上后从 after_seq 续传", async () => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    const runId = await succeededRun(fixture);
    const before = fixture.eventsOf(runId);
    assert.ok(before.length >= 5, `造洞需要至少 5 条事件，实测 ${before.length}`);

    // 挖洞：删掉 seq=2（模拟"写者崩在中间"或"读到未提交行"）。
    // seq=2 是 `loop.started`（内部行，不下发）—— 它仍然是 seq 序列里的一格：
    // 缺了它，`continualFrom` 在 seq=1 之后期望 2、拿到 3 ⇒ 立即停。
    const victim = before.find((row) => row.seq === 2);
    assert.ok(victim !== undefined, "seq=2 必须存在（否则这个洞造不出来）");
    fixture.raw.prepare("delete from agent_event where run_id = ? and seq = 2").run(runId);

    const gapped = await streamEvents(fixture, runId);
    assert.deepEqual(gapped.map(idOf), [1], `遇洞即停：只应发 seq=1，实测 ${gapped.map(idOf).join(",")}`);

    // 补洞（原样写回），从 after_seq=1 续传 ⇒ 2..N
    fixture.raw
      .prepare("insert into agent_event (id, run_id, type, payload, seq) values (?, ?, ?, ?, ?)")
      .run(victim.id ?? `ab000000-0000-4000-8000-00000000000${victim.seq}`, runId, victim.type, victim.payload, 2);

    const resumed = await streamEvents(fixture, runId, { afterSeq: 1 });
    assert.deepEqual(
      resumed.map(idOf),
      expectedFrameIds(fixture, runId).filter((seq) => seq > 1),
      "补洞后应从 seq>1 起连续下发（不重发 seq=1）",
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// R-5 · 取消不复活
// ---------------------------------------------------------------------------

test("R-5 · 取消后 run 停在 CANCELLED（后台收尾后仍不是 SUCCEEDED）且不发 agent.completed", async () => {
  // 关键设计：**取消窗口必须落在"模型还在流式"的时刻**，而不是"工具执行中"。
  // 因为内核只在两处查 `signal.aborted`（轮首 / 工具执行前）；模型这一轮流完仍会
  // commit + 收敛成 SUCCEEDED。于是"cancel 先落 CANCELLED、内核后返回 SUCCEEDED"
  // 这个竞态真的会发生 —— 收尾若不复核终态，就会把取消覆盖成"复活"。
  const slow = [[
    { type: "text_delta", text: "慢慢想……", delayMs: 800 },
    { type: "usage", usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 } },
    { type: "finish", reason: "model_finish" },
  ]];
  const fixture = await makeRunApp({ turns: slow });
  try {
    const started = await fixture.startRun({ message: "慢速取消" });
    assert.equal(started.response.statusCode, 200, started.response.body);
    const runId = JSON.parse(started.response.body).data.id;

    // 等它真的开始推进（拿到 lease 并发出第一帧），再取消 —— 此刻模型正在流式中
    await fixture.waitFor(
      () => fixture.channelsOf(runId).includes("agent.started"),
      "agent.started",
      10_000,
    );
    await sleep(120);
    const cancelled = await fixture.app.inject({
      method: "POST",
      url: `/api/v1/runs/${runId}/cancel`,
      headers: fixture.headers,
      payload: {},
    });
    assert.equal(cancelled.statusCode, 200, cancelled.body);
    assert.equal(JSON.parse(cancelled.body).data.status, "CANCELLED");

    const first = await fixture.waitTerminal(runId, 20_000);
    assert.equal(first.status, "CANCELLED", JSON.stringify(first));
    assert.equal(first.stop_reason, "cancelled");

    // 关键：等后台驱动**真正收尾**（模型 800ms 才流完），再读一次 ——
    // 不允许被晚到的 SUCCEEDED 覆盖。等待窗口必须大于"取消时刻到内核返回"的间隔。
    await sleep(2000);
    const again = fixture.runRow(runId);
    assert.equal(again.status, "CANCELLED", `取消后被复活：${JSON.stringify(again)}`);
    assert.equal(again.stop_reason, "cancelled");
    assert.ok(!fixture.channelsOf(runId).includes("agent.completed"), "取消的 run 不得发 agent.completed");
  } finally {
    await fixture.close();
  }
});

// COUNTEREXAMPLE: 把 `RunDriver.#settle` 开头的
// `if (current !== null && isTerminalRunStatus(current.status)) return;` 删掉
// （"反正内核会返回最终状态"）⇒ 取消后的 `finalize(SUCCEEDED)` 会覆盖 CANCELLED
// ⇒ R-5 的 `again.status` 变成 SUCCEEDED ⇒ R-5 红；同时 `agent.completed` 会被发出来
// ⇒ R-5 的第二条断言也红（双红）。
// 复跑：改 `apps/api/src/modules/run/driver.ts` 后
//       `pnpm --filter @wbtime/api build && cd apps/api && node --experimental-sqlite --test tests/invariants/resume.test.mjs`
//
// COUNTEREXAMPLE: 把 `continualFrom` 里的 `if (row.seq > expected) break;` 改成
// `continue`（"跳过洞继续发"）⇒ R-3 的 `gapped.map(idOf)` 从 `[1]` 变成 `[1,3,4,…]`
// ⇒ R-3 红。跳过洞等于伪造因果链：前端会看到 tool.completed 却没见过 tool.started。
// 复跑：改 `apps/api/src/modules/run/sse-stream.ts` 后同上命令。
