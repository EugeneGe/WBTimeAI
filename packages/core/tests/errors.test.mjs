// T1-02 · @wbtime/core 错误码：与 contracts/errors.json 逐项全等。
// Oracle 是契约文件本身，不是手抄的快照。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ERROR_CODE_LIST,
  ERROR_CODES,
  ERROR_HTTP_STATUS,
  UNKNOWN_ERROR_CODE,
  httpStatusFor,
} from "../dist/index.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const contract = JSON.parse(readFileSync(join(ROOT, "contracts", "errors.json"), "utf8"));

test("错误码集合与契约逐项全等（数量 + 每个码值）", () => {
  const expected = Object.keys(contract.codes).sort();
  assert.equal(ERROR_CODE_LIST.length, expected.length, "错误码数量必须与契约一致");
  assert.deepEqual([...ERROR_CODE_LIST].sort(), expected);
});

test("ERROR_CODES 键 == 值，且与清单同源", () => {
  for (const code of ERROR_CODE_LIST) {
    assert.equal(ERROR_CODES[code], code);
  }
  assert.equal(Object.keys(ERROR_CODES).length, ERROR_CODE_LIST.length);
});

test("HTTP 状态映射逐码等于契约的 http_status", () => {
  for (const code of ERROR_CODE_LIST) {
    assert.equal(
      ERROR_HTTP_STATUS[code],
      contract.codes[code].http_status,
      `${code} 的 HTTP 状态与契约不一致`,
    );
  }
});

test("空集合必红：清单非空（门禁防哑真的前提）", () => {
  assert.ok(ERROR_CODE_LIST.length > 0, "错误码清单不得为空");
});

test("未知码回落 UNKNOWN，不静默给 500 字面量", () => {
  assert.equal(UNKNOWN_ERROR_CODE, "UNKNOWN");
  assert.equal(httpStatusFor("NOT_A_REAL_CODE"), ERROR_HTTP_STATUS.UNKNOWN);
});
