// T2-02 · K-1（壳成员级全等）· K-2（两态不同型）
//
// 口径来源：`docs/V1.0/V0.2.0-身份与HTTP垂直切片/01-计划/02-响应壳与SSE.md` §7。
// 硬要求：**运行时读契约比对**，不写死字段字面量 —— 写死就变成「测试自己跟自己比」，
// 契约加了第 5 个键也照样绿。空集一律 INVALID（本合同侧 floor 独立断言，防哑真）。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ENVELOPE_FIELD_NAMES,
  ERROR_CODES,
  ErrorEnvelopeSchema,
  OkEnvelopeSchema,
  Value,
  errorResponse,
  isErrorShell,
  isSuccessShell,
  okResponse,
} from "@wbtime/core";

/** 仓库根（apps/api/tests → apps/api → apps → 根）。 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

function readContract(relativePath) {
  return JSON.parse(readFileSync(join(ROOT, relativePath), "utf8"));
}

const envelopeContract = readContract("contracts/envelope.schema.json");

test("K-1 壳成员级全等：ENVELOPE_FIELD_NAMES.length === 4 且集合 == 契约 required 并集", () => {
  const successRequired = envelopeContract.$defs.successEnvelope.required;
  const errorRequired = envelopeContract.$defs.errorEnvelope.required;

  // 空集 floor：契约侧为空 ⇒ 这条断言必须红，而不是「空 == 空 所以 PASS」。
  assert.ok(successRequired.length > 0, "契约 successEnvelope.required 不得为空");
  assert.ok(errorRequired.length > 0, "契约 errorEnvelope.required 不得为空");

  const contractFields = [...new Set([...successRequired, ...errorRequired])].sort();

  assert.equal(ENVELOPE_FIELD_NAMES.length, 4, "生成物顶层键数量必须是 4");
  assert.ok(ENVELOPE_FIELD_NAMES.length > 0, "生成物字段清单不得为空（空集不是 PASS）");
  assert.deepEqual([...ENVELOPE_FIELD_NAMES].sort(), contractFields, "生成物字段集合必须与契约全等");
});

test("K-1 契约自洽：顶层键数 4 且成功壳 / 失败壳 required 同构且禁第 5 键", () => {
  const invariance = envelopeContract["x-wbtimeai"].enforcement.field_invariance;

  assert.equal(invariance.top_level_key_count, 4);
  assert.deepEqual(
    [...envelopeContract.$defs.successEnvelope.required].sort(),
    [...envelopeContract.$defs.errorEnvelope.required].sort(),
    "成功壳与失败壳的 required 必须同构（四顶层键恒在）",
  );

  // 「壳只有一层」是契约硬规则：additionalProperties: false ⇒ 第 5 个顶层键非法。
  assert.equal(envelopeContract.$defs.successEnvelope.additionalProperties, false);
  assert.equal(envelopeContract.$defs.errorEnvelope.additionalProperties, false);

  // 生成物字段名必须逐个来自契约（成员级，不只看数量）。
  for (const field of ENVELOPE_FIELD_NAMES) {
    assert.ok(
      envelopeContract.$defs.successEnvelope.properties[field] !== undefined,
      `生成物字段 ${field} 在契约 successEnvelope.properties 里不存在`,
    );
  }
});

test("K-2 两态不同型：两个方向的 Value.Check 都必须为 false", () => {
  const okBody = okResponse({ id: "a1" }, "rid-1");
  const errBody = errorResponse(ERROR_CODES.NOT_FOUND, "资源不存在", {}, "rid-1");

  // 反例口径：用 `code: number | string` 单类型表达 ⇒ 两向 Check 至少一向变 true。
  assert.equal(Value.Check(ErrorEnvelopeSchema, okBody), false, "成功壳不得通过失败壳校验");
  assert.equal(Value.Check(OkEnvelopeSchema, errBody), false, "失败壳不得通过成功壳校验");

  // 正向（防止「两边都恒 false」这种假成立）
  assert.equal(Value.Check(OkEnvelopeSchema, okBody), true);
  assert.equal(Value.Check(ErrorEnvelopeSchema, errBody), true);

  assert.equal(typeof okBody.code, "number");
  assert.equal(okBody.code, 0);
  assert.equal(typeof errBody.code, "string");
  assert.equal(errBody.code, "NOT_FOUND");
});

test("四键恒在：request_id 键不可缺、值可为 null；data 缺省 {}", () => {
  const okBody = okResponse(null);
  const errBody = errorResponse(ERROR_CODES.INTERNAL_ERROR, "内部错误");

  for (const body of [okBody, errBody]) {
    assert.deepEqual(Object.keys(body).sort(), ["code", "data", "message", "request_id"]);
    assert.ok(Object.hasOwn(body, "request_id"), "request_id 键必须存在");
  }
  assert.equal(okBody.request_id, null);
  assert.equal(errBody.request_id, null);
  assert.deepEqual(errBody.data, {});

  // messageEnvelope：唯一的二层壳（外层恒 "ok"，内层是业务提示语）
  const messageEnvelope = okResponse({ message: "已创建" }, "rid-2");
  assert.equal(messageEnvelope.message, "ok");
  assert.equal(messageEnvelope.data.message, "已创建");
  assert.equal(Value.Check(OkEnvelopeSchema, messageEnvelope), true);
});

test("已是壳判定是值判定，不是键判定", () => {
  const failureLike = { code: "NOT_FOUND", message: "资源不存在", data: {}, request_id: "r1" };

  // 键判定会把这条误当成功壳 ⇒ 二次包裹。值判定必须为 false。
  assert.equal(isSuccessShell(failureLike), false, "失败壳四键俱在，但不是成功壳");
  assert.equal(isErrorShell(failureLike), true);

  assert.equal(isSuccessShell({ code: 0, message: "ok", data: {}, request_id: "r1" }), true);
  assert.equal(isSuccessShell({ code: 0, message: "ok", data: {} }), false, "缺 request_id 键不算成功壳");
  assert.equal(isSuccessShell({ code: 0, message: "OK", data: {}, request_id: "r1" }), false);
  assert.equal(isSuccessShell({ code: 1, message: "ok", data: {}, request_id: "r1" }), false);
  assert.equal(isSuccessShell(null), false);
  assert.equal(isSuccessShell([]), false);
  assert.equal(isSuccessShell("ok"), false);

  assert.equal(isErrorShell({ code: "NOT_FOUND", message: "x", data: {} }), false, "缺 request_id 键不算失败壳");
  assert.equal(isErrorShell({ code: 0, message: "ok", data: {}, request_id: "r1" }), false);
});
