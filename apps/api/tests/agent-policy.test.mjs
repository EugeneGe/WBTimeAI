/**
 * T3-05 · 策略配置载体（`modules/agent/policy.ts`）的行为证明。
 *
 * 判据（R3-13 §11-9 逐条）：
 *   ① harness 来源 = `runtime_config.harness`，缺省 `general`（约定值，route_reason='default'）；
 *   ② 白名单 = `["general"]`；**任何**白名单外的值（含 `coding`、大小写变体、非字符串）
 *      ⇒ 抛 422 `VALIDATION_ERROR` + `reason_code='harness_unsupported'` —— 不静默回落
 *      （反例 CE-T5-1 的正向面；注入面见施工记录 §反例）；
 *   ③ 路由成功 ⇒ `writeHarnessAudit` 落一行 `agent.harness_routed`（resource_type=
 *      `agent_run`、metadata.route_reason；T3-05 的 run_id 恒 null —— T3-08 接线补齐）；
 *   ④ `run_mode` 断言：非 INLINE ⇒ 抛 + `reason_code='run_mode_unsupported'`（R3-06）。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  AUDIT_ACTION_HARNESS_ROUTED,
  HARNESS_SUPPORTED,
  assertInlineRunMode,
  routeHarness,
  writeHarnessAudit,
} from "../dist/modules/agent/policy.js";
import { createSqliteDb } from "@wbtime/db/connection";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ROOT, TENANT_ID } from "./routes-harness.mjs";

const DDL = readFileSync(join(ROOT, "output", "ddl.sqlite.sql"), "utf8");

/** 建内存库 + 最小父链（tenant + agent + user，audit_log 的 FK 需要）。 */
function seedDb() {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  const tenantId = TENANT_ID;
  const userId = "aaaa0000-0000-4000-8000-0000000000a1";
  const agentId = "aaaa0000-0000-4000-8000-0000000000a2";
  connection.raw
    .prepare("insert into tenant (id, name, slug, is_active) values (?, 't', 't', 1)")
    .run(tenantId);
  connection.raw
    .prepare(
      "insert into user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
        "values (?, ?, 'alice', 'a@a.example', 'x', 'alice', 1, 0)",
    )
    .run(userId, tenantId);
  connection.raw
    .prepare(
      "insert into agent (id, tenant_id, organization_id, workspace_id, name, description, type, status, current_version_id, created_by) " +
        "values (?, ?, null, null, 'a', null, 'PRIMARY', 'DRAFT', null, ?)",
    )
    .run(agentId, tenantId, userId);
  return { connection, tenantId, userId, agentId };
}

// ---------------------------------------------------------------------------
// A · routeHarness：值域 + 缺省（R3-13 ①②）
// ---------------------------------------------------------------------------

test("A · 白名单恰一值 general；缺省路由 general + route_reason=default（R3-13 ①）", () => {
  assert.deepEqual([...HARNESS_SUPPORTED], ["general"], "白名单逐字（coding 不在）");

  const byDefault = routeHarness({});
  assert.equal(byDefault.harness, "general");
  assert.equal(byDefault.routeReason, "default");

  const explicitNull = routeHarness({ harness: null });
  assert.equal(explicitNull.harness, "general", "显式 null 视为未配置（JSONB 开放对象常态）");
  assert.equal(explicitNull.routeReason, "default");

  const configured = routeHarness({ harness: "general" });
  assert.equal(configured.harness, "general");
  assert.equal(configured.routeReason, "configured");
});

test("A · 白名单外一律 422 harness_unsupported，绝不静默回落（R3-13 ②③）", () => {
  // coding 在列（裁定原文点名）；大小写变体与未知值同罪；非字符串也是白名单外
  for (const bogus of ["coding", "CODING", "general ", "hacker", "", 1, true, {}]) {
    assert.throws(
      () => routeHarness({ harness: bogus }),
      (error) => {
        if (error === null || typeof error !== "object") return false;
        const body = error;
        return (
          body.statusCode === 422 &&
          body.code === "VALIDATION_ERROR" &&
          body.data?.reason_code === "harness_unsupported"
        );
      },
      `harness=${JSON.stringify(bogus)} 必须被拒（不得回落 general）`,
    );
  }
});

// ---------------------------------------------------------------------------
// B · assertInlineRunMode（R3-06）
// ---------------------------------------------------------------------------

test("B · run_mode：INLINE 放行；其余一律 422 run_mode_unsupported", () => {
  assert.equal(assertInlineRunMode("INLINE"), undefined, "INLINE 放行（无返回值即成功）");
  for (const bogus of ["BATCH", "CRON", "inline", ""]) {
    assert.throws(
      () => assertInlineRunMode(bogus),
      (error) =>
        error !== null &&
        typeof error === "object" &&
        error.statusCode === 422 &&
        error.data?.reason_code === "run_mode_unsupported",
      `run_mode=${JSON.stringify(bogus)} 必须被拒`,
    );
  }
});

// ---------------------------------------------------------------------------
// C · writeHarnessAudit：R3-13 ⑤ 的审计行（T3-05 形态：run_id 恒 null）
// ---------------------------------------------------------------------------

test("C · 审计行：action/resource_type/metadata.route_reason 逐字；run_id 恒 null（T3-08 接线项）", async () => {
  const { connection, tenantId, userId, agentId } = seedDb();
  try {
    await writeHarnessAudit({
      db: connection.db,
      dialect: "sqlite",
      tenantId,
      userId,
      agentId,
      runId: null,
      routed: { harness: "general", routeReason: "default" },
      requestId: "req-test-1",
      now: new Date("2026-10-22T08:00:00Z"),
    });

    const rows = connection.raw
      .prepare("select * from audit_log where action = ?")
      .all(AUDIT_ACTION_HARNESS_ROUTED);
    assert.equal(rows.length, 1);
    const row = rows[0];
    assert.equal(row.tenant_id, tenantId);
    assert.equal(row.agent_id, agentId);
    assert.equal(row.user_id, userId);
    assert.equal(row.resource_type, "agent_run", "R3-13 ⑤ 逐字");
    assert.equal(row.run_id, null, "T3-05 不创建 run ⇒ run_id 恒 null");
    assert.equal(row.resource_id, null, "同上（T3-08 接线补 <run_id>）");
    assert.equal(row.outcome, "success");
    assert.equal(row.request_id, "req-test-1");
    assert.deepEqual(JSON.parse(row.metadata), { route_reason: "default", harness: "general" });
    assert.ok(row.created_at, "created_at 落库");

    // 再写一行（configured 路径）：审计不覆盖、逐行累积
    await writeHarnessAudit({
      db: connection.db,
      dialect: "sqlite",
      tenantId,
      userId: null,
      agentId,
      runId: null,
      routed: { harness: "general", routeReason: "configured" },
      requestId: "req-test-2",
    });
    assert.equal(
      connection.raw.prepare("select count(*) as n from audit_log").get().n,
      2,
      "逐行累积，不覆盖",
    );
  } finally {
    connection.close();
  }
});
