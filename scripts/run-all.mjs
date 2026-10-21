#!/usr/bin/env node
/**
 * `pnpm test:all` —— **这个包的全部测试**（四组，名字与覆盖面必须一致）。
 *
 * | # | 组 | 目录/文件 | 下界 | 前置 |
 * |---|---|---|---|---|
 * | 1 | `legacy:forward` | `tests/e2e` | ≥4 | 本机 py 环境 |
 * | 2 | `legacy:reverse` | `tests/reverse` | ≥1 | 本机 py 环境 |
 * | 3 | `run-smoke` | `tests/ts-backend` | ≥4 | `apps/api/dist` 已构建 |
 * | 4 | `run-conformance` | `tests/conformance/tenant-404.cases.mjs` | ≥11 | 自动注入夹具 |
 *
 * 为什么必须四组都在（V0.2.0 审计 #3 的核心教训）：
 * 本版此前的 `test:all` 是一条 `node --test "tests/**\/*.test.mjs"` ——
 *   * `.cases.mjs` **不匹配**该 glob ⇒ conformance 从来没被执行过；
 *   * 而 glob 一旦 0 匹配，node 打印 `# pass 0 / # fail 0` 并 **exit 0**（假绿）。
 * 团队裁定：`test:all` 这个名字必须等于「全部测试」。所以这里**逐组独立断言执行数**，
 * 任何一组不足下界即红 —— 覆盖面缩水不可能再伪装成绿。
 *
 * 组定义（含 `minPass`）的唯一来源：`scripts/lib/suites.mjs` 的 `ALL_GROUPS`。
 * 改任一组用例数，必须同步改那张表（刻意的摩擦）。
 *
 * 用法：
 *   `node scripts/run-all.mjs`              等价于包内 `pnpm test:all`
 *   `node scripts/run-all.mjs --self-test`  只跑**runner 自身的红证**（不起任何子进程）
 *
 * 退出码：四组全达标 0；任一组红 1；`--self-test` 任一条不成立 1。
 */

import { ALL_GROUPS, CONFORMANCE_ENV, LEGACY_FORWARD, LEGACY_REVERSE, resolveGroup } from "./lib/suites.mjs";
import { assertCaseLevelPass, runTapSuite } from "./lib/tap-runner.mjs";

// ─────────────────────────────────────────────────────────────────────────────
// `--self-test`：runner 自身的红证（不起子进程，秒级）
// ─────────────────────────────────────────────────────────────────────────────
//
// 为什么需要它：runner 的全部价值是"假绿会红"。可这个性质本身没有单测就会退化 ——
// 于是这里用**构造出来的 TAP 文本**直接证明判据会红/会绿，并把 2026-10-21 QA 抓到的
// `legacy:reverse` 幽灵绿（漏传 `E2E_LEG` ⇒ 0 用例 ⇒ 文件级 ok）钉成回归断言。

/** 构造一份「只有文件级 ok」的 TAP（幽灵绿的形态）。 */
const FILE_LEVEL_ONLY_TAP = [
  "TAP version 13",
  "ok 1 - D:////WBT////WBTimeAI////packages////e2e////tests////reverse////reverse.test.mjs",
  "  ---",
  "  duration_ms: 208.2079",
  "  ...",
  "1..1",
  "# tests 1",
  "# pass 1",
  "# fail 0",
].join("\n");

/** 构造一份「有具名用例」的 TAP（正常形态）。 */
const NAMED_CASE_TAP = [
  "TAP version 13",
  "ok 1 - case-r-reverse-refused",
  "  ---",
  "  duration_ms: 6045.1",
  "  ...",
  "1..1",
  "# tests 1",
  "# pass 1",
  "# fail 0",
].join("\n");

/** 构造一份「文件 + 具名用例混合」的 TAP（不该误伤）。 */
const MIXED_TAP = [
  "TAP version 13",
  "ok 1 - D:////a////b////c.test.mjs",
  "ok 2 - case-x-real",
  "1..2",
  "# tests 2",
  "# pass 2",
  "# fail 0",
].join("\n");

/** 构造一份「用例名里带 .mjs 但没有路径分隔符」的 TAP（判据不该靠命名约定）。 */
const DOTTED_NAME_TAP = ["TAP version 13", "ok 1 - foo.test.mjs", "1..1", "# pass 1", "# fail 0"].join("\n");

/**
 * 跑 runner 的红证。
 *
 * @returns {number} 0 = 全部成立；1 = 有断言不成立。
 */
function selfTest() {
  const checks = [];

  /** 记录一条断言。 */
  const check = (name, condition, detail = "") => {
    checks.push({ name, ok: Boolean(condition), detail });
  };

  // ① 幽灵绿形态必须红
  let threw = null;
  try {
    assertCaseLevelPass(FILE_LEVEL_ONLY_TAP);
  } catch (error) {
    threw = error instanceof Error ? error.message : String(error);
  }
  check("文件级通过必须判红", threw !== null, threw ?? "未抛错（判据失效）");
  check(
    "错误文案必须点明原因",
    threw !== null && threw.includes("文件级通过不算用例"),
    threw ?? "",
  );

  // ② 具名用例必须绿
  let namedThrew = null;
  try {
    assertCaseLevelPass(NAMED_CASE_TAP);
  } catch (error) {
    namedThrew = error instanceof Error ? error.message : String(error);
  }
  check("具名用例不得误伤", namedThrew === null, namedThrew ?? "");

  // ③ 混合形态不得误伤（只要有一条真用例就放行）
  let mixedThrew = null;
  try {
    assertCaseLevelPass(MIXED_TAP);
  } catch (error) {
    mixedThrew = error instanceof Error ? error.message : String(error);
  }
  check("混合形态不得误伤", mixedThrew === null, mixedThrew ?? "");

  // ④ 用例名带 `.mjs` 但无分隔符 ⇒ 视为用例名（不是文件）
  let dottedThrew = null;
  try {
    assertCaseLevelPass(DOTTED_NAME_TAP);
  } catch (error) {
    dottedThrew = error instanceof Error ? error.message : String(error);
  }
  check("`foo.test.mjs` 形态的用例名不得判成文件", dottedThrew === null, dottedThrew ?? "");

  // ⑤ **P1 回归守卫**：两条 legacy 腿必须各自带正确的 `E2E_LEG`
  check(
    "LEGACY_FORWARD 必须显式带 E2E_LEG=forward",
    LEGACY_FORWARD.env?.E2E_LEG === "forward",
    `实测 ${JSON.stringify(LEGACY_FORWARD.env)}`,
  );
  check(
    "LEGACY_REVERSE 必须显式带 E2E_LEG=reverse",
    LEGACY_REVERSE.env?.E2E_LEG === "reverse",
    `实测 ${JSON.stringify(LEGACY_REVERSE.env)}`,
  );
  // ⑥ 并且这个 env 要真的进到「子进程 env 规格」里（不是只写在常量上）
  check(
    "resolveGroup 必须把 E2E_LEG 带进子进程 env",
    resolveGroup(LEGACY_REVERSE).env?.E2E_LEG === "reverse",
    `实测 ${JSON.stringify(resolveGroup(LEGACY_REVERSE).env)}`,
  );

  for (const item of checks) {
    process.stdout.write(`  ${item.ok ? "ok  " : "FAIL"} ${item.name}${item.ok ? "" : `  ← ${item.detail}`}\n`);
  }
  const failed = checks.filter((item) => !item.ok);
  process.stdout.write(
    `[self-test] ${failed.length === 0 ? "PASS" : "FAIL"} ${checks.length - failed.length}/${checks.length}\n`,
  );
  return failed.length === 0 ? 0 : 1;
}

if (process.argv.slice(2).includes("--self-test")) {
  process.exitCode = selfTest();
} else {

process.stdout.write(
  `[test:all] 覆盖率声明：${ALL_GROUPS.length} 组 —— ` +
    `${ALL_GROUPS.map((group) => `${group.key}(≥${group.minPass})`).join(" + ")}\n`
);

/** 每组的结果（用于末尾汇总表；这样"哪一组跑了多少"在日志里可核）。 */
const results = [];

for (const group of ALL_GROUPS) {
  /** `runTapSuite` 解析出的 TAP 汇总（失败时可能仍是 null）。 */
  let summary = null;
  let code = 1;
  try {
    const suite = resolveGroup(group);
    if (group.harness !== undefined) {
      process.stdout.write(`[${group.label}] harness=${suite.env[CONFORMANCE_ENV]}\n`);
    }
    code = await runTapSuite({ ...suite, onSummary: (parsed) => { summary = parsed; } });
  } catch (error) {
    process.stderr.write(`[${group.label}] FAIL: ${error.message}\n`);
    code = 1;
  }
  results.push({
    key: group.key,
    label: group.label,
    minPass: group.minPass,
    pass: summary === null ? null : summary.pass,
    fail: summary === null ? null : summary.fail,
    tests: summary === null ? null : summary.tests,
    ok: code === 0,
  });
}

const totalPass = results.reduce((sum, item) => sum + (item.pass ?? 0), 0);
const totalFail = results.reduce((sum, item) => sum + (item.fail ?? 0), 0);
const passedGroups = results.filter((item) => item.ok).length;

// ── 汇总表（逐组 pass 数 + 总 exit，验收要的就是这张表）─────────────────────
process.stdout.write("\n[test:all] ================= 汇总 =================\n");
for (const item of results) {
  process.stdout.write(
    `[test:all] ${item.ok ? "OK  " : "FAIL"} ${item.key.padEnd(16)} ` +
      `pass=${String(item.pass).padEnd(4)} fail=${String(item.fail).padEnd(4)} ` +
      `(minPass=${item.minPass})\n`
  );
}
process.stdout.write(
  `[test:all] TOTAL pass=${totalPass} fail=${totalFail} ` +
    `groups=${passedGroups}/${results.length}\n`
);
const ok = passedGroups === results.length && totalFail === 0;
process.stdout.write(`[test:all] ${ok ? "PASS ✅ 四组全部达标" : "FAIL ❌ 有组未达标"}\n`);
process.exitCode = ok ? 0 : 1;
}
