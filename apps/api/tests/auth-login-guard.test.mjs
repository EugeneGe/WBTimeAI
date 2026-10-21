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

test("§3.4 · 锁定窗口按「最近一次失败」起算：窗口外不锁", async () => {
  const connection = freshDb();
  seedTenant(connection.raw);
  // 时钟锚在**真实当前时刻**：`LoginAttemptSink` 的 `created_at` 用它自己的授时
  // （T2-03 的实现，本任务不得改 db），所以固定成"未来/过去"的时钟会让
  // `now - created_at` 变成负值或巨大值，测出来的就不是窗口语义了。
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

  // 把时钟推到窗口外（lock_seconds=900 ⇒ 拨 +1800s），锁定必须自动解除。
  // 余量必须覆盖 5 次失败登录的真实耗时 E —— 全量并行跑时 CPU 争用可使 E > 1s；
  // 判锁条件（login-guard.ts）展开为 `1800 − E > 900`，E 无论多慢（远小于 900s）
  // 都不影响判定。（曾用 +901s：E ≥ 1s 即假红，全量跑偶发 AUTH_ACCOUNT_LOCKED。）
  now = new Date(now.getTime() + 1_800_000);
  const afterWindow = await service.login({ username: "alice", password: PASSWORD });
  assert.ok(afterWindow.tokens.access_token, "窗口外应允许登录（锁定不是永久的）");
  connection.close();
});
