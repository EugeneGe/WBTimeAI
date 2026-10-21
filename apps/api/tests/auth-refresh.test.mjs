/**
 * T2-04 · **J-4 refresh 轮换**（计划 §8）+ §7 登出语义。
 *
 * 判据原文：「同一 refresh 第 2 次使用 ⇒ 401 `AUTH_TOKEN_REVOKED`；第 1 次刷新后
 * 旧 session `revoked_at` 非空」。后半句**必须查库**才算证 —— 只看响应的话，
 * "撤销了会话"和"只是签了新令牌"在客户端完全一样。
 *
 * 另外覆盖：旧 refresh 行本身也被打上 `revoked_at`、轮换后新 refresh 可用一次、
 * 未入库的合法签名 refresh ⇒ `AUTH_TOKEN_INVALID`、登出幂等（同一 access 连打 2 次）、
 * 全端退出撤销全部会话。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { expectRejected, freshDb, makeService, seedTenant, TENANT_ID } from "./auth-harness.mjs";
import { hashRefreshToken } from "../dist/modules/auth/refresh.js";
import { TokenService } from "../dist/modules/auth/jwt.js";
import { TEST_SECRET } from "./auth-harness.mjs";

/** 注册一个用户并返回服务 + 令牌（每次用独立内存库，互不干扰）。 */
async function setupUser({ username = "alice", password = "alice-password-2026" } = {}) {
  const connection = freshDb();
  seedTenant(connection.raw);
  const service = makeService({ db: connection.db });
  const result = await service.register({ username, email: `${username}@a.example`, password });
  return { connection, service, result };
}

/** 读某会话行的撤销状态（**查库**，不看响应）。 */
function sessionRow(raw, sessionId) {
  return raw.prepare("SELECT id, revoked_at, expires_at FROM session WHERE id = ?").get(sessionId);
}

/** 读某 refresh 哈希对应的行（用来证明"存的是哈希、撤销也落到行上"）。 */
function refreshTokenRow(raw, plaintext) {
  return raw
    .prepare("SELECT id, token_hash, revoked_at FROM refresh_token WHERE token_hash = ?")
    .get(hashRefreshToken(plaintext));
}

/** 从 refresh 令牌里取 `sid`（不验签，仅用于定位行；验签由被测代码负责）。 */
function sessionIdOf(token) {
  const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8"));
  return payload.sid;
}

test("J-4 · 刷新成功 ⇒ 新令牌对；**旧 session 的 revoked_at 非空**（查库）", async () => {
  const { connection, service, result } = await setupUser();
  const oldRefresh = result.tokens.refresh_token;
  const oldSessionId = sessionIdOf(oldRefresh);

  assert.equal(sessionRow(connection.raw, oldSessionId).revoked_at, null, "刷新前旧会话必须是有效状态");

  const refreshed = await service.refresh(oldRefresh);

  assert.notEqual(refreshed.tokens.refresh_token, oldRefresh, "轮换必须换发新 refresh");
  assert.notEqual(refreshed.tokens.access_token, result.tokens.access_token, "access 也必须换新");

  const afterRow = sessionRow(connection.raw, oldSessionId);
  assert.ok(afterRow !== undefined, "旧会话行必须还在（不物理删除，devices 列表要看得到）");
  assert.notEqual(afterRow.revoked_at, null, "旧 session 的 revoked_at 必须非空");

  const oldTokenRow = refreshTokenRow(connection.raw, oldRefresh);
  assert.ok(oldTokenRow !== undefined, "旧 refresh 行必须还在");
  assert.notEqual(oldTokenRow.revoked_at, null, "旧 refresh 行的 revoked_at 必须非空");

  // 新会话是一行**新**的 session
  const newSessionId = sessionIdOf(refreshed.tokens.refresh_token);
  assert.notEqual(newSessionId, oldSessionId, "轮换必须建新会话");
  assert.equal(sessionRow(connection.raw, newSessionId).revoked_at, null);
  connection.close();
});

test("J-4 · 同一 refresh 第 2 次使用 ⇒ 401 AUTH_TOKEN_REVOKED（旧会话已连带撤销）", async () => {
  const { connection, service, result } = await setupUser();
  const refreshToken = result.tokens.refresh_token;

  await service.refresh(refreshToken);

  await expectRejected(() => service.refresh(refreshToken), {
    code: "AUTH_TOKEN_REVOKED",
    status: 401,
  }, "second-use");

  // 第 3 次也一样（不是"只有第二次特殊"）
  await expectRejected(() => service.refresh(refreshToken), {
    code: "AUTH_TOKEN_REVOKED",
    status: 401,
  }, "third-use");
  connection.close();
});

test("轮换出的新 refresh 可用一次，随后同样失效（链式轮换）", async () => {
  const { connection, service, result } = await setupUser();
  const first = await service.refresh(result.tokens.refresh_token);
  const second = await service.refresh(first.tokens.refresh_token);
  assert.ok(second.tokens.refresh_token);
  await expectRejected(() => service.refresh(first.tokens.refresh_token), {
    code: "AUTH_TOKEN_REVOKED",
    status: 401,
  }, "chain-reuse");
  connection.close();
});

test("签名合法但从未入库的 refresh ⇒ 401 AUTH_TOKEN_INVALID（与「已撤销」区分，对齐 py）", async () => {
  const { connection, service } = await setupUser();
  const tokens = new TokenService(TEST_SECRET);
  const fabricated = await tokens.createRefreshToken("aaaaaaaa-0000-4000-8000-000000000009", {
    tenantId: TENANT_ID,
    sessionId: "99999999-9999-4999-8999-999999999999",
  });

  await expectRejected(() => service.refresh(fabricated), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "unknown-refresh");
  connection.close();
});

test("access 当 refresh 用（类型不符）⇒ 401 AUTH_TOKEN_INVALID", async () => {
  const { connection, service, result } = await setupUser();
  await expectRejected(() => service.refresh(result.tokens.access_token), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "access-as-refresh");
  connection.close();
});

test("§7 登出幂等：同一 access 连打 2 次都成功（解码不查 session）", async () => {
  const { connection, service, result } = await setupUser();
  const access = result.tokens.access_token;
  const sessionId = sessionIdOf(result.tokens.refresh_token);

  await service.logout(access);
  assert.notEqual(sessionRow(connection.raw, sessionId).revoked_at, null, "登出必须撤销会话");
  assert.notEqual(
    refreshTokenRow(connection.raw, result.tokens.refresh_token).revoked_at,
    null,
    "登出必须连带撤销该会话的 refresh"
  );

  // 第二次必须**不抛**（幂等）—— 这条证明"解码不查 session.revoked_at"
  await service.logout(access);

  // 登出后旧 access 仍能用（access 无状态，≤900s）—— 这是继承语义，不是缺陷
  const user = await service.authenticate(access);
  assert.equal(user.username, "alice", "登出后 access 在 exp 前仍有效（§3.2 继承语义）");

  // 而旧 refresh 立刻失效
  await expectRejected(() => service.refresh(result.tokens.refresh_token), {
    code: "AUTH_TOKEN_REVOKED",
    status: 401,
  }, "refresh-after-logout");
  connection.close();
});

test("§7 全端退出：撤销该用户全部会话（多设备），且不回撤销数量", async () => {
  const { connection, service, result } = await setupUser();
  // 同一用户再登录两次（多会话并存 —— 本版不设上限、不踢旧会话）
  const second = await service.login({ username: "alice", password: "alice-password-2026" });
  const third = await service.login({ username: "alice", password: "alice-password-2026" });

  const sessions = [result, second, third].map((item) => sessionIdOf(item.tokens.refresh_token));
  for (const id of sessions) {
    assert.equal(sessionRow(connection.raw, id).revoked_at, null, "退出前三条都应有效");
  }

  const returned = await service.logoutAll(third.tokens.access_token);
  assert.equal(returned, undefined, "契约不回撤销数量（MessageResponse 只有 message）");

  for (const id of sessions) {
    assert.notEqual(sessionRow(connection.raw, id).revoked_at, null, `会话 ${id} 必须被撤销`);
  }
  for (const item of [result, second, third]) {
    await expectRejected(() => service.refresh(item.tokens.refresh_token), {
      code: "AUTH_TOKEN_REVOKED",
      status: 401,
    }, "refresh-after-logout-all");
  }
  connection.close();
});

test("refresh 令牌只存哈希：库里不得出现明文", async () => {
  const { connection, result } = await setupUser();
  const plaintext = result.tokens.refresh_token;
  const stored = connection.raw
    .prepare("SELECT token_hash FROM refresh_token")
    .all()
    .map((row) => row.token_hash);

  assert.equal(stored.length, 1);
  assert.equal(stored[0], hashRefreshToken(plaintext), "库里必须是 sha256 hex");
  assert.equal(stored[0].includes(plaintext), false, "库里不得出现 refresh 明文");
  assert.match(stored[0], /^[0-9a-f]{64}$/, "必须是 64 位 hex");
  connection.close();
});
