/**
 * T2-10 · TS 后端冒烟 case 3 —— SSE 语义的**替代面**（对齐 py `tests/e2e/sse.test.mjs`）。
 *
 * **如实裁定（不是 skip、不是 mock）**：py case-3 打的是 agent run 的 SSE 帧流
 * （9 核心通道逐帧观察）。TS 后端 V0.2.0 的 19 op 里**没有任何 SSE 端点**——
 * `POST /api/v1/agents/{id}/run` 连路由都未注册（agents 族整族不在 19 op 内）。
 * 因此本 case 以可测的等价面替代，逐条可审计：
 *
 *   1. **真进程真端口的活性与壳契约**：`GET /healthz` ⇒ 200 + 四键成功壳 +
 *      `data = {status:"ok", uptime_seconds}`（TS 特有字段，py /health 无此形态）+
 *      `x-request-id` 头与体 `request_id` 相等（「体 == 头」，TS 中间件链的自证）；
 *   2. **content-type 必须是 JSON 而非 text/event-stream** —— 若有人日后把 healthz
 *      误做成 SSE，这里当场红；
 *   3. **SSE 端点确缺的反向证明**：`POST /api/v1/agents/agent_x/run` ⇒ 404 四键失败壳
 *      —— 证明「TS 后端无 SSE 端点」是**实测事实**，不是本套件跳过了它。
 *
 * 该替代与登记同步写入 `T2-10.md`（诚实边界：SSE 通道矩阵在 TS 后端**未验证，
 * 依赖不可得**——V0.3.0 agent 运行时落地后才有可打的对象）。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { assertTsEvidence, startTsBackend } from "./_backend.mjs";

test("case-3-ts-sse：TS 后端无 SSE 端点 ⇒ 以 /healthz 活性 + run 端点确缺（404）替代", { timeout: 120_000 }, async () => {
  const backend = await startTsBackend("sse");
  try {
    // ── 1. /healthz：真端口活性 + 壳契约 + 「体 == 头」 ─────────────────────
    const health = await fetch(`${backend.baseUrl}/healthz`, { signal: AbortSignal.timeout(10_000) });
    const requestId = assertTsEvidence(health, backend);
    assert.equal(health.status, 200, `/healthz 期望 200，实得 ${health.status}`);

    const contentType = health.headers.get("content-type") ?? "";
    assert.match(contentType, /application\/json/, `healthz 必须是 JSON，实得 ${contentType}`);
    assert.equal(
      contentType.includes("text/event-stream"),
      false,
      "healthz 不得是 SSE 流（若这里变红，说明有人把探针做成了 event-stream）",
    );

    const healthBody = await health.json();
    assert.deepEqual(
      Object.keys(healthBody).sort(),
      ["code", "data", "message", "request_id"],
      `healthz 必须是契约四键成功壳 :: ${JSON.stringify(healthBody).slice(0, 300)}`,
    );
    assert.equal(healthBody.code, 0, "成功壳 code 必须 0");
    assert.equal(healthBody.message, "ok", "成功壳 message 恒 ok");
    assert.equal(healthBody.data?.status, "ok", "healthz 的 data.status 恒 ok");
    assert.equal(
      typeof healthBody.data?.uptime_seconds,
      "number",
      "uptime_seconds 是 TS 后端 healthz 特有字段（py /health 无此形态）—— TS 证据之一",
    );
    assert.equal(
      healthBody.request_id,
      requestId,
      "体 request_id 必须等于响应头 x-request-id（「体 == 头」）",
    );

    // ── 2. SSE 端点确缺的反向证明 ──────────────────────────────────────────
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
