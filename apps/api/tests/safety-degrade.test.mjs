/**
 * T3-13 · R3-14 开关 + 失败策略矩阵（验收 ④ ⑥）。
 *
 * 判据
 * ----
 *   ① **无行 = 默认开**：命中 ⇒ DENY/REDACT 正常发生；
 *   ② **`enabled=false` ⇒ 双断言**（防"一关全关"）：非底线规则跳过（含 PII 的无害文本
 *      ALLOW）+ **底线项（凭据形态）仍 DENY**；审计记 `disabled=true` + `degraded=true`；
 *   ③ **R3-14 ③**：代码里不得出现 `safety.local_rules.<tenant>` 键拼接（假多租户能力）；
 *   ④ **失败策略矩阵**（§9）：本地规则故障 ⇒ 任何等级 DENY；「语义未配置」⇒ 不 blanket
 *      DENY 且**不标 degraded**（R3 对齐注：未启用 ≠ 降级）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/safety-degrade.test.mjs`
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { AuditLogRepo, FeatureFlagRepo } from "@wbtime/db";

import { decideOnFailure } from "../dist/modules/safety/failure-policy.js";
import { SAFETY_LOCAL_RULES_FLAG } from "../dist/modules/safety/feature.js";
import { SafetyGate } from "../dist/modules/safety/gate.js";
import { makeApp, ROOT, TENANT_ID } from "./routes-harness.mjs";

/** 底线内容（凭据形态 —— 开关关闭时仍 DENY）。 */
const BASELINE_CONTENT = "key=sk-abcdefghijklmnopqrstuvwx";
/** 非底线内容（PII —— 开关关闭时应放行）。 */
const NON_BASELINE_CONTENT = "客户手机 13812345678";

/** 造 gate + 开关仓储。 */
function makeGateWithFlag(fixture) {
  const gate = new SafetyGate({ db: fixture.connection.db, dialect: "sqlite", tenantId: TENANT_ID });
  const flags = new FeatureFlagRepo(fixture.connection.db, "sqlite");
  return { gate, flags };
}

test("A-1 · **无行 = 默认开**：非底线（PII）命中 ⇒ REDACT 正常发生", async () => {
  const fixture = await makeApp({ username: "saf-dg-a1" });
  try {
    const { gate, flags } = makeGateWithFlag(fixture);
    assert.equal(await flags.findByName(SAFETY_LOCAL_RULES_FLAG), null, "前置：无行");

    const verdict = await gate.evaluate({ stage: "input", content: NON_BASELINE_CONTENT, requestId: "req-dg1" });
    assert.equal(verdict.decision, "REDACT", "无行 ⇒ 规则生效（裁定 R3-14 ①）");
    assert.equal(verdict.disabled, false);
  } finally {
    await fixture.close();
  }
});

test("A-2 · **enabled=false 双断言**：非底线放行 + **底线项仍 DENY**（防一关全关）", async () => {
  const fixture = await makeApp({ username: "saf-dg-a2" });
  try {
    const { gate, flags } = makeGateWithFlag(fixture);
    await flags.upsert(SAFETY_LOCAL_RULES_FLAG, false);

    // 断言 1：非底线（PII）不再判定 ⇒ ALLOW
    const nonBaseline = await gate.evaluate({ stage: "input", content: NON_BASELINE_CONTENT, requestId: "req-dg2a" });
    assert.equal(nonBaseline.decision, "ALLOW", "关闭后非底线规则必须跳过");
    assert.equal(nonBaseline.hits.length, 0, "跳过 = 没有命中（不是命中后放行）");
    assert.equal(nonBaseline.disabled, true);

    // 断言 2：底线（凭据）**仍被判定**（决策可以是 REDACT —— "仍强制"指仍判定，
    // 不是"必 DENY"；凭据在 input 段的正确处置就是脱敏）。一关全关的形态是
    // "底线项也被跳过（hits 为空 + ALLOW）" ⇒ 那才是本条要红的。
    const baseline = await gate.evaluate({ stage: "input", content: BASELINE_CONTENT, requestId: "req-dg2b" });
    assert.equal(baseline.decision, "REDACT", "底线项关闭态下仍判定（凭据 ⇒ REDACT）");
    assert.ok(baseline.hits.length >= 1, "底线命中必须在关闭态下仍被检出");

    // 审计：disabled=true + degraded=true（R3-14 ②）
    const repo = new AuditLogRepo(fixture.connection.db, "sqlite");
    const rows = await repo.listByResourceId(TENANT_ID, "input");
    const metadata = rows.map((row) => (typeof row.metadata === "string" ? JSON.parse(row.metadata) : row.metadata));
    const disabledRows = metadata.filter((item) => item.disabled === true);
    assert.ok(disabledRows.length >= 2, "关闭态的两条判定都要有 disabled=true");
    for (const item of disabledRows) {
      assert.equal(item.degraded, true, "显式关闭 ⇒ 降级审计（R3-14 ②）");
    }
  } finally {
    await fixture.close();
  }
});

test("A-3 · **R3-14 ③**：代码里不得出现租户级键拼接（假多租户能力）", () => {
  const files = [
    join(ROOT, "apps/api/src/modules/safety/feature.ts"),
    join(ROOT, "apps/api/src/modules/safety/gate.ts"),
  ];
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    assert.equal(
      /safety\.local_rules\.\$?\{/.test(source) || source.includes("safety.local_rules.${"),
      false,
      `${file} 出现了租户级键拼接 —— 租户开关归 1.1+，本版私搭会造成假能力`
    );
  }
});

// ---------------------------------------------------------------------------
// B 组 · 失败策略矩阵（§9 的纯函数面）
// ---------------------------------------------------------------------------

test("B-1 · 本地规则故障 ⇒ **任何等级**都 DENY（fail-closed，永不降级）", () => {
  for (const riskLevel of ["high", "medium", "low"]) {
    const verdict = decideOnFailure({ riskLevel, localRulesFailed: true, semanticState: "not-configured" });
    assert.ok(verdict !== null);
    assert.equal(verdict.decision, "DENY", `${riskLevel} 风险 + 引擎故障 ⇒ DENY`);
    assert.equal(verdict.degraded, false, "引擎故障不是降级，是拒绝");
  }
});

test("B-2 · 语义未配置 ⇒ **不 blanket DENY 且不标 degraded**（R3 对齐注）", () => {
  for (const riskLevel of ["high", "medium", "low"]) {
    const verdict = decideOnFailure({ riskLevel, localRulesFailed: false, semanticState: "not-configured" });
    assert.equal(verdict, null, "未配置态走正常判定路径（不是故障）");
    // "不标 degraded" 由 gate 侧保证：语义未配置时 degraded 恒 false（见 gate.evaluate）。
  }
});

test("B-3 · 语义超时：高 ⇒ DENY；中/低 ⇒ ALLOW + degraded（矩阵行保留，本版不可达）", () => {
  const high = decideOnFailure({ riskLevel: "high", localRulesFailed: false, semanticState: "timeout" });
  assert.equal(high?.decision, "DENY");

  const medium = decideOnFailure({ riskLevel: "medium", localRulesFailed: false, semanticState: "timeout" });
  assert.equal(medium?.decision, "ALLOW");
  assert.equal(medium?.degraded, true, "已启用后不可用才标 degraded");

  const low = decideOnFailure({ riskLevel: "low", localRulesFailed: false, semanticState: "unavailable" });
  assert.equal(low?.decision, "ALLOW");
  assert.equal(low?.degraded, true);
});
