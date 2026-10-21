/**
 * M-04 · `scanSensitive` 等价性证明（node:test，零依赖）。
 *
 * 判据口径（**已降级，见 T2-01 施工记录 D-1**）
 * ------------------------------------------------
 * 计划 §6 原文的 M-04 判据是「① 同一引用 `plugin.scanSensitive ===
 * security.scanSensitive` + ② 8 fixture 两侧全等」。但本仓 V0.1.0 **只迁入 9 个包，
 * `packages/plugin` 不存在**（实测 `ls packages/`），因此「同一引用」这一半本版无法落地。
 * 经主理人裁定，J-9 降级为 **security 侧单侧断言**：
 *
 * 1. **8 fixture**（4 命中 / 4 不命中）× `{是否抛, findings 的 path+reason 序列, count}`
 *    逐条断言 —— 这是「行为」那一半；
 * 2. **常量与 py 源码逐项对齐** —— 9 个敏感键 pattern / 5 条 token 值 pattern /
 *    高熵阈值 20 + 4.2 / 12 个占位 marker / 3 个引用前缀 / 递归深度 200。
 *
 * ⚠️ 期望值不是手写的
 * -------------------
 * 本文件里所有期望值都来自 `tests/golden/scan-sensitive.py-golden.json` —— 那个文件是
 * **py 线 `scan_sensitive` 真跑这 8 个 fixture 的输出**（用 `D:/WBT/WBTimeAI_old/.venv`
 * 的解释器生成，溯源与重放命令写在 golden 的 `source` / `regenerate` 字段里）。
 *
 * 为什么要绕这一道：如果期望值由本文件作者手写，那"TS 与 py 等价"就退化成
 * "TS 与作者的理解等价"——而作者的理解正是最可能出错的一环（例如把"数组里的标量
 * 不扫描"这条上游怪癖当成 bug 顺手修掉）。拿 py 的输出当基准，这条退化路径才被堵死。
 *
 * 驱动：`node --test`，无外部依赖。被测对象是**编译产物** `dist/`（与 `package.json`
 * 的 `main/types` 同一入口），故先 `tsc -b` 再跑测试 —— 测 dist 而不是测源码，
 * 才能同时证明「构建后的导出面」就是判据面。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  HIGH_ENTROPY_MIN_LENGTH,
  HIGH_ENTROPY_THRESHOLD,
  MAX_FINDINGS,
  MAX_SCAN_DEPTH,
  PLACEHOLDER_MARKERS,
  REFERENCE_PREFIXES,
  SENSITIVE_KEY_PATTERN,
  TOKEN_VALUE_PATTERNS,
  scanSensitive,
} from "../dist/index.js";

const GOLDEN_PATH = fileURLToPath(
  new URL("./golden/scan-sensitive.py-golden.json", import.meta.url)
);
const GOLDEN = JSON.parse(readFileSync(GOLDEN_PATH, "utf8"));

// ---------------------------------------------------------------------------
// 输入（夹具本体）：与 golden 的 8 个 id 一一对应
// ---------------------------------------------------------------------------

/**
 * 8 条输入，4 命中 / 4 不命中 —— 与计划 §6 的点名清单逐条对应。
 * **只放输入**：期望值一律从 golden 取，避免"输入期望同源"制造循环论证。
 *
 * @type {Readonly<Record<string, unknown>>}
 */
const PAYLOADS = Object.freeze({
  // ---- 4 命中 ------------------------------------------------------------
  // 嵌套 + 数组下标：同时验证 path 拼接口径 `providers[0].api_key`
  "hit-sk-prefix": { providers: [{ api_key: "sk-abc123DEF456ghi789JKL012" }] },
  "hit-akia": { credentials: { aws_access_key_id: "AKIAZZ7Q3XK9LMN4P2RT" } },
  // 键名不敏感（header）⇒ 只能是 high-entropy，用来锁住「不是靠键名蒙对」
  "hit-high-entropy": { models: [{ name: "x", header: "Zx9Qw3Lp7Rt1Yb5Nc8Vf2Hk6Md4Sg0Ja" }] },
  // 低熵 + 短于 20 ⇒ 前两道闸门都不命中，只能由「敏感键名 + 明文」兜住
  "hit-sensitive-key": { database: { password: "hunter2hunter2" } },

  // ---- 4 不命中 ----------------------------------------------------------
  "miss-change-me": { api_key: "change-me" },
  // 长度 18 ≥ 8 且键名命中 SENSITIVE_KEY_PATTERN ⇒ 若不先判占位符就会误报
  "miss-example": { secret: "example-value-1234" },
  // 引用形值：指向别处的引用不是明文
  "miss-credential-ref": { password: "credential:prod-db-password" },
  // 中文描述：长度 ≥ 20 但字符集闸门直接失败（`^[A-Za-z0-9+/=_-]+$`）
  "miss-chinese-prose": { description: "这是一个用于描述模型供应商身份的纯中文说明文本" },
});

/**
 * 把一次调用的结果压成可逐条比对的形状。
 *
 * @param {unknown} payload
 * @param {{ path?: string }} [opts]
 * @returns {{ threw: boolean; findings: { path: string; reason: string }[]; count: number | null; code: string | null; error: unknown }}
 */
function observe(payload, opts = {}) {
  try {
    scanSensitive(payload, opts);
    return { threw: false, findings: [], count: null, code: null, error: null };
  } catch (error) {
    const data = /** @type {{ data?: { findings?: unknown; count?: unknown } }} */ (error).data;
    const rawFindings = Array.isArray(data?.findings) ? data.findings : [];
    return {
      threw: true,
      findings: rawFindings.map((item) => ({
        path: String(/** @type {Record<string, unknown>} */ (item).path),
        reason: String(/** @type {Record<string, unknown>} */ (item).reason),
      })),
      count: typeof data?.count === "number" ? data.count : null,
      code: typeof /** @type {{ code?: unknown }} */ (error).code === "string"
        ? /** @type {{ code: string }} */ (error).code
        : null,
      error,
    };
  }
}

// ---------------------------------------------------------------------------
// 1. 8 fixture 逐条对齐 py 真跑结果
// ---------------------------------------------------------------------------

test("J-9（降级口径）· 8 fixture × {是否抛, findings 的 path+reason 序列, count} 与 py 输出逐条全等", () => {
  // 夹具与基准必须一一对应：少一条、多一条都判红（防止"删掉不通过的夹具"式作弊）
  assert.equal(GOLDEN.fixtures.length, 8, "golden 必须恰好 8 条 fixture");
  assert.deepEqual(
    GOLDEN.fixtures.map((item) => item.id).sort(),
    Object.keys(PAYLOADS).sort(),
    "golden 的 fixture id 集合必须与测试里的输入集合全等"
  );
  assert.equal(
    GOLDEN.fixtures.filter((item) => item.threw).length,
    4,
    "命中夹具必须 4 条（计划 §6 点名 4 命中）"
  );
  assert.equal(
    GOLDEN.fixtures.filter((item) => !item.threw).length,
    4,
    "不命中夹具必须 4 条（计划 §6 点名 4 不命中）"
  );

  for (const expected of GOLDEN.fixtures) {
    const payload = PAYLOADS[expected.id];
    const actual = observe(payload);

    assert.equal(
      actual.threw,
      expected.threw,
      `[${expected.id}] 是否抛错不符：py=${expected.threw}，ts=${actual.threw}`
    );
    assert.deepEqual(
      actual.findings,
      expected.findings,
      `[${expected.id}] findings 的 path+reason 序列与 py 不符`
    );
    assert.equal(actual.count, expected.count, `[${expected.id}] count 与 py 不符`);
    if (expected.code !== undefined) {
      assert.equal(actual.code, expected.code, `[${expected.id}] code 与 py 不符`);
    }
  }
});

test("命中错误是 DomainError(VALIDATION_ERROR)，data 只有 findings + count", () => {
  const { error } = observe(PAYLOADS["hit-sk-prefix"]);
  assert.ok(error instanceof Error, "必须抛 Error 子类");
  assert.equal(/** @type {{ code?: string }} */ (error).code, "VALIDATION_ERROR");
  assert.equal(/** @type {{ name?: string }} */ (error).name, "DomainError");

  const data = /** @type {Record<string, unknown>} */ (
    /** @type {{ data?: unknown }} */ (error).data
  );
  assert.deepEqual(
    Object.keys(data).sort(),
    ["count", "findings"],
    "data 键集合必须恰为 {findings,count}"
  );
  assert.equal(
    Object.hasOwn(data, "entropy"),
    false,
    "entropy 不得进 data —— py 4.2 与 JS 4.2 序列化不同，会把 findings 的逐字节比对弄坏"
  );
});

test("不回显原文明文：message 与 data 的 JSON 里都不得出现命中值", () => {
  for (const expected of GOLDEN.fixtures.filter((item) => item.threw)) {
    const { error } = observe(PAYLOADS[expected.id]);
    const secret = firstScalar(PAYLOADS[expected.id]);
    const serialized = JSON.stringify({
      message: /** @type {{ message?: string }} */ (error).message,
      data: /** @type {{ data?: unknown }} */ (error).data,
      asString: String(error),
    });
    assert.equal(
      serialized.includes(secret),
      false,
      `[${expected.id}] 错误体泄漏了明文：${secret}`
    );
  }
});

/**
 * 取夹具里的第一个标量（命中夹具都是单标量，用来做泄漏断言）。
 *
 * @param {unknown} node
 * @returns {string}
 */
function firstScalar(node) {
  if (node === null || typeof node !== "object") return String(node);
  for (const value of Object.values(node)) {
    const found = firstScalar(value);
    if (found !== "undefined") return found;
  }
  return "undefined";
}

test("findings 截断到 20 条，count 仍是真实总数（25）", () => {
  /** @type {Record<string, string>} */
  const payload = {};
  for (let index = 0; index < 25; index += 1) {
    payload[`key_${index}`] = `sk-${String(index).padStart(2, "0")}abcdefghijklmnopqrstu`;
  }
  const { error, findings, count } = observe(payload);
  assert.ok(error, "25 条命中必须抛错");
  assert.equal(findings.length, MAX_FINDINGS, `findings 必须截断到 ${MAX_FINDINGS} 条`);
  assert.equal(count, 25, "count 是真实总数，不是截断后的条数");
});

test("超过深度上限 200 ⇒ VALIDATION_ERROR + reason=too_deep（不是 RangeError），与 py 同形", () => {
  let deep = { leaf: "sk-abc123DEF456ghi789JKL012" };
  for (let index = 0; index <= MAX_SCAN_DEPTH + 5; index += 1) deep = { nested: deep };

  const { error } = observe(deep);
  assert.ok(error instanceof Error, "超深嵌套必须抛领域错误");
  assert.equal(
    error instanceof RangeError,
    false,
    "不得泄漏裸 RangeError（Maximum call stack size exceeded）"
  );
  assert.equal(/** @type {{ code?: string }} */ (error).code, "VALIDATION_ERROR");
  const data = /** @type {{ data?: Record<string, unknown> }} */ (error).data;
  assert.equal(
    data?.reason,
    GOLDEN.too_deep.data.reason,
    "too_deep 的 reason 必须与 py 一致"
  );
  assert.equal(
    data?.limit,
    GOLDEN.too_deep.data.limit,
    "too_deep 的 limit 必须与 py 一致"
  );
  assert.equal(Object.hasOwn(data ?? {}, "findings"), false, "too_deep 分支不带 findings");
});

test("path 选项作为 finding 前缀（多段扫描定位用）", () => {
  const { findings } = observe(
    { api_key: "sk-abc123DEF456ghi789JKL012" },
    { path: "packages[2]" }
  );
  assert.deepEqual(findings, [{ path: "packages[2].api_key", reason: "token-prefix" }]);
});

test("判定顺序：token 前缀优先于键名，高熵优先于键名", () => {
  // 键名敏感 + 值命中 token 前缀 ⇒ 记 token-prefix（不是 sensitive-key）
  assert.deepEqual(observe({ api_key: "sk-abc123DEF456ghi789JKL012" }).findings, [
    { path: "api_key", reason: "token-prefix" },
  ]);
  // 键名敏感 + 高熵值 ⇒ 记 high-entropy
  assert.deepEqual(observe({ api_key: "Zx9Qw3Lp7Rt1Yb5Nc8Vf2Hk6Md4Sg0Ja" }).findings, [
    { path: "api_key", reason: "high-entropy" },
  ]);
  // 敏感键名 + 长度 < 8 ⇒ 不报（`len(value) >= 8` 闸门）
  assert.deepEqual(observe({ password: "short" }).findings, []);
});

test("继承口径：数组里的**标量**不判定（py `_walk` 对 list 只下钻）", () => {
  // 上游语义如此，等价性判据要求逐条相同 ⇒ 这里把「不报」钉成断言，防止被"顺手补全"
  assert.deepEqual(observe({ keys: ["sk-abc123DEF456ghi789JKL012"] }).findings, []);
  // 但数组里的**映射**其标量值必须判定
  assert.deepEqual(observe({ keys: [{ api_key: "sk-abc123DEF456ghi789JKL012" }] }).findings, [
    { path: "keys[0].api_key", reason: "token-prefix" },
  ]);
});

// ---------------------------------------------------------------------------
// 2. 常量对齐：与 py 源码逐项比（「同一个扫描器」的另一半）
// ---------------------------------------------------------------------------

test("SENSITIVE_KEY_PATTERN 的 source 与 py 逐字相同，且忽略大小写", () => {
  assert.equal(
    SENSITIVE_KEY_PATTERN.source,
    GOLDEN.constants.sensitive_key_source,
    "敏感键名 pattern 的 source 必须与 py 逐字相同"
  );
  assert.equal(
    GOLDEN.constants.sensitive_key_ignore_case,
    true,
    "py 侧基准自身必须是 IGNORECASE 的（否则基准失真）"
  );
  assert.ok(
    SENSITIVE_KEY_PATTERN.flags.includes("i"),
    "TS 侧必须同样忽略大小写"
  );

  // 行为断言：9 类键名都命中（避免「source 相同但正则引擎行为不同」）
  for (const key of [
    "secret",
    "token",
    "password",
    "passwd",
    "pwd",
    "api_key",
    "apikey",
    "api-key",
    "access_key",
    "private_key",
    "privatekey",
    "credential",
    "client_SECRET",
    "X-Api-Key",
    "ACCESS-KEY",
    "PRIVATE_KEY",
    "DB_PASSWORD",
  ]) {
    assert.equal(SENSITIVE_KEY_PATTERN.test(key), true, `敏感键名未命中：${key}`);
  }
  for (const key of ["username", "description", "display_name", "url", "model"]) {
    assert.equal(SENSITIVE_KEY_PATTERN.test(key), false, `非敏感键名被误判：${key}`);
  }
});

test("TOKEN_VALUE_PATTERNS 恰 5 条，source 与 py 逐字相同，且各能命中目标形态", () => {
  assert.equal(TOKEN_VALUE_PATTERNS.length, 5, "token 值 pattern 必须恰 5 条");
  assert.deepEqual(
    TOKEN_VALUE_PATTERNS.map((pattern) => pattern.source),
    GOLDEN.constants.token_sources,
    "5 条 pattern 的 source 必须与 py 源码逐字相同"
  );

  assert.equal(TOKEN_VALUE_PATTERNS[0].test("sk-" + "a".repeat(20)), true);
  for (const prefix of ["ghp_", "gho_", "ghs_", "ghu_", "ghr_"]) {
    assert.equal(TOKEN_VALUE_PATTERNS[1].test(prefix + "a".repeat(20)), true, prefix);
  }
  assert.equal(TOKEN_VALUE_PATTERNS[2].test("AKIA" + "A1".repeat(8)), true);
  for (const prefix of ["xoxb-", "xoxa-", "xoxp-", "xoxr-", "xoxs-"]) {
    assert.equal(TOKEN_VALUE_PATTERNS[3].test(prefix + "1".repeat(10)), true, prefix);
  }
  assert.equal(TOKEN_VALUE_PATTERNS[4].test("-----BEGIN RSA PRIVATE KEY-----"), true);
  assert.equal(TOKEN_VALUE_PATTERNS[4].test("-----BEGIN PRIVATE KEY-----"), true);
  assert.equal(TOKEN_VALUE_PATTERNS[4].test("-----BEGIN OPENSSH PRIVATE KEY-----"), true);
  assert.equal(TOKEN_VALUE_PATTERNS[4].test("-----BEGIN EC PRIVATE KEY-----"), true);
});

test("高熵阈值 / 递归上限 / 截断上限 / 占位符 / 引用前缀 与 py 原值一致", () => {
  assert.equal(HIGH_ENTROPY_MIN_LENGTH, GOLDEN.constants.high_entropy_min_len);
  assert.equal(HIGH_ENTROPY_THRESHOLD, GOLDEN.constants.high_entropy_threshold);
  assert.equal(MAX_SCAN_DEPTH, GOLDEN.constants.max_scan_depth);
  assert.equal(MAX_FINDINGS, 20, "findings 截断上限（py `findings[:20]`）");
  assert.equal(GOLDEN.constants.placeholder_markers.length, 12, "py 侧占位符必须 12 个");

  assert.deepEqual(
    [...PLACEHOLDER_MARKERS],
    GOLDEN.constants.placeholder_markers,
    "占位符必须与 py 的 12 个 marker 逐项相同且顺序一致"
  );
  assert.deepEqual(
    [...REFERENCE_PREFIXES],
    GOLDEN.constants.reference_prefixes,
    "引用前缀必须与 py 的 3 条逐项相同"
  );
});

test("引用前缀三条全部生效（含 $ref: 与 secret:），且 trim 后比较", () => {
  for (const prefix of REFERENCE_PREFIXES) {
    assert.deepEqual(
      observe({ password: `${prefix}vault/path` }).findings,
      [],
      `${prefix} 应视为引用`
    );
    assert.deepEqual(observe({ password: `  ${prefix}vault/path  ` }).findings, []);
  }
});

test("空值与标量入参不报错（py：非映射/非序列即无 findings）", () => {
  for (const payload of [
    null,
    undefined,
    0,
    1.5,
    true,
    false,
    "",
    "sk-abc123DEF456ghi789JKL012",
    [],
    {},
  ]) {
    assert.deepEqual(observe(payload).findings, [], `标量/空结构不应命中：${String(payload)}`);
  }
});
