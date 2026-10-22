/**
 * T3-08 · SSE 下发（12 帧）的行为证明。
 *
 * 判据（卡面验收 ③ + 反例 ③）
 * ------------------------
 *   ① **12 帧逐条可下发**：用 `SSE_CHANNEL_SPECS[channel].requiredPayloadKeys`
 *      **自动**构造最小合法 payload（不手抄字段名 —— 手抄就会漏掉将来新增的必填键），
 *      逐条 `append`，断言 12 条全部成功且 seq 连续。
 *   ② **反例 ③（必红）**：`workflow.started` / `workflow.completed` / `agent.failed` /
 *      `agent.message` 这些**在 19 通道里但不在 12 帧里**的通道 ⇒ `RunChannelRejectedError`，
 *      且**零写**（连 `agent_event` 行都不该多）。
 *   ③ **帧格式**：`id: {seq}\nevent: {channel}\ndata: {json}\n\n`，JSON 紧凑、键序为契约序。
 *   ④ **流只发已发生的**（反例 ② 的一半）：终态 run 的流把已有帧发完就结束，
 *      不产生新事件、不改 run 状态。
 *   ⑤ **不可见 ⇒ 404 JSON 壳**（不是空流）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/sse-dispatch.test.mjs`
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { SSE_CHANNEL_SPECS } from "@wbtime/event";

import {
  RUN_SSE_CHANNELS,
  RunChannelRejectedError,
  RunEventWriter,
} from "../dist/modules/run/event-writer.js";
import { errorOf, makeApp, request, ROOT, TENANT_ID } from "./routes-harness.mjs";
import {
  countRows,
  createAgentWithVersion,
  createConversation,
  seedOtherTenantRun,
  seedRun,
  seedWorkspace,
} from "./fixtures/run-fixture.mjs";

/** 造链。 */
async function seedChain(fixture, runOptions = {}) {
  seedWorkspace(fixture);
  const { agentId, versionId } = await createAgentWithVersion(fixture);
  const conversationId = await createConversation(fixture, agentId);
  const runId = seedRun(fixture, { agentId, versionId, conversationId, ...runOptions });
  return { agentId, versionId, conversationId, runId };
}

/** 按契约的必填键自动构造一份最小合法 payload（不手抄字段名）。 */
function minimalPayload(channel) {
  const spec = SSE_CHANNEL_SPECS[channel];
  assert.ok(spec !== undefined, `通道 ${channel} 不在 19 通道定义里`);
  const values = {};
  for (const key of spec.requiredPayloadKeys) {
    values[key] = key === "iteration" ? 1 : "x";
  }
  return values;
}

/** 把 SSE 响应体切成帧（按空行分隔，丢掉心跳/空段）。 */
function splitFrames(body) {
  return body
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk !== "" && chunk.startsWith("id:"));
}

/** 从一帧里取 `event:` 行。 */
function channelOf(frame) {
  const match = /^event: (.+)$/m.exec(frame);
  return match === null ? null : match[1];
}

// ---------------------------------------------------------------------------
// A 组 · 12 帧
// ---------------------------------------------------------------------------

test("A-1 · 12 帧**逐条**可下发，且 seq 连续（用契约必填键自动构造 payload）", async () => {
  const fixture = await makeApp({ username: "sse-a1" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });

    assert.equal(RUN_SSE_CHANNELS.length, 12, "白名单必须恰好 12 条（R3-11a）");

    let expectedSeq = 1;
    for (const channel of RUN_SSE_CHANNELS) {
      const appended = await writer.append(channel, minimalPayload(channel));
      assert.equal(appended.seq, expectedSeq, `${channel} 的 seq 必须连续`);
      assert.ok(Buffer.isBuffer(appended.frame));
      expectedSeq += 1;
    }

    assert.equal(countRows(fixture, "agent_event", `run_id = '${runId}'`), 12);
  } finally {
    await fixture.close();
  }
});

test("A-2 · 反例③：19 通道里**不在 12 帧**的 7 条一律拒绝，且零写", async () => {
  const fixture = await makeApp({ username: "sse-a2" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });

    // 19 - 12 = 7 条（实测 `SSE_CHANNEL_LIST`）：
    // `workflow.*` 五条 + `knowledge.indexed` + `memory.written`。
    // ⚠️ 19 通道里**没有** `agent.failed` / `agent.message` —— 凭印象写会在这里撞
    //    "通道不在 19 通道定义里"，这条错误信息本身就是一次提醒：白名单要读契约，别记。
    const forbidden = [
      "workflow.started",
      "workflow.node.started",
      "workflow.node.completed",
      "workflow.completed",
      "workflow.failed",
      "knowledge.indexed",
      "memory.written",
    ];
    assert.equal(forbidden.length, 7, "19 通道减去 12 帧应恰好 7 条");

    const before = countRows(fixture, "agent_event", `run_id = '${runId}'`);
    for (const channel of forbidden) {
      await assert.rejects(
        () => writer.append(channel, minimalPayload(channel)),
        (error) => {
          assert.ok(
            error instanceof RunChannelRejectedError,
            `${channel} 必须被 RunChannelRejectedError 拒绝，实测 ${String(error)}`
          );
          return true;
        }
      );
    }
    assert.equal(
      countRows(fixture, "agent_event", `run_id = '${runId}'`),
      before,
      "被拒通道不得写进 agent_event（连一行都不行）"
    );
  } finally {
    await fixture.close();
  }
});

test("A-3 · 未知通道（19 条之外）同样拒绝（不静默丢弃）", async () => {
  const fixture = await makeApp({ username: "sse-a3" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });
    await assert.rejects(
      () => writer.append("agent.unknown_frame", {}),
      (error) => error instanceof RunChannelRejectedError
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B 组 · 帧格式与流
// ---------------------------------------------------------------------------

test("B-1 · 终态 run 的流：帧格式逐字 + 只发已发生的帧", async () => {
  const fixture = await makeApp({ username: "sse-b1" });
  try {
    const { runId, agentId } = await seedChain(fixture, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
      completedAt: "2026-10-22 00:01:00",
    });
    // 先在"非终态"窗口写入 3 帧 —— 方法是先插事件行（绕过 writer 的终态检查，
    // 因为终态检查正是被测对象；这里要的是"库里已有帧"这个前提）。
    fixture.raw
      .prepare("insert into agent_event (id, run_id, type, payload, seq) values (?, ?, ?, ?, ?)")
      .run("aa000000-0000-4000-8000-000000000001", runId, "agent.started", JSON.stringify({ run_id: runId, agent_id: agentId }), 1);
    fixture.raw
      .prepare("insert into agent_event (id, run_id, type, payload, seq) values (?, ?, ?, ?, ?)")
      .run("aa000000-0000-4000-8000-000000000002", runId, "agent.thinking", JSON.stringify({ run_id: runId, iteration: 1 }), 2);
    fixture.raw
      .prepare("insert into agent_event (id, run_id, type, payload, seq) values (?, ?, ?, ?, ?)")
      .run("aa000000-0000-4000-8000-000000000003", runId, "agent.completed", JSON.stringify({ run_id: runId }), 3);

    const response = await request(fixture, "GET", `/api/v1/runs/${runId}/events`);
    assert.equal(response.statusCode, 200);
    assert.match(
      String(response.headers["content-type"] ?? ""),
      /text\/event-stream/,
      "Content-Type 必须是 text/event-stream"
    );

    const frames = splitFrames(response.body);
    assert.equal(frames.length, 3, `应回 3 帧，实测 ${frames.length}`);
    assert.deepEqual(frames.map(channelOf), ["agent.started", "agent.thinking", "agent.completed"]);

    // 逐帧格式：id / event / data 三行 + 紧凑 JSON
    const first = frames[0];
    assert.match(first, /^id: 1$/m);
    assert.match(first, /^event: agent\.started$/m);
    const dataLine = /^data: (.+)$/m.exec(first)?.[1];
    assert.ok(dataLine !== undefined, "必须有 data 行");
    assert.equal(dataLine.includes(" "), false, "JSON 必须紧凑（separators 无空格）");
    assert.equal(JSON.parse(dataLine).run_id, runId);

    // 流不得产生新事件、不得改 run 状态（反例 ② 的一半：读不等于执行）
    assert.equal(countRows(fixture, "agent_event", `run_id = '${runId}'`), 3);
    assert.equal(
      fixture.raw.prepare("select status from agent_run where id = ?").get(runId).status,
      "SUCCEEDED"
    );
  } finally {
    await fixture.close();
  }
});

test("B-2 · 静态：续读链**不得** import 任何执行器（反例 ② 的机械化面）", () => {
  const files = [
    join(ROOT, "apps/api/src/modules/run/sse-stream.ts"),
    join(ROOT, "apps/api/src/routes/runs.ts"),
  ];
  // ⚠️ 判据是**路径片段**（`/tool/` 而不是 `modules/tool`）：同目录下的导入写的是
  //     `../tool/service.js`，用 `modules/tool` 匹配会漏 —— 这条漏过是被 CE-T8-2 注入抓到的。
  const forbiddenPaths = ["/tool/", "/sandbox/", "/runtime/", "agent-loop"];
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    const specifiers = [...source.matchAll(/from\s+"([^"]+)"/g)].map((match) => match[1]);
    assert.ok(specifiers.length > 0, `${file} 应至少有一个 import`);
    for (const specifier of specifiers) {
      for (const forbidden of forbiddenPaths) {
        assert.equal(
          specifier.includes(forbidden),
          false,
          `${file} 从 "${specifier}" 导入了执行器面（命中 "${forbidden}"）—— 续读不得触发执行`
        );
      }
    }
  }
});

test("B-2b · 静态（AUD-11）：SSE handler 必须同时看**取消**与**客户端断开**两个信号，且收尾只在终态丢 controller", () => {
  // 为什么是静态面：`app.inject()` 里没有真实 socket，"客户端中途断开"复现不出来
  // （那条路径只能在真 listen 的集成测试里造，本仓不引入端口绑定）。可机械断言的
  // 是**接线形态**，而 AUD-11 / AUD-02 的缺陷恰恰是接线写错：
  //   · 只传 `service.signalOf(runId)` ⇒ 客户端断开后空轮询到 2s 上限；
  //   · `finally` 里无条件 `service.forget(runId)` ⇒ 在飞 run 的 controller 被丢弃。
  const source = readFileSync(join(ROOT, "apps/api/src/routes/runs.ts"), "utf8");

  assert.match(
    source,
    /AbortSignal\.any\(\s*\[[^\]]*signalOf\(runId\)[^\]]*clientAbort\.signal[^\]]*\]/,
    "必须用 AbortSignal.any([service.signalOf(runId), clientAbort.signal]) —— 两个来源任一置位都要收尾"
  );
  assert.match(
    source,
    /request\.raw\.on\(\s*"close"/,
    "必须监听 request.raw 的 close（浏览器关标签页 / 断网时 signalOf 不会动）"
  );
  assert.match(
    source,
    /request\.raw\.off\(\s*"close"/,
    "监听器必须在收尾时移除（否则长连接反复进入会把 emitter 撑大）"
  );
  assert.match(
    source,
    /forgetIfTerminal\(/,
    "收尾必须用 forgetIfTerminal（AUD-02）：非终态丢弃 controller ⇒ 取消失效"
  );
  assert.equal(
    /service\.forget\(/.test(source),
    false,
    "路由层不得再出现无条件 forget（那是 AUD-02 的成因）"
  );
});

test("B-3 · 不可见 run 的事件流 ⇒ 404 JSON 壳（不是空流）", async () => {
  const fixture = await makeApp({ username: "sse-b3" });
  try {
    const otherRunId = seedOtherTenantRun(fixture);
    const response = await request(fixture, "GET", `/api/v1/runs/${otherRunId}/events`);
    assert.equal(response.statusCode, 404);
    assert.equal(errorOf(response).code, "NOT_FOUND");
    assert.equal(
      String(response.headers["content-type"] ?? "").includes("text/event-stream"),
      false,
      "404 必须是 JSON 壳，不能是 SSE"
    );
  } finally {
    await fixture.close();
  }
});
