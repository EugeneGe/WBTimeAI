/**
 * T2-10 补 · TS 后端冒烟 case 5 —— **refresh 轮换与旧令牌失效**（V0.2.0 审计 #13 / FIX-10）。
 *
 * 为什么补这一条：冒烟原有 4 个 case 里，`refresh` 这条链路**一次都没被真实端口打过**
 * （`case-1-ts-auth` 只到 register/login）。而"轮换"是本项目最危险的一段状态机：
 * 旧 refresh 若能被二次使用，等于令牌永不过期。所以这里必须过真 TCP 栈、真进程。
 *
 * 断言链（逐条对应契约行为，不是"能返回 200 就算过"）：
 *
 *   1. `register` ⇒ 201（拿到 refresh_0）
 *   2. `login`    ⇒ 200（拿到 refresh_1；本 case 用 login 签发的那条做轮换起点）
 *   3. `refresh`  ⇒ 200 + `TokenResponse` 恰 4 键；新 access **可用**：拿它打
 *      `GET /users/me` ⇒ 200 且 `data.id` 与登录用户一致（证明"新令牌不是一串字符"）
 *   4. **新 refresh ≠ 旧 refresh**（轮换真的换了，不是原样回吐）
 *   5. **旧 refresh 二次使用 ⇒ 401 `AUTH_TOKEN_REVOKED`**（J-4 的正面判据）
 *   6. 二次使用之后，**新 refresh 仍然可用**（1 次）—— 防止"为了拒旧令牌把整条会话族全撤了"
 *      这种过度杀伤：FIX-24 的口径是"只有真正把旧行从 NULL 改成非 NULL 的那一次才签发"，
 *      而不是"一发现复用就核弹整族"。
 *
 * 为什么第 6 条重要：只断言 5 会漏掉「复用检测把新令牌一起废掉」的实现 —— 那种实现
 * 让用户在网络重试场景下被踢下线，且测试看不出来。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { assertTsEvidence, startTsBackend, TS_PASSWORD } from "./_backend.mjs";

/** `TokenResponse` 的契约键集合（恰 4 键，多一个少一个都红）。 */
const TOKEN_KEYS = ["access_token", "expires_in", "refresh_token", "token_type"];

/**
 * 发一个 JSON 请求并返回 `{ response, body }`。
 *
 * @param {object} backend `startTsBackend()` 的返回值。
 * @param {string} path 路径。
 * @param {{method?: string, body?: unknown, token?: string}} [options]
 * @returns {Promise<{response: Response, body: any}>}
 */
async function call(backend, path, options = {}) {
  const method = options.method ?? "GET";
  const headers = {};
  if (options.token !== undefined) headers.authorization = `Bearer ${options.token}`;
  if (options.body !== undefined) headers["content-type"] = "application/json";
  const response = await fetch(`${backend.baseUrl}${path}`, {
    method,
    headers,
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    signal: AbortSignal.timeout(10_000),
  });
  assertTsEvidence(response, backend);
  return { response, body: await response.json() };
}

test(
  "case-5-ts-refresh：轮换后旧 refresh 二次使用 ⇒ 401 AUTH_TOKEN_REVOKED（新 access 仍可用）",
  { timeout: 120_000 },
  async () => {
    const backend = await startTsBackend("refresh");
    try {
      const username = `ts_refresh_${Date.now()}`;
      const email = `${username}@ts-smoke.test`;
      const password = TS_PASSWORD;

      // ── 1. register ⇒ 201（refresh_0 只是链路证据，本 case 用 login 签发的做起点）──
      const registered = await call(backend, "/api/v1/auth/register", {
        method: "POST",
        body: { username, email, password, display_name: "TS refresh" },
      });
      assert.equal(registered.response.status, 201, `register 期望 201，实得 ${registered.response.status}`);
      assert.equal(typeof registered.body.data?.refresh_token, "string", "register 必须回 refresh_token");

      // ── 2. login ⇒ 200（拿到 refresh_old）─────────────────────────────────
      const loggedIn = await call(backend, "/api/v1/auth/login", {
        method: "POST",
        body: { username, password },
      });
      assert.equal(loggedIn.response.status, 200, `login 期望 200，实得 ${loggedIn.response.status}`);
      assert.deepEqual(Object.keys(loggedIn.body.data).sort(), TOKEN_KEYS, "TokenResponse 必须恰 4 键");
      const refreshOld = loggedIn.body.data.refresh_token;
      assert.equal(typeof refreshOld, "string", "login 必须回 refresh_token");

      // ── 3. refresh ⇒ 200 + 新 access 可用 ────────────────────────────────
      const refreshed = await call(backend, "/api/v1/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshOld },
      });
      assert.equal(refreshed.response.status, 200, `refresh 期望 200，实得 ${refreshed.response.status} :: ${JSON.stringify(refreshed.body).slice(0, 300)}`);
      assert.deepEqual(
        Object.keys(refreshed.body.data).sort(),
        TOKEN_KEYS,
        "refresh 响应也必须是 TokenResponse 4 键",
      );
      const accessNew = refreshed.body.data.access_token;
      const refreshNew = refreshed.body.data.refresh_token;

      // 新 access 必须**真能用**（不只是字符串格式对）
      const me = await call(backend, "/api/v1/users/me", { token: accessNew });
      assert.equal(me.response.status, 200, `新 access 打 /users/me 期望 200，实得 ${me.response.status}`);
      assert.equal(me.body.data.username, username, "新 access 必须解析到同一用户");
      assert.equal(typeof me.body.data.id, "string", "/users/me 必须回 id");

      // ── 4. 轮换真的换了（不是原样回吐）───────────────────────────────────
      assert.notEqual(refreshNew, refreshOld, "轮换后的 refresh_token 必须与旧的不同");
      assert.notEqual(accessNew, loggedIn.body.data.access_token, "轮换后的 access_token 必须与旧的不同");

      // ── 5. 旧 refresh 二次使用 ⇒ 401 AUTH_TOKEN_REVOKED ──────────────────
      const reused = await call(backend, "/api/v1/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshOld },
      });
      assert.equal(
        reused.response.status,
        401,
        `旧 refresh 二次使用必须 401，实得 ${reused.response.status} :: ${JSON.stringify(reused.body).slice(0, 300)}`,
      );
      assert.equal(
        reused.body.code,
        "AUTH_TOKEN_REVOKED",
        `错误码必须是 AUTH_TOKEN_REVOKED，实得 ${String(reused.body.code)}`,
      );
      assert.deepEqual(
        Object.keys(reused.body).sort(),
        ["code", "data", "message", "request_id"],
        "401 必须是契约四键失败壳",
      );

      // ── 6. 二次使用后，**新** refresh 仍可用（防过度杀伤）────────────────
      const rotated = await call(backend, "/api/v1/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshNew },
      });
      assert.equal(
        rotated.response.status,
        200,
        `复用检测不得牵连新 refresh：期望 200，实得 ${rotated.response.status} :: ${JSON.stringify(rotated.body).slice(0, 300)}`,
      );
      assert.deepEqual(Object.keys(rotated.body.data).sort(), TOKEN_KEYS, "再次轮换仍是 TokenResponse 4 键");
      assert.notEqual(
        rotated.body.data.refresh_token,
        refreshNew,
        "第二次轮换同样必须换新 refresh",
      );
    } finally {
      await backend.stop();
    }
  },
);
