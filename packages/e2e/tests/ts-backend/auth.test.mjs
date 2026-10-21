/**
 * T2-10 · TS 后端冒烟 case 1 —— 认证族（语义沿用 `tests/e2e/auth.test.mjs` 的可观测面）。
 *
 * 打的是 **TS 后端**（spawn `apps/api/dist/main.js`，真端口）：
 *
 *   1. `POST /api/v1/auth/register` ⇒ 201 + 四键成功壳（`data` 即 TokenResponse）；
 *   2. `POST /api/v1/auth/login`    ⇒ 200 + `data` 恰 4 键（access_token / refresh_token /
 *      token_type / expires_in，契约 `TokenResponse`）；
 *   3. 错误口令 ⇒ 401 + 四键失败壳（`INVALID_CREDENTIALS` 语义，code ≠ 0）；
 *   4. 连续 5 次错 ⇒ 第 6 次 **423**（`LOGIN_MAX_ATTEMPTS = 5`，T2-04 的锁定闸真接线）。
 *
 * py 版的 case-1 还打了 `POST /workspaces`（workspace 族）——TS 后端按 R-26 **不装配**
 * workspace 路由，故本 case 的「token 真能授权读」改用 TS 后端真实存在的
 * `GET /api/v1/models/credentials`（200 数组）证明，语义等价：令牌可读 ≠ 只是一串字符。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assertTsEvidence,
  registerAndLogin,
  startTsBackend,
  TS_PASSWORD,
} from "./_backend.mjs";

test("case-1-ts-auth：register 201 / login 200 + 4 键 / 错口令 401 / 5 错后第 6 次 423", { timeout: 120_000 }, async () => {
  const backend = await startTsBackend("auth");
  try {
    const username = `ts_smoke_${Date.now()}`;

    // ── 1. register ⇒ 201 + 四键壳 ─────────────────────────────────────────
    const registerResponse = await fetch(`${backend.baseUrl}/api/v1/auth/register`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        username,
        email: `${username}@ts-smoke.test`,
        password: TS_PASSWORD,
        display_name: "TS smoke",
      }),
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(registerResponse, backend);
    assert.equal(registerResponse.status, 201, `register 期望 201，实得 ${registerResponse.status}`);
    const registerBody = await registerResponse.json();
    assert.deepEqual(
      Object.keys(registerBody).sort(),
      ["code", "data", "message", "request_id"],
      `register 必须是契约四键壳 :: ${JSON.stringify(registerBody).slice(0, 300)}`,
    );
    assert.equal(registerBody.code, 0, "成功壳 code 必须 0");
    assert.equal(typeof registerBody.data?.access_token, "string", "register 的 data 必须带 access_token");

    // ── 2. login ⇒ 200 + TokenResponse 恰 4 键 ─────────────────────────────
    const loginResponse = await fetch(`${backend.baseUrl}/api/v1/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password: TS_PASSWORD }),
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(loginResponse, backend);
    assert.equal(loginResponse.status, 200, `login 期望 200，实得 ${loginResponse.status}`);
    const loginBody = await loginResponse.json();
    assert.deepEqual(
      Object.keys(loginBody.data).sort(),
      ["access_token", "expires_in", "refresh_token", "token_type"],
      `TokenResponse 必须恰 4 键 :: ${JSON.stringify(loginBody.data).slice(0, 300)}`,
    );
    assert.equal(loginBody.data.token_type, "bearer", "token_type 恒 bearer");
    assert.equal(typeof loginBody.data.expires_in, "number", "expires_in 必须是数字");
    const token = loginBody.data.access_token;

    // 令牌真能授权读（等价 py case-1 的 workspace 读）：TS 后端 19 op 里用凭据列表。
    const listed = await fetch(`${backend.baseUrl}/api/v1/models/credentials`, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(listed, backend);
    assert.equal(listed.status, 200, `带令牌读列表期望 200，实得 ${listed.status}`);
    const listedBody = await listed.json();
    assert.ok(Array.isArray(listedBody.data), "凭据列表的 data 应为数组");

    // ── 3. 错误口令 ⇒ 401 + 四键失败壳 ─────────────────────────────────────
    const wrong = await fetch(`${backend.baseUrl}/api/v1/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password: "wrong-password-1" }),
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(wrong, backend);
    assert.equal(wrong.status, 401, `错误口令期望 401，实得 ${wrong.status}`);
    const wrongBody = await wrong.json();
    assert.deepEqual(
      Object.keys(wrongBody).sort(),
      ["code", "data", "message", "request_id"],
      "401 必须是契约四键失败壳（无 errors 二层）",
    );
    assert.notEqual(wrongBody.code, 0, "失败壳 code 不得为成功码 0");
    assert.equal(typeof wrongBody.code, "string", "失败码必须是 ErrorCode 字面值");

    // ── 4. 连续 5 次错 ⇒ 第 6 次 423 ───────────────────────────────────────
    // 第 1 次错已在上面（401）；再打 4 次凑满 5 次连续失败，全部 401。
    for (let attempt = 2; attempt <= 5; attempt += 1) {
      const attemptResponse = await fetch(`${backend.baseUrl}/api/v1/auth/login`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password: `wrong-password-${attempt}` }),
        signal: AbortSignal.timeout(10_000),
      });
      assertTsEvidence(attemptResponse, backend);
      assert.equal(
        attemptResponse.status,
        401,
        `连续失败第 ${attempt} 次应仍 401（未达锁定阈值），实得 ${attemptResponse.status}`,
      );
      await attemptResponse.json().catch(() => null);
    }

    // 第 6 次：锁定闸生效 ⇒ 423 + 四键壳。
    const locked = await fetch(`${backend.baseUrl}/api/v1/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password: "wrong-password-6" }),
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(locked, backend);
    assert.equal(locked.status, 423, `第 6 次失败应触发锁定 423，实得 ${locked.status}`);
    const lockedBody = await locked.json();
    assert.deepEqual(
      Object.keys(lockedBody).sort(),
      ["code", "data", "message", "request_id"],
      "423 也必须是契约四键失败壳",
    );
    assert.notEqual(lockedBody.code, 0, "423 的 code 不得为成功码 0");
  } finally {
    await backend.stop();
  }
});
