/**
 * FIX-24 · refresh 轮换的 TOCTOU（time-of-check-to-time-of-use）—— 20xx 审计 P2。
 *
 * 缺陷原文
 * --------
 * 旧路径 `find → revoke → issue`：两个并发请求若**都**先完成「未撤销」校验，
 * 就会各自撤销旧会话、各自签发一对新令牌 —— 同一 refresh 换来两对有效令牌
 * （数据面：3 条会话 / 3 条 refresh）。
 *
 * 修复口径（任务书 FIX-24）
 * ----------------------
 * 以「**affected rows**」为准：只有真正把 `revoked_at` 从 NULL 改成非 NULL 的那一次
 * 才允许签发；否则 401 `AUTH_TOKEN_REVOKED`。`RefreshTokenRepo.revoke` 返回
 * `boolean`（`rows.length > 0`），正是本判据的天然载体。
 *
 * ⚠️ 为什么必须「人为制造交错」才算证到
 * ----------------------------------
 * 本机实测：直接 `Promise.allSettled([refresh(t), refresh(t)])` 时**旧代码也是绿的** ——
 * 因为请求 A 从"校验通过"到"撤销旧会话"之间的 await 链恰好短于 B 走到校验的时间，
 * 自然交错下 B 读到的已经是撤销后的行。也就是说**自然并发测不出这个缺陷**（它只在
 * 更长的交错窗口里出现），拿它当红证会得出"改前改后都绿"的假结论。
 *
 * 因此本文件的红证用「延迟第一条 UPDATE」把交错窗口**确定性地**撑开：
 * 给 A 的第一条 UPDATE 加 50ms 延迟 ⇒ B 完整跑完（校验→撤销→签发）⇒ A 的 UPDATE
 * 此时命中 0 行。
 *   * 旧实现忽略 affected rows ⇒ A 照样签发 ⇒ 3 条会话（**红**）；
 *   * 新实现 affected rows = 0 ⇒ A 抛 `AUTH_TOKEN_REVOKED(401)` ⇒ 2 条会话（**绿**）。
 *
 * 延迟探针只包 `update`（仓储里只有它在签发路径上产生写），不改变任何生产代码。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { freshDb, makeService, seedTenant } from "./auth-harness.mjs";

const PASSWORD = "alice-password-2026";

/** 延迟 A 的第一条 UPDATE 的毫秒数（远大于一次完整 refresh 的耗时）。 */
const TOCTOU_WINDOW_MS = 50;

/**
 * 把 drizzle 查询 builder 包成「执行前先等 `waitMs`」的 thenable。
 *
 * drizzle 的 builder 是惰性执行：`update().set().where().returning()` 只是拼 SQL，
 * **真正执行发生在 `.then()` 被调用时**。所以只需重写 `then`，无需理解 SQL 生成细节。
 *
 * @param {object} builder drizzle 查询 builder。
 * @param {number} waitMs 延迟毫秒数。
 * @returns {object} 同形状的代理（可继续链式调用）。
 */
function delayExecution(builder, waitMs) {
  const wait = new Promise((resolve) => {
    setTimeout(resolve, waitMs);
  });
  const wrap = (target) =>
    new Proxy(target, {
      get(object, property) {
        if (property === "then") {
          const boundThen = object.then.bind(object);
          return (onFulfilled, onRejected) => wait.then(() => boundThen(onFulfilled, onRejected));
        }
        const value = Reflect.get(object, property, object);
        if (typeof value !== "function") return value;
        return (...args) => {
          const result = value.apply(object, args);
          return result !== null && typeof result === "object" ? wrap(result) : result;
        };
      },
    });
  return wrap(builder);
}

/**
 * 只让**第一条** `update` 延迟执行，其余照旧。
 *
 * @param {object} real 真实 drizzle 句柄。
 * @param {number} waitMs 延迟毫秒数。
 * @returns {object} 可直接当 `DrizzleDatabase` 端口用的对象。
 */
function delayFirstUpdate(real, waitMs) {
  const state = { delayed: false };
  return {
    select: (...args) => real.select(...args),
    insert: (...args) => real.insert(...args),
    delete: (...args) => real.delete(...args),
    update: (...args) => {
      const builder = real.update(...args);
      if (state.delayed) return builder;
      state.delayed = true;
      return delayExecution(builder, waitMs);
    },
  };
}

/** 建库 + 种租户 + 注册一个用户（`db` 可替换为探针）。 */
async function setup(wrapDb = (db) => db) {
  const connection = freshDb();
  seedTenant(connection.raw);
  const service = makeService({ db: wrapDb(connection.db) });
  const result = await service.register({
    username: "alice",
    email: "alice@a.example",
    password: PASSWORD,
  });
  return { connection, service, result };
}

/** 统计某表行数。 */
function count(connection, table) {
  const row = connection.raw.prepare(`SELECT COUNT(*) AS total FROM ${table}`).get();
  return Number(row.total);
}

/** 统计某表里 `revoked_at IS NULL` 的行数。 */
function countActive(connection, table) {
  const row = connection.raw
    .prepare(`SELECT COUNT(*) AS total FROM ${table} WHERE revoked_at IS NULL`)
    .get();
  return Number(row.total);
}

// ---------------------------------------------------------------------------
// 红证：确定性撑开 TOCTOU 窗口
// ---------------------------------------------------------------------------

test("FIX-24 · 撑开交错窗口：一次成功 / 一次 AUTH_TOKEN_REVOKED(401)，只多一对令牌（旧实现两次都成功）", async () => {
  const connection = freshDb();
  seedTenant(connection.raw);

  // 装配顺序：真实句柄先跑注册（拿一对有效令牌），然后把**同一个** connection 的 db
  // 换成"第一条 UPDATE 延迟"的探针，重新装配服务。内存库是同一个，数据不丢。
  const bootstrap = makeService({ db: connection.db });
  const result = await bootstrap.register({
    username: "alice",
    email: "alice@a.example",
    password: PASSWORD,
  });
  const refreshToken = result.tokens.refresh_token;

  const service = makeService({ db: delayFirstUpdate(connection.db, TOCTOU_WINDOW_MS) });

  const settled = await Promise.allSettled([
    service.refresh(refreshToken),
    service.refresh(refreshToken),
  ]);

  const fulfilled = settled.filter((item) => item.status === "fulfilled");
  const rejected = settled.filter((item) => item.status === "rejected");

  assert.equal(
    fulfilled.length,
    1,
    "撑开窗口后必须**只有一次**签发成功 —— 旧实现两次都成功（同一 refresh 换来两对令牌）"
  );
  assert.equal(rejected.length, 1, "另一次必须被拒");

  const reason = rejected[0].reason;
  assert.equal(reason.code, "AUTH_TOKEN_REVOKED", "被拒的那次必须是「已撤销」而不是别的码");
  assert.equal(reason.statusCode ?? reason.status, 401, "契约：AUTH_TOKEN_REVOKED ⇒ 401");

  assert.equal(count(connection, "session"), 2, "只允许新建 1 条会话（旧实现 3 条）");
  assert.equal(count(connection, "refresh_token"), 2, "只允许新建 1 条 refresh（旧实现 3 条）");
  assert.equal(countActive(connection, "session"), 1, "有效会话只应剩新会话那 1 条");
  assert.equal(countActive(connection, "refresh_token"), 1, "有效 refresh 只应剩新令牌那 1 条");
  connection.close();
});

// ---------------------------------------------------------------------------
// 自然交错（回归：不能因为修复而把正常并发打坏）
// ---------------------------------------------------------------------------

test("FIX-24 · 自然并发两次：仍必须恰好一次成功、一次 AUTH_TOKEN_REVOKED(401)", async () => {
  const { connection, service, result } = await setup();
  const refreshToken = result.tokens.refresh_token;

  assert.equal(count(connection, "session"), 1, "前置：只注册产生的 1 条会话");

  const settled = await Promise.allSettled([
    service.refresh(refreshToken),
    service.refresh(refreshToken),
  ]);

  const fulfilled = settled.filter((item) => item.status === "fulfilled");
  const rejected = settled.filter((item) => item.status === "rejected");

  assert.equal(fulfilled.length, 1, "并发两次只能有一次签发成功");
  assert.equal(rejected.length, 1);
  assert.equal(rejected[0].reason.code, "AUTH_TOKEN_REVOKED");
  assert.equal(rejected[0].reason.statusCode ?? rejected[0].reason.status, 401);

  assert.equal(count(connection, "session"), 2, "并发轮换只能新建 1 条会话");
  assert.equal(count(connection, "refresh_token"), 2, "并发轮换只能新建 1 条 refresh");
  assert.equal(countActive(connection, "session"), 1);
  assert.equal(countActive(connection, "refresh_token"), 1);
  connection.close();
});

test("FIX-24 · 自然并发三次：成功次数恒为 1（不是「恰好两次」的偶然）", async () => {
  const { connection, service, result } = await setup();

  const settled = await Promise.allSettled([
    service.refresh(result.tokens.refresh_token),
    service.refresh(result.tokens.refresh_token),
    service.refresh(result.tokens.refresh_token),
  ]);

  assert.equal(settled.filter((item) => item.status === "fulfilled").length, 1, "只有一次成功");
  const rejected = settled.filter((item) => item.status === "rejected");
  assert.equal(rejected.length, 2, "另外两次必须都被拒");
  for (const item of rejected) {
    assert.equal(item.reason.code, "AUTH_TOKEN_REVOKED");
    assert.equal(item.reason.statusCode ?? item.reason.status, 401);
  }

  assert.equal(count(connection, "session"), 2, "只允许新建 1 条会话");
  assert.equal(count(connection, "refresh_token"), 2, "只允许新建 1 条 refresh");
  connection.close();
});

// ---------------------------------------------------------------------------
// 旧语义不得被修复改坏
// ---------------------------------------------------------------------------

test("FIX-24 · 串行二次使用仍走原语义：第 2 次 401 AUTH_TOKEN_REVOKED", async () => {
  const { connection, service, result } = await setup();
  const refreshToken = result.tokens.refresh_token;

  const first = await service.refresh(refreshToken);
  assert.ok(first.tokens.access_token, "第 1 次必须成功");

  await assert.rejects(
    () => service.refresh(refreshToken),
    (error) => {
      assert.equal(error.code, "AUTH_TOKEN_REVOKED");
      assert.equal(error.statusCode ?? error.status, 401);
      return true;
    },
    "串行二次使用必须仍为 AUTH_TOKEN_REVOKED(401)"
  );

  connection.close();
});

test("FIX-24 · 链式轮换：新 refresh 仍可用一次（认领逻辑不得误伤新会话）", async () => {
  const { connection, service, result } = await setup();

  const first = await service.refresh(result.tokens.refresh_token);
  const second = await service.refresh(first.tokens.refresh_token);
  assert.ok(second.tokens.refresh_token, "链式轮换必须能连续进行");

  assert.equal(countActive(connection, "session"), 1, "任意时刻只应有 1 条有效会话");
  assert.equal(countActive(connection, "refresh_token"), 1, "任意时刻只应有 1 条有效 refresh");
  connection.close();
});
