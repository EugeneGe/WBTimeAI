/**
 * T2-04 · **J-5 登录限速**（计划 §3.4 / §8）。
 *
 * 判据原文：「连续 5 次错口令 ⇒ 5×401；第 6 次起 423 `AUTH_ACCOUNT_LOCKED`；
 * 成功登录后连续计数归零；`login_attempt` 有新增行」。
 *
 * 四条都做成**查库 + 查响应码**的双重断言：
 *  - 只看响应码证明不了"限速有数据源"（可以是内存计数器，重启即失效）；
 *  - 只看库证明不了"用户真的被挡住"。
 *
 * 另外钉住三条容易退化的语义：
 *  ① **用户不存在时行为一致**（否则 423 变成用户名探测器）；
 *  ② **锁定期间不再落库**（`assert_not_locked` 在写库之前抛 —— 否则攻击者能靠
 *    423 无限刷行，把流水表撑爆）；
 *  ③ `login_attempt` 表**没有**口令 / 口令哈希列。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { freshDb, makeService, seedTenant } from "./auth-harness.mjs";

const PASSWORD = "alice-password-2026";

/** 建库 + 注册一个用户（argon2 真哈希）。 */
async function setup({ maxAttempts } = {}) {
  const connection = freshDb();
  seedTenant(connection.raw);
  const service = makeService({
    db: connection.db,
    ...(maxAttempts === undefined ? {} : { maxAttempts }),
  });
  await service.register({ username: "alice", email: "alice@a.example", password: PASSWORD });
  return { connection, service };
}

/** `login_attempt` 的全部行（新的在前由 SQL 排序保证；这里只看集合）。 */
function attempts(raw, username) {
  return raw
    .prepare("SELECT username, success FROM login_attempt WHERE username = ? ORDER BY created_at, rowid")
    .all(username);
}

/** 从被抛的错误里取 `{code, status, data}`。 */
async function capture(thunk) {
  try {
    await thunk();
  } catch (error) {
    return {
      code: error?.code,
      status: error?.statusCode ?? error?.status,
      data: error?.data ?? {},
      message: error?.message,
    };
  }
  throw new Error("期望被拒，实际调用成功了");
}

test("J-5 · 连续 5 次错口令 ⇒ 5×401，且 login_attempt 落 5 行失败", async () => {
  const { connection, service } = await setup();

  for (let index = 1; index <= 5; index += 1) {
    const result = await capture(() => service.login({ username: "alice", password: `wrong-${index}` }));
    assert.equal(result.code, "AUTH_INVALID_CREDENTIALS", `第 ${index} 次必须是凭据无效`);
    assert.equal(result.status, 401, `第 ${index} 次必须是 401（不是 423）`);
  }

  const rows = attempts(connection.raw, "alice");
  assert.equal(rows.length, 5, "校验失败也必须落库 —— 限速的唯一数据来源");
  assert.equal(rows.every((row) => row.success === 0), true, "5 行都必须是失败");
  connection.close();
});

test("J-5 · 第 6 次起 423 AUTH_ACCOUNT_LOCKED（**即使口令正确**），且 data 只带 username + lock_seconds", async () => {
  const { connection, service } = await setup();

  for (let index = 1; index <= 5; index += 1) {
    await capture(() => service.login({ username: "alice", password: `wrong-${index}` }));
  }

  const locked = await capture(() => service.login({ username: "alice", password: PASSWORD }));
  assert.equal(locked.code, "AUTH_ACCOUNT_LOCKED");
  assert.equal(locked.status, 423, "契约：AUTH_ACCOUNT_LOCKED → 423");
  assert.deepEqual(locked.data, { username: "alice", lock_seconds: 900 }, "data 只带契约规定的两键");

  // 锁定期间**不再落库**（否则 423 可被用来无限刷行）
  assert.equal(attempts(connection.raw, "alice").length, 5, "被锁的尝试不得写库");

  // 连打仍是 423（锁定窗口未过）
  const again = await capture(() => service.login({ username: "alice", password: PASSWORD }));
  assert.equal(again.status, 423);
  connection.close();
});

test("J-5 · 用户不存在时同样 5×401 → 423（不泄露用户名是否存在）", async () => {
  const { connection, service } = await setup();

  for (let index = 1; index <= 5; index += 1) {
    const result = await capture(() => service.login({ username: "ghost", password: `wrong-${index}` }));
    assert.equal(result.code, "AUTH_INVALID_CREDENTIALS", "不存在的用户也走同一码");
    assert.equal(result.status, 401);
  }
  const locked = await capture(() => service.login({ username: "ghost", password: "whatever" }));
  assert.equal(locked.code, "AUTH_ACCOUNT_LOCKED");
  assert.equal(locked.status, 423, "不存在的用户也会被锁 —— 否则 423 就是用户名探测器");

  assert.equal(attempts(connection.raw, "ghost").length, 5, "不存在的用户名同样落库");
  connection.close();
});

test("J-5 · 成功登录打断连续计数（4 失败 → 成功 → 4 失败仍不锁）", async () => {
  const { connection, service } = await setup();

  for (let index = 1; index <= 4; index += 1) {
    await capture(() => service.login({ username: "alice", password: `wrong-a${index}` }));
  }
  const ok = await service.login({ username: "alice", password: PASSWORD });
  assert.ok(ok.tokens.access_token, "第 5 次用对口令必须成功（此时连续失败只有 4 < 5）");

  for (let index = 1; index <= 4; index += 1) {
    const result = await capture(() => service.login({ username: "alice", password: `wrong-b${index}` }));
    assert.equal(result.status, 401, "成功之后重新计数：第 4 次仍应是 401");
  }

  // 此时累计失败 8 次，但"连续"只有 4 次 —— 若成功没有打断计数，这里早该 423 了。
  const fifth = await capture(() => service.login({ username: "alice", password: "wrong-b5" }));
  assert.equal(fifth.status, 401, "第 5 次连续失败仍返回 401（本次失败先落库再判）");
  const sixth = await capture(() => service.login({ username: "alice", password: PASSWORD }));
  assert.equal(sixth.status, 423, "达到 5 次连续失败后，下一次（含正确口令）必须 423");

  const rows = attempts(connection.raw, "alice");
  assert.equal(rows.length, 10, "9 次失败 + 1 次成功 = 10 行");
  assert.equal(rows.filter((row) => row.success === 1).length, 1, "成功行恰好 1 条（它打断计数）");
  assert.equal(rows.filter((row) => row.success === 0).length, 9);
  connection.close();
});

test("§3.4 · login_attempt 不含口令、不含口令哈希（列清单断言）", async () => {
  const { connection, service } = await setup();
  await capture(() => service.login({ username: "alice", password: "wrong" }));

  const columns = connection.raw
    .prepare("PRAGMA table_info(login_attempt)")
    .all()
    .map((row) => row.name);

  assert.deepEqual(
    [...columns].sort(),
    ["created_at", "id", "ip_address", "success", "tenant_id", "updated_at", "username"],
    "login_attempt 的列就是这 7 个 —— 任何口令相关列出现即违约"
  );
  for (const forbidden of ["password", "password_hash", "token", "credential"]) {
    assert.equal(
      columns.some((name) => name.includes(forbidden)),
      false,
      `login_attempt 不得有 ${forbidden} 相关列`
    );
  }

  // 库里也不得出现口令明文（把整表序列化后搜一遍）
  const dump = JSON.stringify(connection.raw.prepare("SELECT * FROM login_attempt").all());
  assert.equal(dump.includes("wrong"), false, "库里不得出现口令明文");
  connection.close();
});

/**
 * 解析 SQLite 毫秒精度 UTC 时间文本（`login-attempt-sink.ts` 的
 * `toSortableTimestamp` 形状 `YYYY-MM-DD HH:MM:SS.sss`）⇒ UTC 毫秒。
 *
 * 与生产侧 `parseDbInstant`（`apps/api/src/modules/auth/refresh.ts`）同一语义：
 * **必须**按 UTC 分量手工拼 —— `Date.parse` 会把无时区的串按本地时区解释，
 * 在 UTC+8 上会偏 8 小时，边界断言就全错。
 */
function parseSqliteStampMs(text) {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/.exec(
    String(text).trim(),
  );
  assert.ok(match !== null, `无法解析的 SQLite 时间戳：${JSON.stringify(text)}`);
  return Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6]),
    match[7] === undefined ? 0 : Number(match[7].padEnd(3, "0")),
  );
}

/** 最近一次失败的 `created_at`（UTC 毫秒）—— 假时钟边界的**锚点**。 */
function lastFailureAtMs(raw, username) {
  const row = raw
    .prepare(
      "SELECT created_at FROM login_attempt WHERE username = ? AND success = 0 " +
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
    )
    .get(username);
  assert.ok(row !== undefined, "必须已有失败行（前置：连续失败已落库）");
  return parseSqliteStampMs(row.created_at);
}

test("§3.4 · 锁定窗口按「最近一次失败」起算，900s 精确边界：899s 锁可用 / 901s 锁失效（#19 假时钟）", async () => {
  const connection = freshDb();
  seedTenant(connection.raw);
  // 假时钟：可变绑定注入（`AuthService` → `LoginGuard` 一路透传）。`created_at`
  // 由 `LoginAttemptSink` 用它自己的授时落库（T2-03 实现，不得改 db），所以锚点
  // 从**库里读回**最近一次失败的真实时刻，再把假时钟拨到 锚点 + 899s / + 901s
  // —— 判据（login-guard.ts）是 `now − created_at <= 900s`，毫秒精度全保留，
  // 两个边界点都是确定值，不再依赖「跑得多快」。
  let now = new Date();
  const service = makeService({ db: connection.db, now: () => now });
  await service.register({ username: "alice", email: "alice@a.example", password: PASSWORD });

  for (let index = 1; index <= 5; index += 1) {
    await capture(() => service.login({ username: "alice", password: `wrong-${index}` }));
  }
  assert.equal(
    (await capture(() => service.login({ username: "alice", password: PASSWORD }))).status,
    423,
    "5 次连续失败后立刻应锁定"
  );

  const anchorMs = lastFailureAtMs(connection.raw, "alice");
  // 899s：仍在 900s 窗口内 ⇒ 锁**可用**（正确口令也 423；该尝试不落库）。
  now = new Date(anchorMs + 899_000);
  const at899 = await capture(() => service.login({ username: "alice", password: PASSWORD }));
  assert.equal(at899.status, 423, "距最近一次失败 899s：仍在锁定窗口内（锁可用）");

  // 901s：窗口外 ⇒ 锁**失效**（自动解锁，锁定不是永久的）。
  now = new Date(anchorMs + 901_000);
  const at901 = await service.login({ username: "alice", password: PASSWORD });
  assert.ok(at901.tokens.access_token, "距最近一次失败 901s：锁定已解除（窗口外不锁）");
  connection.close();
});
