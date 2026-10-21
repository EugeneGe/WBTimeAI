/**
 * FIX-06 / FIX-06b · `logout-all` 的语句规模与**数据口径**（20xx 审计 #8）。
 *
 * 缺陷原文
 * --------
 * 旧实现：`sessions.listByUser(limit: 500)` → 逐条 `revokeBySession` → `revokeAllByUser`。
 * 三个问题叠在一起：
 * * 语句数 = 会话数 + 1（N+1）；
 * * 会话集合被 500 截断 ⇒ 第 501 条之后的 refresh 不会被撤，而会话侧是**单条** UPDATE
 *   撤全部 ⇒ 「session 已撤销、refresh 仍可轮换」的口径裂缝；
 * * **`session_id IS NULL` 的 refresh 行不在任何会话集合里** ⇒ 永远不被命中。而
 *   `authenticateRefresh` 在 `session_id === null` 时跳过会话校验 ⇒ 这类行在
 *   logout-all 之后仍能换出新令牌（FIX-06b 的根因）。
 *
 * 现行实现（FIX-06b）：两条按 `user_id` 的 UPDATE —— `RefreshTokenRepo.revokeByUser`
 * （`tenant_id + user_id + revoked_at IS NULL`）→ `SessionRepo.revokeAllByUser`。
 * **与会话数量、会话是否存在、`session_id` 是否为空全部无关。**
 *
 * 本文件的判据
 * -----------
 * ① ≥50 会话 logout-all 后**全部** session `revoked_at` 非空；
 * ② **全部** refresh `revoked_at` 非空（含第 500 条之后、含 `session_id IS NULL` 的脏数据）；
 * ③ 语句数**精确**为 `UPDATE = 2 / SELECT = 0`（不是"≤2"的模糊断言）；
 * ④ 幂等：二次调用不改写 `revoked_at` 时间戳（用可推进的时钟证）；
 * ⑤ 租户隔离：另一租户里同 `user_id` 的行不得被连带撤销（scope 生效）。
 *
 * 计数探针
 * --------
 * `DrizzleDatabase` 端口只有 `select/insert/update/delete` 四个方法（见 scoped-repo.ts），
 * 把真句柄包成「四方法各自计数」的薄壳即可精确统计语句数 —— 仓储里的每一次 `update()`
 * 都被记一次，没有漏数分支。
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";

import { RefreshTokenRepo, Scope } from "@wbtime/db";

import { freshDb, makeService, seedTenant, TENANT_ID } from "./auth-harness.mjs";
import { hashRefreshToken } from "../dist/modules/auth/refresh.js";

/** 第二个租户（用于 scope 隔离用例）。 */
const OTHER_TENANT_ID = "22222222-2222-4222-8222-222222222222";

/**
 * 固定时钟：**锚在本次运行的秒级时刻**，而不是硬编码的日历时刻。
 *
 * 为什么必须这样（2026-10-21 实测缺陷）：访问令牌的 `exp` 由**注入时钟**决定
 * （`FIXED_NOW + 900s`），但 `jose.jwtVerify` 校验 `exp` 用的是**真实时钟**。
 * 原先硬编码 `2026-10-21T12:00:00Z` ⇒ 令牌 `exp = 12:15Z`，任何在 UTC 12:15 之后
 * 跑这条用例的时段都会拿到 `AUTH_TOKEN_EXPIRED`（本日 23:2x 全量跑时 5 条红，13:xx 跑时全绿）。
 * 锚在运行时刻后，`exp` 恒晚于真实时间 15 分钟，断言的**确定性**不受影响（同一文件内
 * 所有时间列都由这一个 `FIXED_NOW` 派生）。
 */
const FIXED_NOW = new Date(Math.floor(Date.now() / 1000) * 1000);

/** `YYYY-MM-DD HH:MM:SS`（UTC）——SQLite 档的时间列文本格式。 */
const toStamp = (d) =>
  `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")} ` +
  `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}:${String(d.getUTCSeconds()).padStart(2, "0")}`;

/** 时间列字面量（SQLite 档是 `YYYY-MM-DD HH:MM:SS` 文本，UTC）。 */
const STAMP = toStamp(FIXED_NOW);

/** 会话/令牌的过期时刻（固定时钟 + 30 天，保证"有效"）。 */
const EXPIRES_AT = toStamp(new Date(FIXED_NOW.getTime() + 30 * 24 * 3600 * 1000));

/** 一次性口令（满足域层策略即可）。 */
const PASSWORD = "alice-password-2026";

/**
 * 把 drizzle 句柄包成计数薄壳。
 *
 * @param {object} real 真句柄（`createSqliteDb().db`）。
 * @returns {{db: object, counts: {select: number, insert: number, update: number, delete: number}}}
 */
function countingDb(real) {
  const counts = { select: 0, insert: 0, update: 0, delete: 0 };
  const wrap = (name) => (...args) => {
    counts[name] += 1;
    return real[name](...args);
  };
  const db = {
    select: wrap("select"),
    insert: wrap("insert"),
    update: wrap("update"),
    delete: wrap("delete"),
  };
  return { db, counts };
}

/** 第 i 条会话 id（UUID 形状，稳定可复现）。 */
function sessionId(index) {
  return `aaaaaaaa-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

/** 第 i 条 refresh id。 */
function refreshId(index) {
  return `bbbbbbbb-0000-4000-8000-${String(index).padStart(12, "0")}`;
}

/** 直插一条 session 行。 */
function insertSession(raw, { id, userId, tenantId = TENANT_ID, index = 0 }) {
  raw
    .prepare(
      "INSERT INTO session (id, tenant_id, user_id, device, ip_address, user_agent, expires_at, revoked_at, created_at, updated_at) " +
        "VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?)"
    )
    .run(id, tenantId, userId, `设备 ${index}`, EXPIRES_AT, STAMP, STAMP);
}

/**
 * 直插一条 refresh 行（`sessionId` 可传 `null` —— 用来复现 FIX-06b 的脏数据场景）。
 *
 * @param {object} raw `node:sqlite` 原生句柄。
 * @param {{id: string, userId: string, sessionId?: string|null, tenantId?: string, tokenIndex?: number}} row
 */
function insertRefresh(raw, row) {
  const sessionIdValue = row.sessionId === undefined ? null : row.sessionId;
  const tokenIndex = row.tokenIndex ?? 0;
  raw
    .prepare(
      "INSERT INTO refresh_token (id, tenant_id, user_id, session_id, token_hash, expires_at, revoked_at, created_at, updated_at) " +
        "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)"
    )
    .run(
      row.id,
      row.tenantId ?? TENANT_ID,
      row.userId,
      sessionIdValue,
      hashRefreshToken(`refresh-plaintext-${tokenIndex}`),
      EXPIRES_AT,
      STAMP,
      STAMP
    );
}

/**
 * 直插 `count` 条「会话 + 其 refresh」，归属同一用户。
 *
 * 为什么直插而不调 `login()`：50～601 次 argon2 会把测试从毫秒级拖到分钟级，而本用例
 * 要证的是**撤销路径的语句数与覆盖面**，与会话是"怎么建出来的"无关。
 */
function seedSessions(raw, userId, count, offset = 0) {
  for (let index = offset; index < offset + count; index += 1) {
    insertSession(raw, { id: sessionId(index), userId, index });
    insertRefresh(raw, {
      id: refreshId(index),
      userId,
      sessionId: sessionId(index),
      tokenIndex: index,
    });
  }
}

/** 统计某表里 `revoked_at IS NULL` 的行数（表名是本文件内的字面量，非外部输入）。 */
function countActive(raw, table, tenantId = null) {
  const sql =
    tenantId === null
      ? `SELECT COUNT(*) AS total FROM ${table} WHERE revoked_at IS NULL`
      : `SELECT COUNT(*) AS total FROM ${table} WHERE revoked_at IS NULL AND tenant_id = ?`;
  const row = tenantId === null ? raw.prepare(sql).get() : raw.prepare(sql).get(tenantId);
  return Number(row.total);
}

/** 统计某表总行数。 */
function countAll(raw, table) {
  const row = raw.prepare(`SELECT COUNT(*) AS total FROM ${table}`).get();
  return Number(row.total);
}

/** 建库 + 种租户 + 装配服务（db 走计数薄壳）。 */
async function setup(options = {}) {
  const connection = freshDb();
  seedTenant(connection.raw);
  const probe = countingDb(connection.db);
  const clock = { now: options.now ?? FIXED_NOW };
  const service = makeService({ db: probe.db, now: () => clock.now });
  const result = await service.register({
    username: "alice",
    email: "alice@a.example",
    password: PASSWORD,
  });
  return { connection, probe, clock, service, result };
}

// ---------------------------------------------------------------------------
// ① ② ③ 50 会话（任务书下限）
// ---------------------------------------------------------------------------

test("FIX-06 ①②③ · 50 会话 logout-all：会话与 refresh 全撤，UPDATE 精确 2 条 / SELECT 0 条", async (t) => {
  const { connection, probe, service, result } = await setup();
  seedSessions(connection.raw, result.user.id, 49); // register 已给 1 条 ⇒ 共 50 条

  assert.equal(countAll(connection.raw, "session"), 50, "前置：50 条会话");
  assert.equal(countActive(connection.raw, "session"), 50, "前置：50 条有效会话");
  assert.equal(countAll(connection.raw, "refresh_token"), 50, "前置：50 条 refresh");
  assert.equal(countActive(connection.raw, "refresh_token"), 50, "前置：50 条有效 refresh");

  // 只统计 logout-all 自身的语句（register 已消耗若干条）
  probe.counts.update = 0;
  probe.counts.select = 0;

  await service.logoutAll(result.tokens.access_token);

  t.diagnostic(
    `50 会话 logout-all：UPDATE=${probe.counts.update}，SELECT=${probe.counts.select}`
  );

  assert.equal(countActive(connection.raw, "session"), 0, "① 全部会话必须已撤销");
  assert.equal(countActive(connection.raw, "refresh_token"), 0, "② 全部 refresh 必须已撤销");
  assert.equal(probe.counts.update, 2, "③ 必须恰好 2 条 UPDATE（revokeByUser + revokeAllByUser）");
  assert.equal(probe.counts.select, 0, "③ 必须 0 条 SELECT —— 不再先取会话列表");
  connection.close();
});

// ---------------------------------------------------------------------------
// ② 超 500（旧实现的截断边界）
// ---------------------------------------------------------------------------

test("FIX-06 ② · 601 会话（>500）logout-all：0 条残留，UPDATE=2 / SELECT=0", async (t) => {
  const { connection, probe, service, result } = await setup();
  seedSessions(connection.raw, result.user.id, 600); // +1 = 601

  assert.equal(countAll(connection.raw, "session"), 601);
  assert.equal(countActive(connection.raw, "refresh_token"), 601);

  probe.counts.update = 0;
  probe.counts.select = 0;

  const returned = await service.logoutAll(result.tokens.access_token);
  assert.equal(returned, undefined, "契约不回撤销数量（MessageResponse 只有 message）");

  t.diagnostic(
    `601 会话 logout-all：UPDATE=${probe.counts.update}，SELECT=${probe.counts.select}`
  );

  assert.equal(countActive(connection.raw, "session"), 0, "① 601 条会话必须全部已撤销");
  assert.equal(
    countActive(connection.raw, "refresh_token"),
    0,
    "② 601 条 refresh 必须全部已撤销 —— 不得被 `listByUser(limit:500)` 截断"
  );
  assert.equal(probe.counts.update, 2, "③ 语句数与会话数无关：仍是 2 条 UPDATE");
  assert.equal(probe.counts.select, 0, "③ 0 条 SELECT");
  connection.close();
});

// ---------------------------------------------------------------------------
// ④ 幂等
// ---------------------------------------------------------------------------

test("FIX-06 ④ · 幂等：二次 logout-all 不改写 revoked_at 时间戳（推进时钟后仍保持首撤时刻）", async (t) => {
  const { connection, probe, clock, service, result } = await setup();
  seedSessions(connection.raw, result.user.id, 49);

  await service.logoutAll(result.tokens.access_token);

  const readStamps = () =>
    connection.raw
      .prepare("SELECT id, revoked_at FROM session ORDER BY id")
      .all()
      .map((row) => `${row.id}=${row.revoked_at}`)
      .join("|");

  const firstPass = readStamps();
  assert.ok(firstPass.includes(STAMP), `首次撤销必须落在注入时钟上（期望 ${STAMP}）`);

  // 时钟推进 10 分钟：若二次调用真的改写了行，时间戳就会变
  clock.now = new Date(FIXED_NOW.getTime() + 10 * 60 * 1000);
  probe.counts.update = 0;

  const secondReturn = await service.logoutAll(result.tokens.access_token);
  assert.equal(secondReturn, undefined, "幂等调用同样不回数量");

  t.diagnostic(`二次 logout-all：UPDATE=${probe.counts.update}（2 条 0 行命中的 UPDATE）`);

  assert.equal(readStamps(), firstPass, "④ 二次撤销不得改写任何 revoked_at 时间戳");
  assert.equal(probe.counts.update, 2, "④ 幂等路径同样恒为 2 条 UPDATE");
  connection.close();
});

// ---------------------------------------------------------------------------
// FIX-06b ①：`session_id IS NULL` 的脏数据
// ---------------------------------------------------------------------------

test("FIX-06b ① · `session_id IS NULL` 的 refresh（脏数据）也必须被 logout-all 撤掉", async (t) => {
  const { connection, probe, service, result } = await setup();

  // 造一条"没有会话"的 refresh：它不在任何会话集合里，旧实现永远碰不到它；
  // 而 authenticateRefresh 对 session_id === null 跳过会话校验 ⇒ 它会一直是活口。
  const orphanId = refreshId(900);
  insertRefresh(connection.raw, {
    id: orphanId,
    userId: result.user.id,
    sessionId: null,
    tokenIndex: 900,
  });

  const readOrphan = () =>
    connection.raw.prepare("SELECT session_id, revoked_at FROM refresh_token WHERE id = ?").get(orphanId);

  assert.equal(readOrphan().session_id, null, "前置：该行确实没有 session_id");
  assert.equal(readOrphan().revoked_at, null, "前置：该行此刻有效");

  probe.counts.update = 0;
  probe.counts.select = 0;

  await service.logoutAll(result.tokens.access_token);

  t.diagnostic(
    `含 1 条 session_id IS NULL：UPDATE=${probe.counts.update}，SELECT=${probe.counts.select}`
  );

  assert.notEqual(
    readOrphan().revoked_at,
    null,
    "FIX-06b 根因：session_id 为 NULL 的 refresh 必须在 logout-all 后失效（否则仍可轮换）"
  );
  assert.equal(countActive(connection.raw, "refresh_token"), 0, "该用户所有 refresh 都必须失效");
  assert.equal(countActive(connection.raw, "session"), 0, "会话同样全部失效");
  assert.equal(probe.counts.update, 2, "语句数仍恒为 2");
  assert.equal(probe.counts.select, 0);
  connection.close();
});

// ---------------------------------------------------------------------------
// FIX-06b ②：租户隔离
// ---------------------------------------------------------------------------

test("FIX-06b ② · 另一租户里同 user_id 的 refresh/session 不得被连带撤销（scope 生效）", async (t) => {
  const { connection, probe, service, result } = await setup();
  seedTenant(connection.raw, { id: OTHER_TENANT_ID, slug: "tenant-b" });

  // 另一租户里同 user_id 的一会话一 refresh（合成"跨租户同 id"场景）。
  // 注：测试库未开 `PRAGMA foreign_keys`，故该行可直插；生产侧有 FK，这种行不可能存在 ——
  // 本用例是**纵深防御**：即便数据面出现这种行，撤销也必须止步于本租户。
  const otherSessionId = sessionId(700);
  insertSession(connection.raw, {
    id: otherSessionId,
    userId: result.user.id,
    tenantId: OTHER_TENANT_ID,
    index: 700,
  });
  insertRefresh(connection.raw, {
    id: refreshId(700),
    userId: result.user.id,
    sessionId: otherSessionId,
    tenantId: OTHER_TENANT_ID,
    tokenIndex: 700,
  });

  assert.equal(countActive(connection.raw, "session", OTHER_TENANT_ID), 1, "前置：另一租户 1 条有效会话");
  assert.equal(countActive(connection.raw, "refresh_token", OTHER_TENANT_ID), 1, "前置：另一租户 1 条有效 refresh");

  probe.counts.update = 0;
  probe.counts.select = 0;

  await service.logoutAll(result.tokens.access_token);

  t.diagnostic(
    `跨租户 logout-all：UPDATE=${probe.counts.update}，SELECT=${probe.counts.select}`
  );

  assert.equal(countActive(connection.raw, "session", TENANT_ID), 0, "本租户会话必须全撤");
  assert.equal(countActive(connection.raw, "refresh_token", TENANT_ID), 0, "本租户 refresh 必须全撤");
  assert.equal(
    countActive(connection.raw, "session", OTHER_TENANT_ID),
    1,
    "⑤ 另一租户的会话**不得**被撤销（scope 谓词生效）"
  );
  assert.equal(
    countActive(connection.raw, "refresh_token", OTHER_TENANT_ID),
    1,
    "⑤ 另一租户里同 user_id 的 refresh **不得**被撤销 —— 撤销按 tenant_id 收敛"
  );
  assert.equal(probe.counts.update, 2, "语句数仍恒为 2（不因跨租户行而变多）");
  connection.close();
});

// ---------------------------------------------------------------------------
// revokeByUser 的单条 UPDATE 覆盖面
// ---------------------------------------------------------------------------

test("FIX-06b · revokeByUser 单条 UPDATE 覆盖 950 条 refresh（不再按会话分块）", async (t) => {
  const { connection, result } = await setup();
  seedSessions(connection.raw, result.user.id, 950); // +1 = 951 条会话 / 951 条 refresh

  const probe = countingDb(connection.db);
  const scope = new Scope(TENANT_ID);
  const repo = new RefreshTokenRepo(probe.db, scope, "sqlite");

  probe.counts.update = 0;
  const revoked = await repo.revokeByUser(scope.ref(result.user.id), FIXED_NOW);

  t.diagnostic(`revokeByUser(951 行)：UPDATE=${probe.counts.update}，撤销行数=${revoked}`);

  assert.equal(revoked, 951, "该用户的 951 条 refresh 必须一条不漏地被撤销");
  assert.equal(
    probe.counts.update,
    1,
    "必须**恰好 1 条** UPDATE —— 没有 IN 列表、没有分块、与会话数无关（SQLite 变量上限也不再相关）"
  );
  assert.equal(countActive(connection.raw, "refresh_token"), 0);
  connection.close();
});

test("FIX-06b · 用户没有任何 refresh ⇒ revokeByUser 返回 0 且仍只发 1 条 UPDATE（无特判分支）", async () => {
  const { connection } = await setup();
  const probe = countingDb(connection.db);
  const scope = new Scope(TENANT_ID);
  const repo = new RefreshTokenRepo(probe.db, scope, "sqlite");

  probe.counts.update = 0;
  const revoked = await repo.revokeByUser(scope.ref(randomUUID()), FIXED_NOW);

  assert.equal(revoked, 0, "没有任何行可撤时返回 0（不抛错）");
  assert.equal(probe.counts.update, 1, "仍只发 1 条 UPDATE —— 不为空结果加特判分支");
  connection.close();
});
