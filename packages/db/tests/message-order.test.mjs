/**
 * T3-07 · `MessageRepo` 的**双键次序**证明（`created_at asc, id asc`）。
 *
 * 为什么单独立文件而不是塞进 `child-scope.test.mjs`：那个文件证的是 **R3-22 隔离**
 * （父引用强制），本文件证的是**排序确定性** —— 两件事的注入反例不同（前者拆父谓词，
 * 后者拆第二排序键），混在一起会让"哪一条红了"说不清。
 *
 * 背景（T3-07 施工记录 §3 口径③）：`message.created_at` 是
 * `DEFAULT CURRENT_TIMESTAMP`（**秒粒度**）⇒ 同一秒写入的消息完全并列。只按
 * `created_at` 排序时，同秒记录的先后**不由数据决定**（SQLite 吐 rowid 序、PG 吐堆序），
 * 后果是分页 / `LIMIT` 截断时**静默丢行或重行**。补 `id`（主键、全序、不随时间变化）
 * 作第二键后，取哪几条与怎么排都成为数据的函数。
 *
 * py oracle 逐字对齐：`list_by_conversation` / `list_by_run` 都是
 * `order_by(created_at.asc(), id.asc())`（`message_repository.py:79` / `:90`）。
 *
 * 判据（本文件 5 条，名字即判据，注入任一拆掉第二键 ⇒ 第 1/2/4 条必红）：
 *   1. `list`：**乱序插入**的 6 条同秒消息 ⇒ 返回次序 = `(created_at, id)` 全序；
 *   2. `listByRun`：同一 run 的 3 条同秒消息 ⇒ 同上（幂等查询用的就是这条路径）；
 *   3. `LIMIT` 截断的**集合**确定性：`limit < 同秒行数` ⇒ 取到的必须是该序的**前 N 条**，
 *      两次调用逐字一致（这条是"服务层重排救不了截断"的直接证据）；
 *   4. 跨**秒**混排：早一秒的行必须整体排在前面（第二键不得覆盖主键语义）；
 *   5. **非法 `orderBy` ⇒ `ScopeError`**（不静默降级成 `created_at` —— 仓纪「非法值直接拒绝」）。
 *
 * 复跑：`cd packages/db && npx tsc -b && node --experimental-sqlite --test tests/message-order.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { MessageRepo, Scope, ScopeError } from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A } from "./fixtures/runtime-fixture.mjs";

/** 6 个**故意乱序**的 id（字典序 = c1 < c2 < c3 < c5 < c7 < c9）。 */
const SCRAMBLED = [
  "cccc0000-0000-4000-8000-0000000000c9",
  "cccc0000-0000-4000-8000-0000000000c3",
  "cccc0000-0000-4000-8000-0000000000c7",
  "cccc0000-0000-4000-8000-0000000000c1",
  "cccc0000-0000-4000-8000-0000000000c5",
  "cccc0000-0000-4000-8000-0000000000c2",
];

/** 建库 + 父链 + A 的 scope 与会话仓储。 */
function seed() {
  const connection = freshConnection();
  seedParents(connection);
  const scopeA = new Scope(T_A);
  const messages = new MessageRepo(connection.db, scopeA, scopeA.ref(IDS.convA), DIALECT);
  return { connection, raw: connection.raw, scopeA, messages };
}

/**
 * 直插一条消息（`created_at` 由测试显式给 —— 秒粒度并列只能靠这个拉平）。
 *
 * 走 raw 而不是 `repo.append`：本文件要被测的是**读路径排序**，写路径已在
 * `child-scope.test.mjs` 覆盖；用 raw 还能自由指定秒值（`append` 不给 `created_at`）。
 */
function insertMessage(raw, { id, createdAt, role = "user", content = "hi", runId = null }) {
  raw
    .prepare(
      "insert into message (id, conversation_id, run_id, role, content, content_parts, token_count, created_at) " +
        "values (?, ?, ?, ?, ?, null, null, ?)",
    )
    .run(id, IDS.convA, runId, role, content, createdAt);
}

test("① list：同秒 6 条**乱序插入** ⇒ 次序 = (created_at asc, id asc)", async () => {
  const { connection, raw, messages } = seed();
  try {
    for (const id of SCRAMBLED) insertMessage(raw, { id, createdAt: "2026-10-22 00:00:05" });

    const listed = await messages.list();
    assert.equal(listed.length, SCRAMBLED.length, "条数必须一致（对照：真的插进去了）");
    assert.deepEqual(
      listed.map((row) => row.id),
      [...SCRAMBLED].sort(),
      "同秒并列时次序必须 = id 升序（拆掉第二键 ⇒ rowid 序 ⇒ 本断言红）",
    );
  } finally {
    connection.close();
  }
});

test("② listByRun：同一 run 的同秒消息同样 (created_at, id) 全序（幂等查询走的这条路径）", async () => {
  const { connection, raw, messages } = seed();
  try {
    const inRun = SCRAMBLED.slice(0, 3);
    for (const id of inRun) {
      insertMessage(raw, { id, createdAt: "2026-10-22 00:00:07", role: "assistant", runId: IDS.runA });
    }
    // 干扰项：同会话、同秒、**别的 run** —— 不得混进来
    insertMessage(raw, {
      id: "cccc0000-0000-4000-8000-0000000000ff",
      createdAt: "2026-10-22 00:00:07",
      role: "assistant",
      runId: IDS.runA2,
    });

    const listed = await messages.listByRun(new Scope(T_A).ref(IDS.runA));
    assert.deepEqual(
      listed.map((row) => row.id),
      [...inRun].sort(),
      "本 run 的 3 条按 id 升序；别的 run 同秒行不得混入",
    );
  } finally {
    connection.close();
  }
});

test("③ LIMIT 截断的**集合**确定：limit=3 ⇒ 该序前 3 条，两次调用逐字一致", async () => {
  const { connection, raw, messages } = seed();
  try {
    for (const id of SCRAMBLED) insertMessage(raw, { id, createdAt: "2026-10-22 00:00:09" });

    const first = await messages.list({ limit: 3 });
    const second = await messages.list({ limit: 3 });
    const expected = [...SCRAMBLED].sort().slice(0, 3);
    assert.deepEqual(first.map((row) => row.id), expected, "截断取到的必须是该序的前 3 条");
    assert.deepEqual(
      second.map((row) => row.id),
      first.map((row) => row.id),
      "两次调用必须一致（单键排序下这一格不稳定 ⇒ 分页丢行/重行）",
    );
  } finally {
    connection.close();
  }
});

test("④ 跨秒混排：早一秒的行整体在前（第二键不得覆盖主键语义）", async () => {
  const { connection, raw, messages } = seed();
  try {
    // 更早一秒的两条（id 字典序落在后面 —— 若实现把 id 当主键就会排错）
    const earlier = ["ffff0000-0000-4000-8000-000000000002", "ffff0000-0000-4000-8000-000000000001"];
    for (const id of earlier) insertMessage(raw, { id, createdAt: "2026-10-22 00:00:01" });
    for (const id of SCRAMBLED) insertMessage(raw, { id, createdAt: "2026-10-22 00:00:02" });

    const listed = await messages.list();
    assert.deepEqual(
      listed.map((row) => row.id),
      [...earlier].sort().concat([...SCRAMBLED].sort()),
      "次序 = created_at 主键 + id 兜底（时间优先，id 只在同秒内生效）",
    );
  } finally {
    connection.close();
  }
});

test("⑤ 非法 orderBy ⇒ ScopeError（不静默降级成 created_at）", async () => {
  const { connection, raw, messages } = seed();
  try {
    insertMessage(raw, { id: SCRAMBLED[0], createdAt: "2026-10-22 00:00:03" });

    // `message` 没有 updated_at 列 ⇒ 显式传它必须**当场拒**。
    // 反例形态：若实现写成 `columns[orderBy] ?? columns.created_at`，这里会静默按
    // created_at 排出一行"看起来正常"的结果 —— 调用方的编程错误就被吞掉了。
    for (const bogus of ["updated_at", "no_such_column"]) {
      await assert.rejects(
        () => messages.list({ orderBy: bogus }),
        (error) => {
          assert.ok(error instanceof ScopeError, `必须 ScopeError，实测 ${String(error)}`);
          assert.match(error.message, /orderBy 非法/);
          return true;
        },
        `orderBy=${bogus} 必须抛错`,
      );
    }

    // 对照：合法列仍然可用（否则"抛错"可能只是整条路坏了）
    assert.equal((await messages.list({ orderBy: "created_at" })).length, 1);
    assert.equal((await messages.list({ orderBy: "id" })).length, 1);
  } finally {
    connection.close();
  }
});
