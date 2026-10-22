/**
 * T2-10 · TS 后端冒烟 case 3 —— SSE 语义的**真实长连接夹具**（V0.2.0 审计 #11）。
 *
 * **演进（#11）**：本 case 原先用 `/healthz` + 404 **替代** SSE 语义。替代面证明的
 * 只是「端点不存在」，从未真正走过 SSE 链路。现在由
 * `packages/e2e/lib/sse-longconn.mjs` 补上真实链路 —— **真建流、真读帧、真断开、
 * 零泄漏**：
 *
 *   1. **真建流**：`fetch(Accept: text/event-stream)` 建真 TCP 长连接（夹具服务端
 *      连接数 0 → 1 可观测）；
 *   2. **真读帧**：`body.getReader()` 逐 chunk 喂 `SseStreamParser`（与 golden 同一
 *      解析实现），逐帧断言 `id` 递增、`event` 通道名、`data` JSON 内容；心跳注释帧
 *      不得被当事件帧；
 *   3. **真断开**：`AbortController.abort()` 客户端主动断；
 *   4. **零泄漏**：断开后夹具服务端连接数必须归零（限时轮询）。
 *
 * **诚实边界（不是 skip、不是 mock）**：TS 后端 V0.2.0 的 19 op 里没有 SSE 端点
 * （V0.3.0 T3-08 才落地 `GET /runs/{id}/events`）。本 case 的第 5 腿保留「后端 SSE
 * 端点确缺」的**反向证明**（`POST /api/v1/agents/agent_x/run` ⇒ 404 四键失败壳），
 * 台账口径仍是「SSE 通道矩阵在 TS 后端未验证（依赖 T3-08 不可得）」；夹具腿证明的
 * 是 SSE 链路机制真实可用，**不得**被读成「SSE 语义已对产品端点验证」。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { openSseStream, startSseFixture } from "../../lib/sse-longconn.mjs";
import { assertTsEvidence, startTsBackend } from "./_backend.mjs";

/** 夹具要下发的真实帧序列（通道名用契约 9 核心通道的子集）。 */
const FIXTURE_FRAMES = Object.freeze([
  { id: 1, event: "agent.started", data: { run_id: "run-fixture-1" } },
  { id: 2, event: "message.delta", data: { text: "你好，SSE 长连接" } },
  { id: 3, event: "agent.completed", data: { stop_reason: "end_turn" } },
]);

test("case-3-ts-sse：真实长连接夹具（真建流/真读帧/真断开/零泄漏）+ TS 后端 SSE 端点确缺（404）", { timeout: 120_000 }, async () => {
  // ── 夹具腿：真实 SSE 长连接 ────────────────────────────────────────────────
  const fixture = await startSseFixture({ frames: [...FIXTURE_FRAMES], frameDelayMs: 15 });
  const controller = new AbortController();
  try {
    // 1. 真建流：连接建立前服务端 0 连接；请求发出后必须升到 1（真 TCP 连接）。
    assert.equal(fixture.connectionCount(), 0, "夹具启动后、建连前必须 0 连接");
    const streamPromise = openSseStream(fixture.url, {
      controller,
      maxFrames: FIXTURE_FRAMES.length,
      timeoutMs: 15_000,
    });
    await fixture.waitForConnections(1, 10_000);

    const stream = await streamPromise;
    assert.equal(stream.response.status, 200, "SSE 建流必须 200");
    assert.match(
      stream.response.headers.get("content-type") ?? "",
      /text\/event-stream/,
      "content-type 必须是 text/event-stream（长连接语义）",
    );

    // 2. 真读帧：帧数、id 序、通道名、data 内容逐帧断言（心跳注释帧不计入）。
    assert.equal(
      stream.frames.length,
      FIXTURE_FRAMES.length,
      `必须收到恰好 ${FIXTURE_FRAMES.length} 个事件帧，实得 ${stream.frames.length}`,
    );
    for (const [index, frame] of stream.frames.entries()) {
      const expected = FIXTURE_FRAMES[index];
      assert.equal(frame.type, "event", `第 ${index + 1} 帧必须是事件帧`);
      assert.equal(frame.id, String(expected.id), `第 ${index + 1} 帧 id 不符`);
      assert.equal(frame.event, expected.event, `第 ${index + 1} 帧通道不符`);
      assert.deepEqual(frame.data, expected.data, `第 ${index + 1} 帧 data 不符`);
    }

    // 3. 真断开：客户端 abort（连接由客户端主动掐断）。
    stream.abort();
    controller.abort();

    // 4. 零泄漏：断开后服务端连接数必须归零（限时轮询，等 close 事件落地）。
    await fixture.waitForConnections(0, 10_000);
    assert.equal(fixture.connectionCount(), 0, "断开后无泄漏连接");
  } finally {
    controller.abort();
    await fixture.stop();
  }

  // ── 后端腿：真进程 + SSE 端点确缺的反向证明（诚实边界，显式登记） ──────────
  const backend = await startTsBackend("sse");
  try {
    const runEndpoint = await fetch(`${backend.baseUrl}/api/v1/agents/agent_x/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message: "hi" }),
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(runEndpoint, backend);
    assert.equal(
      runEndpoint.status,
      404,
      `POST /agents/{id}/run 在 TS 后端应确缺（404），实得 ${runEndpoint.status} —— 出现 200/SSE 流反而说明打错了对象`,
    );
    const runBody = await runEndpoint.json().catch(() => null);
    assert.ok(runBody !== null, "404 也应有可解析的失败壳");
    assert.deepEqual(
      Object.keys(runBody).sort(),
      ["code", "data", "message", "request_id"],
      "SSE 端点缺失的 404 也必须是四键失败壳",
    );
    assert.equal(typeof runBody.code, "string", "失败码必须是 ErrorCode 字面值");
  } finally {
    await backend.stop();
  }
});
