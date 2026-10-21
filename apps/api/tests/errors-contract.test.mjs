// T2-02 · K-5（30 码 / 13 类映射计数）· K-6（`DEPENDENCY_MISSING` 双状态）
//
// 口径来源：`docs/V1.0/V0.2.0-身份与HTTP垂直切片/01-计划/02-响应壳与SSE.md` §3 / §7。
// 全部断言**运行时读 `contracts/errors.json`** 比对，不写死码表 —— 码表在契约里是
// 唯一真源，测试再抄一份就等于给自己发了一份「可以漂移的副本」。

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import { ERROR_HTTP_STATUS, dependencyMissing, httpStatusFor } from "@wbtime/core";

import { toErrorOutcome } from "../dist/http/error-handler.js";
import {
  CODES_BY_HTTP_STATUS,
  FRAMEWORK_BASE_CODE_BY_STATUS,
  HTTP_STATUS_BY_CODE,
  HTTP_STATUS_CLASSES,
} from "../dist/http/status-map.js";

/** 仓库根（apps/api/tests → apps/api → apps → 根）。 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

const errorsContract = JSON.parse(
  readFileSync(join(ROOT, "contracts", "errors.json"), "utf8"),
);

const contractCodes = Object.keys(errorsContract.codes);

test("K-5 契约侧：30 个码、13 类 HTTP 状态、无 null", () => {
  assert.equal(contractCodes.length, 30, "契约错误码数量必须是 30");

  const contractStatuses = contractCodes.map((code) => errorsContract.codes[code].http_status);
  assert.ok(
    contractStatuses.every((status) => typeof status === "number"),
    "任一码的 http_status 为 null / 非数字即违规（契约无 null）",
  );
  assert.equal(new Set(contractStatuses).size, 13, "契约侧 HTTP 状态类数必须是 13");
});

test("K-5 TS 侧：30 个键、13 类值、与契约逐码相等", () => {
  const tsCodes = Object.keys(ERROR_HTTP_STATUS);

  // 空集 floor 与数量
  assert.ok(tsCodes.length > 0, "生成物映射表不得为空（空集不是 PASS）");
  assert.equal(tsCodes.length, 30, "生成表键数必须是 30");
  assert.deepEqual([...tsCodes].sort(), [...contractCodes].sort(), "码集合必须与契约全等");

  const tsStatuses = new Set(Object.values(ERROR_HTTP_STATUS));
  assert.equal(tsStatuses.size, 13, "生成表的状态取值类数必须是 13");
  assert.deepEqual(
    [...tsStatuses].sort((a, b) => a - b),
    [...new Set(contractCodes.map((code) => errorsContract.codes[code].http_status))].sort(
      (a, b) => a - b,
    ),
    "状态类集合必须与契约全等",
  );

  // 逐码相等（成员级，不只比数量）
  for (const code of contractCodes) {
    assert.equal(
      ERROR_HTTP_STATUS[code],
      errorsContract.codes[code].http_status,
      `码 ${code} 的状态与契约不一致`,
    );
  }
});

test("K-5 apps/api 派生面：13 类清单 / 反查索引 / 框架层默认码与契约一致", () => {
  assert.deepEqual(
    [...HTTP_STATUS_CLASSES],
    [...new Set(Object.values(ERROR_HTTP_STATUS))].sort((a, b) => a - b),
  );
  assert.equal(HTTP_STATUS_CLASSES.length, 13);
  assert.equal(HTTP_STATUS_BY_CODE, ERROR_HTTP_STATUS, "派生表必须是生成表的同一引用（不做二次抄写）");

  // 反查索引由同一张表翻转而来：条数与键集必须能对上，且并集覆盖全部 30 码。
  const reverseKeys = Object.keys(CODES_BY_HTTP_STATUS).map(Number).sort((a, b) => a - b);
  assert.deepEqual(reverseKeys, [...HTTP_STATUS_CLASSES]);
  const flattened = reverseKeys.flatMap((status) => CODES_BY_HTTP_STATUS[status]);
  assert.equal(flattened.length, 30, "反查索引展开后必须覆盖 30 个码");

  // 框架层默认码：与契约 reverse_map_by_http_status 逐项相等。
  // 这张表只服务「框架层没有业务码」的出口（Fastify 404/405 等），**不是** 13 类映射源
  // （契约原文：reverse_map_by_http_status 只有 6 项，不得当 13 类映射源）。
  const reverseMap = errorsContract.reverse_map_by_http_status;
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(FRAMEWORK_BASE_CODE_BY_STATUS).map(([status, code]) => [status, code]),
    ),
    reverseMap,
    "框架层默认码必须与契约 reverse_map_by_http_status 全等",
  );
});

test("K-6 契约侧：http_status_uniform=false、分布 {500:2, 503:8}、raise_site_count=10", () => {
  const entry = errorsContract.codes.DEPENDENCY_MISSING;

  assert.equal(entry.http_status, 503, "契约登记值是 503（多数值，非全量）");
  assert.equal(entry.http_status_uniform, false, "该码状态非全量成立");
  assert.deepEqual(entry.http_status_distribution, { 500: 2, 503: 8 });
  assert.equal(entry.raise_site_count, 10);
  assert.equal(entry.http_status_by_call_site_resolved.length, 10);
  assert.equal(entry.http_status_inconsistent_call_sites.length, 2, "该码的两处偏离点必须被登记");
  assert.ok(
    entry.http_status_inconsistent_call_sites.every(
      (site) => site.actual_status === 500 && site.status_origin === "domain_error_default",
    ),
    "两处 500 必须来自未传 status_code 的构造点",
  );
});

test("K-6 生成表 OR 字段保持契约值 503（参数化活在生成表之外）", () => {
  // 这一条是 gate:platform 第 ④ 项（逐码全等）的运行时对应断言：
  // 谁把生成表改成 500，这里立刻红。
  assert.equal(ERROR_HTTP_STATUS.DEPENDENCY_MISSING, 503);
  assert.equal(httpStatusFor("DEPENDENCY_MISSING"), 503);
});

test("K-6 dependencyMissing 按 call-site 取状态（503 / 500 各一例）", () => {
  const as503 = dependencyMissing("remote_tasks", 503);
  assert.equal(as503.status, 503);
  assert.equal(as503.code, "DEPENDENCY_MISSING");
  assert.deepEqual(as503.data, { capability: "remote_tasks" });
  assert.equal(typeof as503.message, "string");
  assert.ok(as503.message.length > 0, "message 必须可读非空");
  assert.ok(as503.message.includes("remote_tasks"), "message 应带上 capability 便于定位");

  const as500 = dependencyMissing("knowledge_parser", 500);
  assert.equal(as500.status, 500);
  assert.equal(as500.code, "DEPENDENCY_MISSING");
  assert.deepEqual(as500.data, { capability: "knowledge_parser" });

  // 空 capability 属调用方 bug，必须在构造期就炸，而不是落一个空的 data.capability。
  assert.throws(() => dependencyMissing("", 503), TypeError);
  assert.throws(() => dependencyMissing("   ", 500), TypeError);
});

test("K-6 参数化穿过统一错误出口后仍按 call-site 状态出壳", () => {
  const outcome503 = toErrorOutcome(dependencyMissing("remote_tasks", 503), "rid-503");
  assert.equal(outcome503.status, 503);
  assert.equal(outcome503.origin, "domain_error");
  assert.equal(outcome503.body.code, "DEPENDENCY_MISSING");
  assert.deepEqual(outcome503.body.data, { capability: "remote_tasks" });
  assert.equal(outcome503.body.request_id, "rid-503");

  // 关键反例：若出口按「表优先」，这里会被表里的 503 覆盖成 503 ⇒ 这条断言立刻红。
  const outcome500 = toErrorOutcome(dependencyMissing("knowledge_parser", 500), "rid-500");
  assert.equal(outcome500.status, 500, "显式 status=500 不得被状态表的 503 覆盖");
  assert.equal(outcome500.origin, "domain_error");
  assert.deepEqual(outcome500.body.data, { capability: "knowledge_parser" });
});

// ─────────────────────────────────────────────────────────────────────────────
// K-6 grep：生产源码零处「全局兜底」
// ─────────────────────────────────────────────────────────────────────────────

/** 生产源码扫描根：`apps/api/src` + 各 `packages/<name>/src`。 */
function collectProductionSources() {
  const roots = [join(ROOT, "apps", "api", "src")];
  for (const entry of readdirSync(join(ROOT, "packages"), { withFileTypes: true })) {
    if (entry.isDirectory()) roots.push(join(ROOT, "packages", entry.name, "src"));
  }

  const scanned = [];
  for (const root of roots) {
    let relativePaths;
    try {
      relativePaths = readdirSync(root, { recursive: true });
    } catch {
      continue; // 该包没有 src（例如纯文档包）
    }
    for (const relativePath of relativePaths) {
      const fullPath = join(root, String(relativePath));
      if (!/\.(ts|mts|cts|js|mjs)$/.test(fullPath)) continue;
      const segments = fullPath.split(/[\\/]/);
      // 排除口径（任务卡原文）：generated/ · errors.ts · tests/
      if (segments.includes("generated")) continue;
      if (segments.includes("tests")) continue;
      if (segments[segments.length - 1] === "errors.ts") continue;
      scanned.push(fullPath);
    }
  }
  return scanned;
}

test("K-6 生产源码 httpStatusFor(\"DEPENDENCY_MISSING\") 命中 0 处", () => {
  const scanned = collectProductionSources();

  // 防空转：一份都没扫到就断言「0 处命中」等于哑真。
  assert.ok(scanned.length > 20, `扫描面过小（${scanned.length} 个文件），疑似路径断链`);
  assert.ok(
    scanned.some((path) => path.endsWith(join("apps", "api", "src", "http", "status-map.ts"))),
    "扫描面必须包含 apps/api/src/http/status-map.ts",
  );

  const globalFallback = /httpStatusFor\s*\(\s*(["'`])DEPENDENCY_MISSING\1\s*\)/;
  const hits = [];
  for (const path of scanned) {
    const text = readFileSync(path, "utf8");
    if (globalFallback.test(text)) hits.push(path.slice(ROOT.length + 1));
  }

  assert.deepEqual(hits, [], `出现全局兜底（应为 0 处）: ${hits.join(", ")}`);
});
