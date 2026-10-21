/**
 * T2-04 · **J-3 alg 白名单**（计划 §8）+ JWT 其余冻结语义。
 *
 * J-3 的判据是「`alg=none` / `RS256` 伪造 token 一律 401 `AUTH_TOKEN_INVALID`」。
 * 这条判据**只有真造假令牌才有意义** —— 只测"合法 token 能通过"证明不了白名单：
 * 不加白名单的实现在那种测法下同样是绿的。所以下面三条伪造都是**真的构造出来**：
 *
 *  1. `alg=none`：手工拼 `base64url(header).base64url(payload).`（空签名）；
 *  2. `RS256`：用 jose **真生成一对 RSA 密钥**并签名 —— 攻击者能拿到的正是这种令牌；
 *  3. `HS256` 但密钥不同：最朴素的一种，用来确认不是"只要 alg 对就过"。
 *
 * 另外覆盖：过期 → `AUTH_TOKEN_EXPIRED`、类型不符 / iss 不符 / 缺 exp →
 * `AUTH_TOKEN_INVALID`，以及 `TokenResponse` 的四键恒在（`expires_in=900`、`token_type="bearer"`）。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { generateKeyPair, SignJWT } from "jose";

import {
  ACCESS_TTL_SECONDS,
  REFRESH_TTL_SECONDS,
  TOKEN_ISSUER,
  TokenService,
} from "../dist/modules/auth/jwt.js";
import { expectRejected, freshDb, makeService, seedTenant, TENANT_ID, TEST_SECRET } from "./auth-harness.mjs";

const USER_ID = "aaaaaaaa-0000-4000-8000-000000000001";

/** 造一个"看起来完全合法"的 payload（除了它不是我们签的）。 */
function forgedPayload(overrides = {}) {
  const now = Math.floor(Date.now() / 1000);
  return {
    sub: USER_ID,
    tenant_id: TENANT_ID,
    type: "access",
    iss: TOKEN_ISSUER,
    iat: now,
    exp: now + ACCESS_TTL_SECONDS,
    jti: "forged-jti",
    ...overrides,
  };
}

/** base64url（无填充）——JWT 的 header/payload 编码。 */
function b64url(value) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

/** 真库 + 真用户 + 真服务（`authenticate` 需要"用户存在且启用"）。 */
function setup({ now } = {}) {
  const connection = freshDb();
  seedTenant(connection.raw);
  connection.raw
    .prepare(
      "INSERT INTO user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    .run(USER_ID, TENANT_ID, "alice", "alice@a.example", "$argon2id$placeholder", "Alice", 1, 0);
  const service = makeService({ db: connection.db, ...(now ? { now } : {}) });
  return { connection, service };
}

test("合法 access token：claims 七项齐全，且 authenticate 能取到用户（不含口令哈希）", async () => {
  const { connection, service } = setup();
  const tokens = new TokenService(TEST_SECRET);

  const access = await tokens.createAccessToken(USER_ID, {
    tenantId: TENANT_ID,
    sessionId: "session-1",
  });
  const claims = await tokens.decode(access, "access");
  assert.equal(claims.sub, USER_ID);
  assert.equal(claims.tenantId, TENANT_ID);
  assert.equal(claims.type, "access");
  assert.equal(claims.sid, "session-1");
  assert.equal(typeof claims.jti, "string");
  assert.ok(claims.exp instanceof Date);
  assert.equal(claims.raw.iss, TOKEN_ISSUER);
  assert.equal(claims.raw.exp - claims.raw.iat, ACCESS_TTL_SECONDS, "access TTL 必须 900s");

  const user = await service.authenticate(access);
  assert.equal(user.id, USER_ID);
  assert.equal(user.username, "alice");
  assert.equal(Object.hasOwn(user, "password_hash"), false, "对外用户视图不得带口令哈希");
  connection.close();
});

test("J-3 · alg=none 伪造 ⇒ 401 AUTH_TOKEN_INVALID", async () => {
  const { connection, service } = setup();
  const forged = `${b64url({ alg: "none", typ: "JWT" })}.${b64url(forgedPayload())}.`;

  const error = await expectRejected(() => service.authenticate(forged), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "alg=none");
  assert.equal(error.statusCode, 401);
  connection.close();
});

test("J-3 · RS256 伪造（真 RSA 密钥签名）⇒ 401 AUTH_TOKEN_INVALID", async () => {
  const { connection, service } = setup();
  // 真生成一对 RSA 密钥 —— 攻击者手里的令牌就是这种形状，不是"随便拼个串"。
  const { privateKey } = await generateKeyPair("RS256");
  const forged = await new SignJWT(forgedPayload())
    .setProtectedHeader({ alg: "RS256", typ: "JWT" })
    .sign(privateKey);

  await expectRejected(() => service.authenticate(forged), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "RS256");

  // 反向确认：这个令牌确实是我们**之外**的密钥签的（jose 自己能验，说明它格式合法）
  assert.equal(forged.split(".").length, 3);
  const header = JSON.parse(Buffer.from(forged.split(".")[0], "base64url").toString("utf8"));
  assert.equal(header.alg, "RS256", "伪造令牌的 header 必须真的写 RS256");
  connection.close();
});

test("J-3 · HS256 但用别的密钥签 ⇒ 401 AUTH_TOKEN_INVALID", async () => {
  const { connection, service } = setup();
  const forged = await new SignJWT(forgedPayload())
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .sign(new TextEncoder().encode("another-secret-key-0123456789abcdef"));

  await expectRejected(() => service.authenticate(forged), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "wrong-secret-hs256");
  connection.close();
});

test("过期 ⇒ 401 AUTH_TOKEN_EXPIRED（与 INVALID 是两个码，别混）", async () => {
  const { connection, service } = setup();
  // 用一小时前的时钟签发 ⇒ exp 已过；验证时用"现在" ⇒ 必然过期。
  const stale = new TokenService(TEST_SECRET, { now: () => new Date(Date.now() - 3_600_000) });
  const expired = await stale.createAccessToken(USER_ID, { tenantId: TENANT_ID });

  await expectRejected(() => service.authenticate(expired), {
    code: "AUTH_TOKEN_EXPIRED",
    status: 401,
  }, "expired");
  connection.close();
});

test("类型不符 / iss 不符 / 缺 exp / 空串 一律 401 AUTH_TOKEN_INVALID", async () => {
  const { connection, service } = setup();
  const tokens = new TokenService(TEST_SECRET);

  // ① refresh 当 access 用
  const refresh = await tokens.createRefreshToken(USER_ID, { tenantId: TENANT_ID });
  await expectRejected(() => service.authenticate(refresh), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "refresh-as-access");

  // ② iss 不符（同一密钥签的，只有 iss 是假的）
  const wrongIssuer = await new SignJWT(forgedPayload({ iss: "evil-issuer" }))
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .sign(new TextEncoder().encode(TEST_SECRET));
  await expectRejected(() => service.authenticate(wrongIssuer), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "wrong-iss");

  // ③ 缺 exp（py 侧 options.require=["exp","sub"]）
  const noExp = forgedPayload();
  delete noExp.exp;
  const noExpToken = await new SignJWT(noExp)
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .sign(new TextEncoder().encode(TEST_SECRET));
  await expectRejected(() => tokens.decode(noExpToken, "access"), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "missing-exp");

  // ④ 空串
  await expectRejected(() => tokens.decode("", "access"), {
    code: "AUTH_TOKEN_INVALID",
    status: 401,
  }, "empty");
  connection.close();
});

test("TTL 常量与契约对齐（access 900 / refresh 1 209 600）", () => {
  assert.equal(ACCESS_TTL_SECONDS, 900);
  assert.equal(REFRESH_TTL_SECONDS, 1_209_600);
  const tokens = new TokenService(TEST_SECRET);
  assert.equal(tokens.accessTtlSeconds, 900, "expires_in 取它");
  assert.equal(tokens.refreshTtlSeconds, 1_209_600);
});

test("TokenResponse 恒出四键（token_type=bearer / expires_in=900）", async () => {
  const { connection, service } = setup();
  const result = await service.login({ username: "alice", password: "wrong-but-ignored" }).catch(
    (error) => error
  );
  // alice 的哈希是占位串 ⇒ 口令校验必然失败；这里只借 login 走到"被拒"以证明不会签出令牌
  assert.equal(result.code, "AUTH_INVALID_CREDENTIALS");

  // 直接看签发面的四键：用 refresh 之外的路径（register 会真哈希，代价可接受）
  const fresh = await service.register({
    username: "bob",
    email: "bob@a.example",
    password: "bob-password-2026",
  });
  assert.deepEqual(Object.keys(fresh.tokens).sort(), [
    "access_token",
    "expires_in",
    "refresh_token",
    "token_type",
  ]);
  assert.equal(fresh.tokens.token_type, "bearer");
  assert.equal(fresh.tokens.expires_in, 900);
  connection.close();
});
