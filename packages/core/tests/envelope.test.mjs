// T1-02 · @wbtime/core 响应壳：四顶层键恒在，且与契约字段集合全等。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ENVELOPE_FIELDS,
  ERROR_CODES,
  Value,
  ErrorEnvelopeSchema,
  OkEnvelopeSchema,
  errorResponse,
  okResponse,
} from "../dist/index.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const schema = JSON.parse(
  readFileSync(join(ROOT, "contracts", "envelope.schema.json"), "utf8"),
);

test("响应壳字段集合与契约全等", () => {
  const okFields = schema.$defs.successEnvelope.required;
  const errFields = schema.$defs.errorEnvelope.required;
  assert.deepEqual([...ENVELOPE_FIELDS].sort(), [...okFields].sort());
  assert.deepEqual([...ENVELOPE_FIELDS].sort(), [...errFields].sort());
});

test("空集合必红：字段清单非空", () => {
  assert.ok(ENVELOPE_FIELDS.length > 0, "响应壳字段清单不得为空");
});

test("成功壳：code 是整数 0、message 恒为 ok、四键恒在", () => {
  const env = okResponse({ id: "a" }, "rid-1");
  assert.deepEqual(Object.keys(env).sort(), ["code", "data", "message", "request_id"]);
  assert.equal(env.code, 0);
  assert.equal(env.message, "ok");
  assert.equal(env.request_id, "rid-1");
  assert.ok(Value.Check(OkEnvelopeSchema, env));
});

test("失败壳：code 是字符串错误码，与成功壳不同型", () => {
  const env = errorResponse(ERROR_CODES.NOT_FOUND, "资源不存在");
  assert.deepEqual(Object.keys(env).sort(), ["code", "data", "message", "request_id"]);
  assert.equal(typeof env.code, "string");
  assert.equal(env.code, "NOT_FOUND");
  assert.deepEqual(env.data, {});
  assert.equal(env.request_id, null);
  assert.ok(Value.Check(ErrorEnvelopeSchema, env));
});

test("request_id 键恒在（值可为 null，键不可缺）", () => {
  const env = okResponse(null);
  assert.ok("request_id" in env);
  assert.equal(env.request_id, null);
});
