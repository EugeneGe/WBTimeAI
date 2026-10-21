/**
 * W0 收尾 · **v0019 `Run*` TypeBox ↔ OpenAPI 对齐测试**。
 *
 * 为什么需要它：`schemas-run.ts` 是手写的第二真相源（`packages/contracts` 没有 OpenAPI 的
 * TS 生成物）。没有断言时，"手写"等于裸奔 —— 改契约或改 schema 都不会红，直到 W5 联调才崩。
 *
 * 断言组（逐对象执行，对象集合与字段集合都从契约读，不抄表）：
 *  1. **属性名集合相等**（多一个键会污染响应壳，少一个键前端拿到 undefined）；
 *  2. **required 集合相等**（多一个必填 = 拒掉合法请求；少一个 = 放行非法请求）；
 *  3. `status` 七值枚举与默认 `QUEUED` 逐字相同；
 *  4. `stop_reason` 可空性 = `string | null`（拒绝 number），且**不是必填**（契约未列入 required）；
 *  5. `STOP_REASONS` 恰好 11 值，与 `contracts/v0019.README.md` §2 的清单逐字一致。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { Value } from "@sinclair/typebox/value";

import {
  ResultOutSchema,
  RUN_STATUSES,
  RunOutSchema,
  RunRequestSchema,
  RunResponseSchema,
  STOP_REASONS,
} from "../dist/routes/schemas-run.js";
import { ROOT } from "./routes-harness.mjs";

const SPEC = JSON.parse(readFileSync(join(ROOT, "contracts", "openapi.v1.frozen.v0019.json"), "utf8"));
const SCHEMAS = SPEC.components.schemas;

const CASES = [
  ["RunRequest", RunRequestSchema],
  ["RunResponse", RunResponseSchema],
  ["RunOut", RunOutSchema],
  ["ResultOut", ResultOutSchema],
];

test("v0019 · 四个对象的属性名集合与契约逐字相等", () => {
  for (const [name, schema] of CASES) {
    const contract = SCHEMAS[name];
    assert.ok(contract, `契约里应有 ${name}`);
    assert.deepEqual(
      Object.keys(schema.properties).sort(),
      Object.keys(contract.properties).sort(),
      `${name} 属性名集合`
    );
  }
});

test("v0019 · required 集合与契约逐字相等", () => {
  for (const [name, schema] of CASES) {
    const contract = SCHEMAS[name];
    assert.deepEqual([...(schema.required ?? [])].sort(), [...(contract.required ?? [])].sort(), `${name} required`);
  }
});

test("v0019 · status 七值枚举 + 默认 QUEUED 与契约逐字相同", () => {
  const c = SCHEMAS.RunResponse.properties.status;
  assert.deepEqual([...RUN_STATUSES], c.enum, "RUN_STATUSES 顺序须与契约 enum 一致");
  assert.equal(c.default, "QUEUED");
  assert.equal(SCHEMAS.RunOut.properties.status.default, "QUEUED");
  assert.equal(c.enum.length, 7);
});

test("v0019 · stop_reason：string / null 通过，number 拒绝，且非必填", () => {
  const base = {
    id: "r1",
    agent_id: "a1",
    agent_version_id: "v1",
    conversation_id: "c1",
  };
  assert.ok(Value.Check(RunResponseSchema, { ...base, stop_reason: "model_finish" }));
  assert.ok(Value.Check(RunResponseSchema, { ...base, stop_reason: null }));
  assert.ok(Value.Check(RunResponseSchema, base), "契约未把 stop_reason 列入 required ⇒ 缺省必须通过");
  assert.ok(!Value.Check(RunResponseSchema, { ...base, stop_reason: 42 }), "number 必须被拒");
  assert.ok(!Value.Check(RunResponseSchema, { ...base, status: "SUCCESS" }), "非七值 status 必须被拒（py 线 SUCCESS 不得混入）");
});

test("v0019 · STOP_REASONS 恰好 11 值且与登记件逐字一致", () => {
  assert.equal(STOP_REASONS.length, 11);
  assert.deepEqual([...STOP_REASONS], [
    "model_finish",
    "tool_failed",
    "approval_rejected",
    "cancelled",
    "budget_tokens",
    "budget_cost",
    "budget_turns",
    "budget_tools",
    "wall_time",
    "provider_error",
    "unknown_recovery",
  ]);
});
