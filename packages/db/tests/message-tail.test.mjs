/**
 * AUD-01 · `MessageRepo.listTail`（**尾部窗口**）的行为证明。
 *
 * 为什么单独立文件：`message-order.test.mjs` 证的是「升序取数的**确定性**」，
 * 本文件证的是「取数**方向**」—— 两者是不同的注入反例（前者拆第二排序键，
 * 后者把 `desc` 换成 `asc`），混在一起会让"哪一条红了"说不清。
 *
 * 被修复的缺陷（AUD-01，P1）
 * ------------------------
 *   `RunDriver.loadMessages` 原先用 `messagesRepo.list({ limit: 200 })`，而 `list` 是
 *   `(created_at asc, id asc) + LIMIT` ⇒ 拿到的是**最旧的** 200 条。长会话超窗之后，
 *   模型看不到最新消息（含本次 run 刚写入的用户消息），且**没有任何报错**。
 *
 * 判据
 * ----
 *   ① 250 条（> 200 窗口）⇒ `listTail({limit:200})` 返回**最新** 200 条，且**升序**；
 *      对照：`list({limit:200})` 仍返回**最旧** 200 条（这就是被修掉的那个语义）；
 *   ② 同秒并列时窗口由 `(created_at, id)` 的**降序**决定 —— 不依赖 rowid / 堆序；
 *   ③ 跨秒时时间优先（反转后整体升序，早的整体在前）；
 *   ④ 条数不足窗口 ⇒ 全给（不补空、不报错）；
 *   ⑤ 非法 `limit` ⇒ `ScopeError`（不静默夹取，与 `list` 同纪律）。
 *
 * 复跑：`cd packages/db && npx tsc -b && node --experimental-sqlite --test tests/message-tail.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { MessageRepo, Scope, ScopeError } from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A } from "./fixtures/runtime-fixture.mjs";

/** 窗口大小（与 `RunDriver` 的常量同值；这里写成字面量是刻意的 —— 判据是"超窗会丢最新"）。 */
const WINDOW = 200;

/** 建库 + 父链 + A 的会话仓储。 */
function seed() {
  const connection = freshConnection();
  seedParents(connection);
  const scopeA = new Scope(T_A);
  const messages = new MessageRepo(connection.db, scopeA, scopeA.ref(IDS.convA), DIALECT);
  return { connection, raw: connection.raw, messages };
}

/** 零填充 id：让字典序 == 插入序（`id asc` 才是"更晚"）。 */
function messageId(sequence) {
  return `dddd0000-0000-4000-8000-${String(sequence).padStart(12, "0")}`;
}

/** 直插一条消息（`created_at` 显式给，秒粒度并列只能靠这个拉平）。 */
function insertMessage(raw, { id, createdAt, role = "user", content = "hi" }) {
  raw
    .prepare(
      "insert into message (id, conversation_id, run_id, role, content, content_parts, token_count, created_at) " +
        "values (?, ?, null, ?, ?, null, null, ?)",
    )
    .run(id, IDS.convA, role, content, createdAt);
}

test("① 250 条（>窗口）⇒ listTail 返回**最新** 200 条且升序；list 仍返回最旧 200 条", async () => {
  const { connection, raw, messages } = seed();
  try {
    const total = 250;
    for (let index = 1; index <= total; index += 1) {
      insertMessage(raw, {
        id: messageId(index),
        createdAt: "2026-10-22 00:00:05",
        content: `m${index}`,
      });
    }

    const tail = await messages.listTail({ limit: WINDOW });
    assert.equal(tail.length, WINDOW, "窗口必须满 200 条（而不是 250）");
    assert.equal(
      tail[tail.length - 1].content,
      `m${total}`,
      "**最新一条必须在窗口里**（AUD-01 的判据：旧实现拿不到它）",
    );
    assert.equal(tail[0].content, `m${total - WINDOW + 1}`, "窗口起点 = 第 51 条（250-200+1）");

    // 升序：上下相邻两条的 (created_at, id) 严格递增。
    for (let index = 1; index < tail.length; index += 1) {
      const previous = tail[index - 1];
      const current = tail[index];
      assert.ok(
        previous.created_at < current.created_at ||
          (previous.created_at === current.created_at && previous.id < current.id),
        `第 ${index} 条与前一条不是升序（尾部窗口必须反转为升序）`,
      );
    }

    // 对照：旧的 `list({limit})` 语义 —— 取到的是**最旧**的 200 条（本用例正是要钉住这个差异）。
    const oldest = await messages.list({ limit: WINDOW });
    assert.equal(oldest.length, WINDOW);
    assert.equal(oldest[0].content, "m1", "list 仍是最旧优先（不是被改坏成尾部窗口）");
    assert.equal(
      oldest[oldest.length - 1].content,
      `m${WINDOW}`,
      "旧语义的最后一条是第 200 条 —— 第 201..250 条被静默截掉（AUD-01 的缺陷形态）",
    );
  } finally {
    connection.close();
  }
});

test("② 同秒 250 条并列 ⇒ 窗口由 (created_at, id) 降序决定，不依赖 rowid", async () => {
  const { connection, raw, messages } = seed();
  try {
    // **乱序插入**：插入序与 id 序无关（若实现靠 rowid / 堆序，取到的集合会跟着插入序走）。
    const ids = [];
    for (let index = 1; index <= 250; index += 1) ids.push(messageId(index));
    // 交替插入：先偶数位再奇数位（插入序 ≠ id 序）
    for (const id of ids.filter((_, index) => index % 2 === 0)) {
      insertMessage(raw, { id, createdAt: "2026-10-22 00:00:06" });
    }
    for (const id of ids.filter((_, index) => index % 2 === 1)) {
      insertMessage(raw, { id, createdAt: "2026-10-22 00:00:06" });
    }

    const tail = await messages.listTail({ limit: WINDOW });
    assert.deepEqual(
      tail.map((row) => row.id),
      ids.slice(ids.length - WINDOW),
      "同秒并列 ⇒ 窗口 = id 最大的 200 条，且按 id 升序返回（与插入序无关）",
    );
  } finally {
    connection.close();
  }
});

test("③ 跨秒：时间优先（反转后最早的仍在最前，id 只在同秒内生效）", async () => {
  const { connection, raw, messages } = seed();
  try {
    // 前 3 条在更早的秒，id 字典序**更大**（若实现把 id 当主键就会排错）。
    insertMessage(raw, { id: "eeee0000-0000-4000-8000-000000000001", createdAt: "2026-10-22 00:00:01", content: "early-1" });
    insertMessage(raw, { id: "eeee0000-0000-4000-8000-000000000002", createdAt: "2026-10-22 00:00:02", content: "early-2" });
    insertMessage(raw, { id: "eeee0000-0000-4000-8000-000000000003", createdAt: "2026-10-22 00:00:03", content: "early-3" });
    insertMessage(raw, { id: "dddd0000-0000-4000-8000-000000000001", createdAt: "2026-10-22 00:00:09", content: "late-1" });

    const tail = await messages.listTail({ limit: 3 });
    assert.deepEqual(
      tail.map((row) => row.content),
      ["early-2", "early-3", "late-1"],
      "limit=3 ⇒ 最近 3 条（按时间），再反转成升序",
    );
  } finally {
    connection.close();
  }
});

test("④ 条数不足窗口 ⇒ 全给（不补空、不报错）", async () => {
  const { connection, raw, messages } = seed();
  try {
    insertMessage(raw, { id: messageId(1), createdAt: "2026-10-22 00:00:01", content: "only" });
    const tail = await messages.listTail({ limit: WINDOW });
    assert.equal(tail.length, 1);
    assert.equal(tail[0].content, "only");
  } finally {
    connection.close();
  }
});

test("⑤ 非法 limit ⇒ ScopeError（不静默夹取）", async () => {
  const { connection, messages } = seed();
  try {
    for (const bogus of [0, -1, 1.5, 501]) {
      await assert.rejects(
        () => messages.listTail({ limit: bogus }),
        (error) => {
          assert.ok(error instanceof ScopeError, `limit=${bogus} 必须 ScopeError，实测 ${String(error)}`);
          return true;
        },
        `limit=${bogus} 必须被拒绝`,
      );
    }
  } finally {
    connection.close();
  }
});
