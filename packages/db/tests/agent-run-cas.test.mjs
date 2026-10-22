/**
 * AUD-03 · `AgentRunRepo.finalizeIfActive`（**条件终态写 / CAS**）的并发证明。
 *
 * 被修复的缺陷（AUD-03，P1）
 * ------------------------
 *   原 `finalize` 是**无条件** `UPDATE`。`RunDriver.#settle` 的路径是
 *   「读状态 → 发终态帧 → `finalize`」，`coordinator.cancel` 的路径是
 *   「CAS 抢 lease → 无条件 `finalize`」；两条路径交错时，**后写者赢** ——
 *   一次晚到的 `finalize(SUCCEEDED)` 会把已经落库的 `CANCELLED` 覆写回成功
 *   （"取消复活"）。
 *
 * 判据
 * ----
 *   ① `Promise.all` 同时写 `SUCCEEDED` 与 `CANCELLED` ⇒ **恰好 1 个 applied**，
 *      终值行与 **applied 方**一致（终态由先到者决定，后到者一行都没改）；
 *   ② 终态行**不带异族字段**：成功态不得带 `error` / `error_type`；
 *      取消态不得带 `success=true`（否则前端会读到"取消但成功"的自相矛盾行）；
 *   ③ 行不存在 ⇒ `applied=false` + `row === null`（**调用点据此给 404**）；
 *   ④ 行已终态 ⇒ `applied=false` + `row !== null`（**调用点据此走幂等返回**）——
 *      这一格就是"404 与幂等不得混在一起"的机器判据；
 *   ⑤ 对照：无条件 `finalize` 仍会覆写终态行（保留它是因为单写者场景要用，
 *      注释已标明"仅限非并发收敛"）。
 *
 * 复跑：`cd packages/db && npx tsc -b && node --experimental-sqlite --test tests/agent-run-cas.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { AgentRunRepo, Scope } from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A } from "./fixtures/runtime-fixture.mjs";

/** 建库 + 父链 + A 的 run 仓储（`runA` 的初始状态是 `QUEUED`）。 */
function seed() {
  const connection = freshConnection();
  seedParents(connection);
  const scopeA = new Scope(T_A);
  const runs = new AgentRunRepo(connection.db, scopeA, DIALECT);
  return { connection, raw: connection.raw, runs, runA: scopeA.ref(IDS.runA) };
}

/** 成功态的终态 patch（**不带** `error` / `error_type`）。 */
const SUCCEEDED_PATCH = Object.freeze({
  status: "SUCCEEDED",
  stopReason: "model_finish",
  success: true,
  completedAt: "2026-10-22 00:00:10",
  durationMs: 1200,
});

/** 取消态的终态 patch（`success=false`，`error_type=CANCELLED`）。 */
const CANCELLED_PATCH = Object.freeze({
  status: "CANCELLED",
  stopReason: "cancelled",
  success: false,
  errorType: "CANCELLED",
  completedAt: "2026-10-22 00:00:11",
  durationMs: 1300,
});

test("① 并发 finalizeIfActive ⇒ **恰好 1 个 applied**，终值行与 applied 方一致", async () => {
  const { connection, raw, runs, runA } = seed();
  try {
    const [first, second] = await Promise.all([
      runs.finalizeIfActive(runA, SUCCEEDED_PATCH),
      runs.finalizeIfActive(runA, CANCELLED_PATCH),
    ]);

    const applied = [first, second].filter((outcome) => outcome.applied);
    assert.equal(
      applied.length,
      1,
      `必须恰好 1 个 applied（实测 ${applied.length}）—— 两个都 applied 就是"双终态写"`,
    );

    const winner = applied[0];
    const row = raw.prepare("select status, stop_reason, success, error_type, error from agent_run where id = ?").get(IDS.runA);

    assert.equal(row.status, winner.row.status, "终值行状态必须等于 applied 方的状态");
    assert.equal(row.stop_reason, winner.row.stop_reason, "stop_reason 也必须同源（不得混写）");

    // ② 终态行不带异族字段。
    if (row.status === "SUCCEEDED") {
      assert.equal(row.success, 1, "成功态 ⇒ success = true");
      assert.equal(row.error, null, "成功态**不得**带 error（异族字段）");
      assert.equal(row.error_type, null, "成功态**不得**带 error_type");
    } else {
      assert.equal(row.status, "CANCELLED");
      assert.equal(row.success, 0, "取消态不得带 success=true");
      assert.equal(row.error_type, "CANCELLED");
    }

    // 未 applied 的一方也必须带回"现状行"，且该行就是终值行。
    const loser = [first, second].find((outcome) => !outcome.applied);
    assert.notEqual(loser, undefined);
    assert.notEqual(loser.row, null, "行存在 ⇒ 未 applied 的一方必须能看到现状行（不是 null）");
    assert.equal(loser.row.status, row.status, "现状行 = 终值行");
  } finally {
    connection.close();
  }
});

test("② 行不存在 ⇒ applied=false 且 row=null（调用点据此 404）", async () => {
  const { connection, runs } = seed();
  try {
    const outcome = await runs.finalizeIfActive(
      new Scope(T_A).ref("f0000000-0000-4000-8000-0000000000de"),
      SUCCEEDED_PATCH,
    );
    assert.equal(outcome.applied, false);
    assert.equal(outcome.row, null, "行不存在必须给 null —— 与「已终态」（row 非空）严格分开");
  } finally {
    connection.close();
  }
});

test("③ 行已终态 ⇒ applied=false 且 row 非空（调用点据此走幂等，不 404）", async () => {
  const { connection, runs, runA } = seed();
  try {
    const first = await runs.finalizeIfActive(runA, SUCCEEDED_PATCH);
    assert.equal(first.applied, true);

    const second = await runs.finalizeIfActive(runA, CANCELLED_PATCH);
    assert.equal(second.applied, false, "终态行不得被二次写终态");
    assert.equal(second.row.status, "SUCCEEDED", "后到者的现状行 = 先到者落的终态（CANCELLED 没被写进去）");
    assert.equal(second.row.stop_reason, "model_finish", "stop_reason 不得被覆写");
  } finally {
    connection.close();
  }
});

test("④ 跨租户 ref ⇒ 不命中（CAS 的租户谓词恒在）", async () => {
  const { connection, runs, runA } = seed();
  try {
    // `runA` 属于 T_A；这里用 **本 scope（T_A）铸造**、但 id 指向 **B 租户** run 的 ref：
    // `owns()` 只校验铸造来源（放行），挡住它的是 `scopedWhere()` 的租户谓词。
    const outcome = await runs.finalizeIfActive(new Scope(T_A).ref(IDS.runB), SUCCEEDED_PATCH);
    assert.equal(outcome.applied, false, "别租户的 run 不得被本 scope 写入");
    assert.equal(outcome.row, null, "别租户的行对本 scope 不可见 ⇒ null");

    // 对照：本 scope 的 run 仍然可写（否则"不命中"可能只是整条路坏了）。
    const own = await runs.finalizeIfActive(runA, SUCCEEDED_PATCH);
    assert.equal(own.applied, true);
  } finally {
    connection.close();
  }
});

test("⑤ 对照：无条件 finalize 仍会覆写终态行（单写者场景保留，注释已标明用途）", async () => {
  const { connection, runs, runA } = seed();
  try {
    await runs.finalize(runA, CANCELLED_PATCH);
    const overwritten = await runs.finalize(runA, SUCCEEDED_PATCH);
    assert.equal(
      overwritten.status,
      "SUCCEEDED",
      "无条件写会覆写 —— 这正是并发路径**不能**用它的原因（AUD-03 的缺陷形态）",
    );
  } finally {
    connection.close();
  }
});
