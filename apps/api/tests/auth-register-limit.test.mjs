/**
 * FIX-04 · 未认证 `POST /auth/register` 限速（20xx 审计 #5 / 裁定 R-34）。
 *
 * 缺陷原文
 * --------
 * `POST /api/v1/auth/register` 没有任何守卫，而 `AuthService.register` 在查重通过后
 * 立刻跑一次 `argon2id`（m=64MiB, t=3, p=4，实测 50～100ms）。单个未认证客户端即可
 * 用串行/并发请求把 CPU 与内存打满 —— 本版唯一的未认证**算力放大面**。
 *
 * 判据（任务书 FIX-04）
 * -------------------
 * ① `limit=2`：夹具自身注册算 1 次，第 2 次 OK，第 3 次 ⇒ **429** +
 *    `code === "RESOURCE_LIMIT_EXCEEDED"` + 四键壳 + `Retry-After` 头存在；
 * ② 被拒的那次**未落库**（按 username 查 `user` 表为 `null`）；
 * ③ **hasher 未被调用** —— 这是"限速在 argon2 之前"的唯一硬证据，也是 DoS 防护成立的前提；
 * ④ 不同 IP 不受前一 IP 影响（按客户端 IP 计数，而不是全局计数）；
 * ⑤ `limit=0` ⇒ 连续 5 次全 201（关闭生效）；
 * ⑥ 滑动窗口：推进 61s 后恢复放行（不是永久封锁）。
 *
 * 怎么拿到"hasher 调用计数"
 * ----------------------
 * `AuthService` 的 `hasher` 是可注入依赖（T2-04 就这么设计的），所以本文件用
 * `buildIdentityStack` 装出真实依赖栈，只把 `auth` 换成一个"记账 hasher"的实例，
 * 再整包注入 `buildApp({ identity })`。**不改生产代码分支**，也不 mock 掉服务本体。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { createSqliteDb } from "@wbtime/db/connection";

import { AuthService } from "../dist/modules/auth/service.js";
import { PasswordHasher } from "../dist/modules/auth/password.js";
import { createRegisterLimiter } from "../dist/modules/auth/register-limiter.js";
import { buildApp, buildIdentityStack } from "../dist/app.js";
import {
  makeApp,
  ROOT,
  seedTenants,
  TENANT_ID,
  TEST_SECRET,
  testConfig,
} from "./routes-harness.mjs";

/** 整份 SQLite DDL（与 `routes-harness.mjs` 同源）。 */
const DDL = readFileSync(join(ROOT, "output", "ddl.sqlite.sql"), "utf8");

/** 建内存库 + 灌 DDL + 种两个租户（需要自定义 identity 的用例用）。 */
function freshConnection() {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  seedTenants(connection.raw);
  return connection;
}

/** 注册载荷（每次换用户名，避免撞 409 干扰限速断言）。 */
function payload(username) {
  return { username, email: `${username}@a.example`, password: "alice-password-2026" };
}

/** 记一次注册请求（默认 IP = 127.0.0.1）。 */
function register(fixture, username, remoteAddress = undefined) {
  return fixture.app.inject({
    method: "POST",
    url: "/api/v1/auth/register",
    payload: payload(username),
    ...(remoteAddress === undefined ? {} : { remoteAddress }),
  });
}

/** 断言失败壳的四个键齐备（契约 `errorEnvelope`）。 */
function assertFourKeyShell(body, label) {
  for (const key of ["code", "message", "data", "request_id"]) {
    assert.ok(Object.hasOwn(body, key), `${label}：失败壳缺 ${key} — ${JSON.stringify(body)}`);
  }
}

// ---------------------------------------------------------------------------
// ① ② 429 + 未落库
// ---------------------------------------------------------------------------

test("FIX-04 ① · limit=2：第 3 次注册 ⇒ 429 RESOURCE_LIMIT_EXCEEDED + Retry-After", async () => {
  // 夹具自己注册了 alice（第 1 次）
  const fixture = await makeApp({ extraEnv: { WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE: "2" } });
  try {
    const second = await register(fixture, "bob");
    assert.equal(second.statusCode, 201, `第 2 次必须放行：${second.statusCode} ${second.body}`);

    const third = await register(fixture, "carol");
    assert.equal(third.statusCode, 429, `第 3 次必须 429：${third.statusCode} ${third.body}`);

    const body = JSON.parse(third.body);
    assertFourKeyShell(body, "429");
    assert.equal(body.code, "RESOURCE_LIMIT_EXCEEDED");
    assert.equal(body.request_id, third.headers["x-request-id"], "体 == 头（请求 id 同源）");

    const retryAfter = third.headers["retry-after"];
    assert.equal(typeof retryAfter, "string", "必须带 Retry-After 头");
    const seconds = Number(retryAfter);
    assert.ok(Number.isInteger(seconds) && seconds >= 1 && seconds <= 60, `Retry-After 应是 1..60 的整数秒，实测 ${retryAfter}`);
    assert.equal(body.data.retry_after_seconds, seconds, "头里的秒数与 data 必须一致（两处同源）");
    assert.equal(body.data.limit_per_minute, 2);
  } finally {
    await fixture.close();
  }
});

test("FIX-04 ② · 被限速拒绝的那次**未落库**（按 username 查为 null）", async () => {
  const fixture = await makeApp({ extraEnv: { WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE: "1" } });
  try {
    const findUser = (username) =>
      fixture.raw.prepare("SELECT id FROM user WHERE username = ?").get(username) ?? null;

    assert.ok(findUser("alice") !== null, "前置：alice 已入库");

    const rejected = await register(fixture, "dave");
    assert.equal(rejected.statusCode, 429, `limit=1 时第 2 次必须 429：${rejected.statusCode}`);

    assert.equal(findUser("dave"), null, "被拒的注册不得写 user 行");
    const sessions = fixture.raw.prepare("SELECT COUNT(*) AS n FROM session").get().n;
    assert.equal(Number(sessions), 1, "被拒的注册不得额外建 session（只有夹具那一条）");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// ③ hasher 未被调用（防护成立的前提）
// ---------------------------------------------------------------------------

test("FIX-04 ③ · 被限速拒时 **hasher 一次都没被调用**（证明限速在 argon2 之前）", async () => {
  const connection = freshConnection();

  /** 记账 hasher：只在 hash/verify 上累加计数，行为仍委托真实现。 */
  const real = new PasswordHasher();
  const counts = { hash: 0, verify: 0 };
  const countingHasher = {
    hash(password) {
      counts.hash += 1;
      return real.hash(password);
    },
    verify(password, stored) {
      counts.verify += 1;
      return real.verify(password, stored);
    },
  };

  const extraEnv = { WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE: "1" };
  const config = testConfig(extraEnv);
  const stack = buildIdentityStack({
    config,
    database: connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
  });
  const app = buildApp({
    config,
    enableLogging: false,
    database: connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
    identity: {
      ...stack,
      // 只替换 auth：限速器仍来自 buildIdentityStack（每次装配一份，验证真实接线）
      auth: new AuthService({
        db: connection.db,
        dialect: "sqlite",
        tenantId: TENANT_ID,
        secretKey: TEST_SECRET,
        hasher: countingHasher,
      }),
    },
  });
  await app.ready();

  try {
    const fixture = { app };
    const first = await register(fixture, "alice");
    assert.equal(first.statusCode, 201, "第 1 次（limit=1 内）必须放行");
    assert.equal(counts.hash, 1, "放行那次必须真的跑过 1 次哈希");

    const rejected = await register(fixture, "erin");
    assert.equal(rejected.statusCode, 429, "第 2 次必须 429");
    assert.equal(
      counts.hash,
      1,
      "③ 被拒时 hasher.hash 调用次数必须**保持 1** —— 若变成 2，说明限速跑到 argon2 之后了，防护等于无效"
    );
    assert.equal(counts.verify, 0, "注册路径不该调用 verify");
  } finally {
    await app.close();
    connection.close();
  }
});

// ---------------------------------------------------------------------------
// ④ 按 IP 计数
// ---------------------------------------------------------------------------

test("FIX-04 ④ · 另一个 IP 不受前一 IP 配额影响（按客户端 IP 计数，不是全局）", async () => {
  const fixture = await makeApp({ extraEnv: { WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE: "2" } });
  try {
    // 127.0.0.1 用满：夹具 1 次 + 本次 1 次
    const sameIp = await register(fixture, "bob");
    assert.equal(sameIp.statusCode, 201);
    const sameIpThird = await register(fixture, "carol");
    assert.equal(sameIpThird.statusCode, 429, "同一 IP 用完配额必须 429");

    // 换 IP ⇒ 仍有自己的配额
    const otherIp = await register(fixture, "dave", "10.0.0.9");
    assert.equal(otherIp.statusCode, 201, `另一个 IP 必须放行：${otherIp.statusCode} ${otherIp.body}`);
    const otherIpAgain = await register(fixture, "erin", "10.0.0.9");
    assert.equal(otherIpAgain.statusCode, 201, "另一个 IP 的第 2 次仍在配额内");
    const otherIpThird = await register(fixture, "frank", "10.0.0.9");
    assert.equal(otherIpThird.statusCode, 429, "另一个 IP 用满后同样 429");

    // 原 IP 仍在限流中（说明两份配额互不干扰，不是"换个 IP 就把全局计数重置"）
    const sameIpStill = await register(fixture, "grace");
    assert.equal(sameIpStill.statusCode, 429);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// ⑤ limit=0 关闭
// ---------------------------------------------------------------------------

test("FIX-04 ⑤ · limit=0 ⇒ 限速关闭：连续 5 次注册全 201", async () => {
  const fixture = await makeApp({ extraEnv: { WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE: "0" } });
  try {
    for (const name of ["u1", "u2", "u3", "u4", "u5"]) {
      const response = await register(fixture, name);
      assert.equal(response.statusCode, 201, `${name} 必须 201：${response.statusCode} ${response.body}`);
    }
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// ⑥ 滑动窗口会过期
// ---------------------------------------------------------------------------

test("FIX-04 ⑥ · 滑动窗口：推进 61s 后恢复放行（不是永久封锁）", async () => {
  const connection = freshConnection();

  const clock = { now: new Date("2026-10-21T12:00:00.000Z") };
  const config = testConfig({ WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE: "2" });
  const stack = buildIdentityStack({
    config,
    database: connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
  });
  const app = buildApp({
    config,
    enableLogging: false,
    database: connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
    identity: {
      ...stack,
      // 假时钟：只有在装配期注入才可能精确验证窗口边界，等真 60s 是不可接受的
      registerLimiter: createRegisterLimiter({ limitPerMinute: 2, now: () => clock.now }),
    },
  });
  await app.ready();

  try {
    const fixture = { app };
    assert.equal((await register(fixture, "alice")).statusCode, 201, "第 1 次");
    assert.equal((await register(fixture, "bob")).statusCode, 201, "第 2 次");
    assert.equal((await register(fixture, "carol")).statusCode, 429, "第 3 次必须 429");

    // 只推进 30s：仍在窗口内 ⇒ 继续 429
    clock.now = new Date(clock.now.getTime() + 30_000);
    assert.equal((await register(fixture, "carol")).statusCode, 429, "30s 后仍在窗口内，必须继续 429");

    // 推进到 61s：最早的两次已滑出窗口 ⇒ 放行
    clock.now = new Date(clock.now.getTime() + 31_000);
    const afterWindow = await register(fixture, "dave");
    assert.equal(afterWindow.statusCode, 201, `滑出窗口后必须放行：${afterWindow.statusCode} ${afterWindow.body}`);
  } finally {
    await app.close();
    connection.close();
  }
});

// ---------------------------------------------------------------------------
// 限速器本体（纯单元：窗口 prune / 内存上界 / 非法阈值）
// ---------------------------------------------------------------------------

test("FIX-04 · 限速器单元：同一 key 的时间戳会 prune（内存上界 = limit）", () => {
  const clock = { now: new Date("2026-10-21T12:00:00.000Z") };
  const limiter = createRegisterLimiter({ limitPerMinute: 2, now: () => clock.now });

  assert.equal(limiter.check("1.1.1.1").allowed, true);
  clock.now = new Date(clock.now.getTime() + 1_000);
  assert.equal(limiter.check("1.1.1.1").allowed, true);
  const denied = limiter.check("1.1.1.1");
  assert.equal(denied.allowed, false);
  // 最早那次发生在 t0，本次判定在 t0+1s ⇒ 还剩 59s（不是 60：退避秒数必须随已经过去的时间递减）
  assert.equal(denied.retryAfterSeconds, 59, "最早那次已过去 1s ⇒ 还剩 59s");

  // 全部滑出窗口后，历史时间戳应被丢掉而不是永久累积
  clock.now = new Date(clock.now.getTime() + 61_000);
  assert.equal(limiter.check("1.1.1.1").allowed, true);
  assert.equal(limiter.size(), 1);
});

test("FIX-04 · 限速器单元：退避秒数随时间递减（不是恒定 60）", () => {
  const clock = { now: new Date("2026-10-21T12:00:00.000Z") };
  const limiter = createRegisterLimiter({ limitPerMinute: 1, now: () => clock.now });

  assert.equal(limiter.check("2.2.2.2").allowed, true);
  clock.now = new Date(clock.now.getTime() + 45_000);
  const denied = limiter.check("2.2.2.2");
  assert.equal(denied.allowed, false);
  assert.equal(denied.retryAfterSeconds, 15, "已过 45s ⇒ 还剩 15s");
});

test("FIX-04 · 限速器单元：key 数超过阈值时清扫过期 IP（内存不无界）", () => {
  const clock = { now: new Date("2026-10-21T12:00:00.000Z") };
  const limiter = createRegisterLimiter({ limitPerMinute: 5, now: () => clock.now });

  for (let index = 0; index < 400; index += 1) limiter.check(`10.0.${index}.1`);
  assert.ok(limiter.size() > 256, `前置：应记录超过 256 个 IP，实测 ${limiter.size()}`);

  // 全部过期后再来一个请求 ⇒ 触发清扫，旧 IP 必须被删掉
  clock.now = new Date(clock.now.getTime() + 61_000);
  limiter.check("10.9.9.9");
  assert.equal(limiter.size(), 1, `过期 IP 必须被清扫，实测 ${limiter.size()}`);
});

test("FIX-04 · 限速器单元：limit=0 不记账；非法阈值抛 TypeError", () => {
  const limiter = createRegisterLimiter({ limitPerMinute: 0 });
  for (let index = 0; index < 100; index += 1) {
    assert.equal(limiter.check("3.3.3.3").allowed, true);
  }
  assert.equal(limiter.size(), 0, "关闭态不得留下任何记账（开关关了就不该有状态）");

  assert.throws(() => createRegisterLimiter({ limitPerMinute: -1 }), (error) => error instanceof TypeError);
  assert.throws(() => createRegisterLimiter({ limitPerMinute: 1.5 }), (error) => error instanceof TypeError);
  assert.throws(() => createRegisterLimiter({ limitPerMinute: Number.NaN }), (error) => error instanceof TypeError);
});
