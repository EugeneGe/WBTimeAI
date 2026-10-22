/**
 * V0.3.1 · **R-4** 判据载体（T031-05 · 长连接 + 优雅关闭收敛）。
 *
 * 为什么必须有这个文件（2026-10-23 QA 验收发现）
 * ------------------------------------------
 *   T031-05 把 SSE 从「有限订阅（40 轮 ≈2s，用尽即 `exhausted`）」改成**长连接**，
 *   并给优雅关闭加了 `convergeAllInflightRuns`。但两笔提交（`90b6935` / `0e5fe01`）
 *   **没有留下任何入库判据**：
 *     - `grep -rn "exhausted" --include="*.mjs" apps/api/tests/` ⇒ 空；
 *     - `grep -rn "convergeAllInflightRuns|convergeForShutdown" apps/api/tests/` ⇒ 空。
 *   实测证据只在 `D:/Temp/.../probe-t03105.mjs` 的 P3 / P4（临时探针，不入库）。
 *   ⇒ **长连接与优雅关闭这两个行为当前零防回归门禁**：谁把 `maxPolls` 缺省改回 200、
 *   或把 `convergeAllInflightRuns` 从 `main.ts` 的 close 回调里摘掉，全仓没有一条用例会红。
 *   本文件把这两半补成**入库回归测试**。
 *
 * 判据两半（卡面 R-4 验收逐字）
 * ----------------------------
 *   **R-4-a（终态前不出现 exhausted 收尾）**
 *     单元层：不传 `maxPolls` ⇒ `streamRunFrames` 的 `reason` 只能是 `terminal` 或
 *     `aborted`，**绝不能**是 `exhausted`；且循环必须能活过旧上限（40 × 50ms = 2s）。
 *     HTTP 层：慢 chunk（2.2s）下流仍要等到终态尾帧 `agent.completed`。
 *     **反向**：显式传有限 `maxPolls: 1` ⇒ `reason === "exhausted"`（证明这个出口
 *     还在、且只有显式传才会走到 ⇒ 上面的"绝不 exhausted"不是恒真）。
 *
 *   **R-4-b（进程退出时无 RUNNING 残留）**
 *     `convergeAllInflightRuns` ⇒ 在飞 run 的 `agent_run` 行经 `RunCoordinator.cancel`
 *     的**终态条件写 CAS** 落成 `CANCELLED`（`stop_reason == "cancelled"`），
 *     **不依赖 lease 超时接管**；收敛耗时远短于 lease；收敛后**不复活**。
 *
 * 复跑：cd D:/WBT/WBTimeAI && node --experimental-sqlite --test apps/api/tests/shutdown-convergence.test.mjs
 */

import assert from "node:assert/strict";
import test from "node:test";

import { FIXED_USAGE, makeRunApp } from "./invariants/_harness.mjs";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------------------
// 0 · 判据载体：长连接与收敛的导出面就位（缺失 ⇒ exit 2 语义，用断言显式报）
// ---------------------------------------------------------------------------

test("R-4-0 · 判据载体：streamRunFrames / convergeAllInflightRuns 就位", async () => {
  const sse = await import("../dist/modules/run/sse-stream.js");
  const driver = await import("../dist/modules/run/driver.js");
  assert.equal(typeof sse.streamRunFrames, "function", "streamRunFrames 必须是函数");
  assert.equal(
    typeof driver.convergeAllInflightRuns,
    "function",
    "convergeAllInflightRuns 必须是函数（T031-05 · R-4 接线点）",
  );
  assert.equal(
    typeof driver.SHUTDOWN_INFLIGHT_TIMEOUT_MS,
    "number",
    "SHUTDOWN_INFLIGHT_TIMEOUT_MS 必须导出（main.ts 取预算用）",
  );
});

// ---------------------------------------------------------------------------
// R-4-a · 单元层：不传 maxPolls ⇒ 绝不 exhausted（长连接）
// ---------------------------------------------------------------------------

test("R-4-a1 · 长连接：不传 maxPolls ⇒ 轮询轮数无限（实测轮数 >> 旧缺省 40）", async () => {
  const { streamRunFrames } = await import("../dist/modules/run/sse-stream.js");

  // ⚠️ **为什么用"轮询轮数"而不是"耗时"当判据**（2026-10-23 红证实测暴露的教训）：
  //   第一版写的是「终态在 150ms 后翻转 ⇒ reason 不得为 exhausted」，改坏成
  //   `maxPolls ?? 40` 后它**仍然绿** —— 40 轮 × 10ms = 400ms > 150ms，终态先到，
  //   判据被"跑得快"蒙混过去了。**判据必须钉在"缺省本身"上，不能钉在时序巧合上**
  //   ⇒ 改为：让终态**永不**翻转、轮询间隔 1ms，用外部时钟在 300ms 后中断，
  //   然后数 `readAfter` 被调了几次。**缺省无限 ⇒ 数百轮；缺省 40 ⇒ 恰好 40 轮。**
  //
  // ⚠️ `pollIntervalMs` **不能取 0**：取 0 时循环体内只有 microtask（已 resolved 的
  //   `await`），**永不把控制权交回 macrotask 队列** ⇒ 外部 `setTimeout` 的 abort
  //   **永远不触发** ⇒ 用例自己挂死（2026-10-23 实测：整个文件 60s 超时）。这不是
  //   生产缺陷（生产 `RUN_EVENTS_POLL_MS = 50`），但是写这类"无限循环 + 外部中断"
  //   用例的硬约束，登记在此避免后人重踩。
  const controller = new AbortController();
  let polls = 0;
  // 窗口取 2000ms：Windows `setTimeout` 分辨率约 15ms ⇒ 每轮实际 ≈13–16ms，
  // 2000ms ≈ 130–150 轮，与"旧缺省恰好 40 轮"有 3 倍以上分离度（300ms 只有 ~22 轮，
  // 落在 40 以下、区分不出来 —— 2026-10-23 实测）。
  const timer = setTimeout(() => controller.abort(), 2000);

  try {
    const result = await streamRunFrames({
      readAfter: async () => {
        polls += 1;
        return [];
      },
      isTerminal: async () => false, // 永不终态 ⇒ 只有"轮数用尽"或"中断"能结束循环
      afterSeq: 0,
      pollIntervalMs: 1,
      signal: controller.signal,
      write: () => {},
    });
    assert.equal(result.reason, "aborted", `本例只能由中断结束，实测 ${result.reason}`);
  } finally {
    clearTimeout(timer);
  }

  assert.ok(
    polls > 40,
    `长连接：不传 maxPolls ⇒ 轮询必须无限（实测 ${polls} 轮；若缺省仍是旧的 40 ⇒ 恰好 40 轮 ⇒ 必红）`,
  );
  assert.notEqual(polls, 40, `实测 ${polls} 轮 —— 恰好 40 说明有限缺省回来了`);
});

test("R-4-a2 · 反向（防恒真）：显式传有限 maxPolls ⇒ reason === exhausted", async () => {
  const { streamRunFrames } = await import("../dist/modules/run/sse-stream.js");

  const result = await streamRunFrames({
    readAfter: async () => [],
    isTerminal: async () => false, // 永不终态
    afterSeq: 0,
    pollIntervalMs: 0,
    maxPolls: 1,
    write: () => {},
  });

  assert.equal(
    result.reason,
    "exhausted",
    `反向断言：显式有限 maxPolls 用尽 ⇒ exhausted（证明 R-4-a1 的"绝不 exhausted"不是恒真），实测 ${result.reason}`,
  );
});

test("R-4-a3 · 反向（防恒真）：signal 中断 ⇒ reason === aborted", async () => {
  const { streamRunFrames } = await import("../dist/modules/run/sse-stream.js");
  const controller = new AbortController();
  // ⚠️ 不能把 `abort()` 写在 `write` 回调里：本例 `readAfter` 恒返回空 ⇒ `write`
  // 永不触发 ⇒ 中断永不置位 ⇒ 不传 `maxPolls` 时循环就是**真无限**，用例自己挂死。
  // 长连接正是本卡要验收的行为，所以中断必须由**外部时钟**给出。
  const timer = setTimeout(() => controller.abort(), 30);

  try {
    const result = await streamRunFrames({
      readAfter: async () => [],
      isTerminal: async () => false,
      afterSeq: 0,
      pollIntervalMs: 5,
      signal: controller.signal,
      write: () => {},
    });
    assert.equal(result.reason, "aborted", `中断出口必须在，实测 ${result.reason}`);
  } finally {
    clearTimeout(timer);
  }
});

// ---------------------------------------------------------------------------
// R-4-a · HTTP 层：慢 chunk（2.2s > 旧 2s 上限）下流仍等到终态尾帧
// ---------------------------------------------------------------------------

test("R-4-a4 · 真链路：慢 chunk 下 SSE 流仍等到终态尾帧 agent.completed", async () => {
  // ⚠️ 延迟取 **3000ms**（不是旧探针的 2200ms）：旧有限订阅是 40 轮 × 50ms，
  //   实测每轮还带两次 DB 查询 ⇒ 实际收尾落在 2.0–2.4s 区间，**2200ms 落在边界上**，
  //   改坏成 `?? 40` 时它可能"刚好来得及"而假绿（2026-10-23 红证实测确认）。
  //   取 3000ms ⇒ 远离边界，改坏必红。
  const DELAY_MS = 3000;
  const fixture = await makeRunApp({
    turns: [
      [
        { type: "text_delta", text: "晚到的答复。", delayMs: DELAY_MS },
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "model_finish" },
      ],
    ],
  });
  try {
    const { response } = await fixture.startRun({ message: "R-4-a4" });
    const runId = JSON.parse(response.body).data.id;
    const startedAt = Date.now();
    const stream = await fixture.app.inject({
      method: "GET",
      url: `/api/v1/runs/${runId}/events`,
      headers: fixture.headers,
    });
    const elapsed = Date.now() - startedAt;
    assert.equal(stream.statusCode, 200);

    const events = String(stream.body)
      .split("\n\n")
      .map((chunk) => chunk.trim())
      .filter((chunk) => chunk !== "" && chunk.startsWith("id:"))
      .map((chunk) => /^event: (.+)$/m.exec(chunk)?.[1] ?? null);

    assert.equal(
      events.includes("agent.completed"),
      true,
      "长连接必须等到终态尾帧（旧 40 轮有限订阅在 2s 就收尾，拿不到它）",
    );
    assert.equal(events.includes("message.delta"), true, "终态前的 message.delta 必须已在流里");
    assert.ok(elapsed >= DELAY_MS, `流必须活过旧有限订阅上限（>=${DELAY_MS}ms），实测 ${elapsed}ms`);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// R-4-b · 优雅关闭：在飞 run 经 CAS 落 CANCELLED，不残留 RUNNING
// ---------------------------------------------------------------------------

test("R-4-b1 · 收敛：在飞 run 行经 CAS 落 CANCELLED + 不复活 + 远短于 lease", async () => {
  const { convergeAllInflightRuns } = await import("../dist/modules/run/driver.js");
  const fixture = await makeRunApp({
    turns: [
      [
        { type: "text_delta", text: "慢", delayMs: 30_000 },
        { type: "usage", usage: { ...FIXED_USAGE } },
        { type: "finish", reason: "model_finish" },
      ],
    ],
  });
  try {
    const { response } = await fixture.startRun({ message: "R-4-b1" });
    const runId = JSON.parse(response.body).data.id;
    await fixture.waitFor(() => fixture.runRow(runId).status === "RUNNING", "run 进入 RUNNING");
    assert.equal(fixture.runRow(runId).status, "RUNNING", "前置：run 必须在飞");

    const startedAt = Date.now();
    const convergence = await convergeAllInflightRuns({ timeoutMs: 3_000 });
    const elapsed = Date.now() - startedAt;

    const row = fixture.runRow(runId);
    assert.equal(
      row.status,
      "CANCELLED",
      `在飞 run 必须经终态 CAS 落 CANCELLED（进程退出不留 RUNNING 残留），实测 ${row.status}`,
    );
    assert.equal(row.stop_reason, "cancelled", `实测 stop_reason=${row.stop_reason}`);
    assert.ok(elapsed < 10_000, `收敛必须远短于 lease 接管超时，实测 ${elapsed}ms`);

    await sleep(200);
    assert.equal(fixture.runRow(runId).status, "CANCELLED", "收敛后不得复活");

    // 报告面（不是判据，只是把实测值打出来供台账留痕）。
    assert.equal(typeof convergence.drivers, "number");
    assert.equal(typeof convergence.cancelled, "number");
    assert.equal(typeof convergence.settled, "number");
    assert.equal(typeof convergence.pending, "number");
  } finally {
    await fixture.close();
  }
});
