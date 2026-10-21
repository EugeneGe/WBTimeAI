/**
 * T2-10 · TS 后端冒烟 case 4 —— 反向段（语义沿用 `tests/reverse/reverse.test.mjs`）。
 *
 * 进程被杀后端口必须**拒绝**连接：只有 `ECONNREFUSED` / `ENOTFOUND` 证明监听者没了；
 * `ETIMEDOUT` 是伪反证（socket 可能被黑洞），断言不符说明请求成功了 —— 两者都必须红。
 *
 * 与 py 版的结构同源：先证「活着」（`/healthz` 200 + spawn pid 存活），再杀，再探 ——
 * 「被杀前是活的」在本文件内自证，不靠编排器假设。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ALLOWED_RED_CAUSES, classifyRedCause } from "../../lib/errors.mjs";
import { assertTsEvidence, isListening, startTsBackend } from "./_backend.mjs";

test("case-4-ts-reverse：kill 后端口必须 ECONNREFUSED（三探针红因一致，非 ETIMEDOUT）", { timeout: 120_000 }, async () => {
  const backend = await startTsBackend("reverse");
  const port = backend.port;

  // ── 前置自证：被杀前它是活的（进程级 + 端口级 + HTTP 级三重证据） ──────────
  assert.equal(typeof backend.pid, "number", "spawn pid 必须是数字");
  assert.doesNotThrow(
    () => process.kill(backend.pid, 0),
    `spawn 的 dist/main.js 进程（pid=${backend.pid}）在 kill 前应存活`,
  );
  assert.equal(await isListening(port), true, `端口 ${port} 在 kill 前应处于监听`);
  const alive = await fetch(`${backend.baseUrl}/healthz`, { signal: AbortSignal.timeout(10_000) });
  assertTsEvidence(alive, backend);
  assert.equal(alive.status, 200, `kill 前 /healthz 期望 200，实得 ${alive.status}`);
  await alive.json().catch(() => null);

  // ── 杀 ─────────────────────────────────────────────────────────────────
  await backend.stop();
  assert.equal(
    await isListening(port),
    false,
    `端口 ${port} 仍在监听：kill 未生效（反向段的前置）`,
  );

  // ── 三探针：每条都必须红在「连接被拒」，红因必须一致 ───────────────────────
  const probes = [
    { label: "GET /healthz", run: () => fetch(`${backend.baseUrl}/healthz`, { signal: AbortSignal.timeout(10_000) }) },
    {
      label: "GET /api/v1/conversations",
      run: () => fetch(`${backend.baseUrl}/api/v1/conversations`, { signal: AbortSignal.timeout(10_000) }),
    },
    {
      label: "POST /api/v1/auth/register",
      run: () =>
        fetch(`${backend.baseUrl}/api/v1/auth/register`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            username: "never",
            email: "never@example.com",
            password: "x",
            display_name: "never",
          }),
          signal: AbortSignal.timeout(10_000),
        }),
    },
  ];

  const verdicts = [];
  for (const probe of probes) {
    let failure = null;
    try {
      const response = await probe.run();
      // fetch resolve 了 = 监听者还在答话 —— 这不是反向证据，必须红。
      failure = new Error(`request succeeded with HTTP ${response.status}: the listener is still up`);
      failure.name = "AssertionError";
    } catch (error) {
      failure = error;
    }
    const verdict = classifyRedCause(failure);
    verdicts.push({ label: probe.label, verdict });
    assert.equal(
      verdict.allowed,
      true,
      `${probe.label} 的红因不合法: cause=${verdict.cause}（允许 ${ALLOWED_RED_CAUSES.join("/")}；`
      + `ETIMEDOUT 不能证明进程已退出，断言不符说明请求成功了）:: ${verdict.detail}`,
    );
    assert.notEqual(
      verdict.cause,
      "ETIMEDOUT",
      `${probe.label} 红在 ETIMEDOUT：这是伪反证（socket 可能只是被黑洞）`,
    );
  }

  // 三探针必须一致：一次幸运的 ECONNREFUSED 不够。
  assert.equal(verdicts.length, probes.length, "三条探针都必须给出判定");
  const causes = new Set(verdicts.map((item) => item.verdict.cause));
  assert.equal(
    causes.size,
    1,
    `三条探针的红因应一致，实得 ${[...causes].join("/")} :: ${JSON.stringify(verdicts.map((item) => ({ label: item.label, cause: item.verdict.cause })))}`,
  );
});
