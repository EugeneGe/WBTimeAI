#!/usr/bin/env node
/**
 * `@wbtime/api` 测试入口的**受保护 runner**（V0.2.0 审计 N-10 / N-9 同族）。
 *
 * 背景（N-10）：`apps/api` 的 `test` 原是一条裸 glob
 * `node --experimental-sqlite --test "tests/**\/*.test.mjs"` —— glob 匹配 **0 个文件**
 * 时 node 打印 `# pass 0` 并 **exit 0**（假绿）；且 `node --test` 会把「0 个子测试的
 * 文件」记成 `ok 1 - <文件路径>`（文件级通过），用例被条件注册整体跳过时
 * `# pass 1` 照样骗过只看退出码的门禁（N-9 在 legacy 腿上实抓过）。
 *
 * 判据（全部满足才 exit 0）：
 *   1. 测试文件**显式枚举**（`readdirSync` 递归展开，glob 不交给 node）；
 *   2. 文件数 ≥ 1 —— 0 文件 ⇒ exit 1；
 *   3. TAP 汇总可解析（空输出 / reporter 变更 ⇒ 红，K-11）；
 *   4. **文件级通过不算用例**（复用 `tap-runner` 的 `assertCaseLevelPass`）；
 *   5. `# fail == 0` 且 `# pass ≥ 1` —— 0 用例 ⇒ exit 1（刻意**不设**硬性用例数
 *      上界：apps/api 的用例数随版本增长，写死会脆弱；0 用例才是假绿形态）。
 *
 * 用法：
 *   node scripts/run-api-tests.mjs              （由 `apps/api` 的 `test` 调用）
 *   node scripts/run-api-tests.mjs --self-test  （runner 自身判据的红证，不起子进程）
 */

import { spawn } from "node:child_process";
import { existsSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertCaseLevelPass,
  NODE_FLAGS,
  parseTapSummary,
  REPO_ROOT,
} from "./lib/tap-runner.mjs";

/** apps/api 的测试根（递归展开 `.test.mjs`；`fixtures/` 等无 `.test.mjs` 自然跳过）。 */
const API_TESTS_DIR = path.join(REPO_ROOT, "apps", "api", "tests");

/** apps/api 的源码 / 编译产物根（N-13 陈旧检查对象）。 */
const API_SRC_DIR = path.join(REPO_ROOT, "apps", "api", "src");
const API_DIST_DIR = path.join(REPO_ROOT, "apps", "api", "dist");

// ---------------------------------------------------------------------------
// R-8 · 测试 runner 的**显式**并发上限与单文件超时（V0.3.1 · T031-05 承接）。
//
// 背景：`node --test` 缺省并发 = CPU 核数，上限不受控 ⇒ 套件一大会触发上游 429 /
// 本机资源挤兑（V0.3.0 台账 R-8）；且缺省**没有**用例超时 ⇒ 单个挂死的用例能把整条
// 套件拖到 CI 超时。故两项都以**显式 flag** 传给子进程（不是"依赖缺省值"——那等于
// 没传，node 升级改缺省就会静默漂移），可用环境变量覆盖：
//   `WBTIME_TEST_CONCURRENCY`（并发上限，正整数；缺省 4）
//   `WBTIME_TEST_TIMEOUT_MS` （单测试文件超时 ms，正整数；缺省 120000）
// 非法值**直接抛错**（fail loud），不静默回落 —— 回落会把"上限没生效"伪装成配置成功。
// ---------------------------------------------------------------------------

/** 从 env 读正整数（未设置 ⇒ 缺省；非法 ⇒ 抛错，不静默夹取）。 */
function positiveIntEnv(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw.trim() === "") return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`[api-tests] 环境变量 ${name} 必须是正整数，实测 ${JSON.stringify(raw)}`);
  }
  return value;
}

/** R-8 · 并发上限（`--test-concurrency`）。 */
export const API_TEST_CONCURRENCY = positiveIntEnv("WBTIME_TEST_CONCURRENCY", 4);

/** R-8 · 单测试文件超时（`--test-timeout`，毫秒）。 */
export const API_TEST_TIMEOUT_MS = positiveIntEnv("WBTIME_TEST_TIMEOUT_MS", 120_000);

/**
 * 组装子进程 argv（**唯一**组装点 —— self-test 靠它断言 R-8 两项 flag 恒在场）。
 *
 * @param {string[]} files 测试文件绝对路径。
 * @returns {string[]}
 */
export function buildTestArgs(files) {
  return [
    ...NODE_FLAGS,
    "--test",
    "--test-reporter=tap",
    `--test-concurrency=${API_TEST_CONCURRENCY}`,
    `--test-timeout=${API_TEST_TIMEOUT_MS}`,
    ...files,
  ];
}

/**
 * 递归枚举目录下的文件（相对路径键 + 绝对路径值，稳定排序）。
 *
 * @param {string} dir 起始目录。
 * @returns {Map<string, string>} 相对路径（`/` 分隔）→ 绝对路径。
 * @throws {Error} 目录不存在（不返回空 Map —— 静默空集就是假绿）。
 */
function listFilesRelative(dir) {
  if (!existsSync(dir) || !statSync(dir).isDirectory()) {
    throw new Error(`[api-tests] 目录不存在：${dir}`);
  }
  const files = new Map();
  const walk = (current) => {
    for (const name of readdirSync(current).sort()) {
      const full = path.join(current, name);
      if (statSync(full).isDirectory()) walk(full);
      else files.set(path.relative(dir, full).split("\\").join("/"), full);
    }
  };
  walk(dir);
  return files;
}

/**
 * N-13 · **dist 不旧于 src** 检查：测试 `import` 的是编译产物（`dist/**`），
 * 源码改了没 rebuild 时旧 dist 仍能让测试通过（stale 窗口，QA 复核记录）。
 *
 * 判据：对每个 `dist/<rel>.js`，若存在对应 `src/<rel>.ts` 且其 mtime **严格更新**
 * ⇒ 判陈旧（exit 1 并提示先 build）。映射是逐文件的 —— `tsc -b` 增量编译只重写
 * 变更过的输出，整体 mtimes 不可比；严格 `>` 是为了不吃掉同毫秒写入的边界。
 * dist 缺失 ⇒ 同样红（「先 build」是唯一出口，不静默当 0 文件处理）。
 *
 * `pnpm test` 的常规路径先跑 `tsc -b`，本检查恒绿；它保护的是**绕过 package
 * 脚本**的单文件复跑 / 直接调 runner 的场景 —— 那正是 stale 窗口的来源。
 *
 * @returns {{stale: string[], missing: boolean}} 陈旧产物列表与 dist 缺失标志。
 */
export function checkDistFreshness() {
  if (!existsSync(API_DIST_DIR)) {
    return { stale: [], missing: true };
  }
  const srcFiles = listFilesRelative(API_SRC_DIR);
  const distFiles = listFilesRelative(API_DIST_DIR);
  const stale = [];
  for (const [rel, fullPath] of distFiles) {
    if (!rel.endsWith(".js")) continue;
    const srcRel = rel.slice(0, -3) + ".ts";
    const srcPath = srcFiles.get(srcRel);
    if (srcPath === undefined) continue; // 无对应源文件（生成的产物）—— 不参与判定
    if (statSync(srcPath).mtimeMs > statSync(fullPath).mtimeMs) {
      stale.push(rel);
    }
  }
  return { stale, missing: false };
}

/**
 * 递归枚举 `apps/api/tests` 下的 `.test.mjs`（显式绝对路径，按名称排序保证稳定）。
 *
 * @param {string} dir 起始目录。
 * @returns {string[]} 绝对路径列表。
 * @throws {Error} 目录不存在（不返回空数组 —— 静默空集就是假绿）。
 */
export function listApiTestFiles(dir = API_TESTS_DIR) {
  if (!existsSync(dir) || !statSync(dir).isDirectory()) {
    throw new Error(`[api-tests] 测试目录不存在：${dir}`);
  }
  const files = [];
  const walk = (current) => {
    for (const name of readdirSync(current).sort()) {
      const full = path.join(current, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name.endsWith(".test.mjs")) files.push(full);
    }
  };
  walk(dir);
  return files;
}

/**
 * 执行受保护的 api 测试套件（`--self-test` 复用其判据函数）。
 *
 * @param {{files?: string[]}} [options] `files` 缺省时自行枚举（self-test 注入构造值）。
 * @returns {Promise<number>} 退出码（0 = 达标）。
 */
export async function runApiTests(options = {}) {
  const prefix = "[api-tests]";

  // ⓪ N-13 陈旧检查：dist 必须不旧于 src（绕过 `tsc -b` 的直跑场景是 stale 窗口）。
  if (options.skipFreshnessCheck !== true) {
    const freshness = checkDistFreshness();
    if (freshness.missing) {
      process.stderr.write(
        `${prefix} FAIL: apps/api/dist 不存在 —— 测试 import 的是编译产物，请先 build` +
          `（pnpm --filter @wbtime/api build，或直接跑 pnpm --filter @wbtime/api test）—— N-13\n`,
      );
      return 1;
    }
    if (freshness.stale.length > 0) {
      process.stderr.write(
        `${prefix} FAIL: dist 落后于 src（改了源码没 rebuild，测试会拿旧产物跑出假结果 —— N-13）：\n` +
          freshness.stale.map((rel) => `  - dist/${rel}\n`).join("") +
          `请先 build：pnpm --filter @wbtime/api build\n`,
      );
      return 1;
    }
  }

  // ① 显式枚举（glob 永远不交给 node）。
  const files = options.files ?? listApiTestFiles();
  if (files.length === 0) {
    process.stderr.write(
      `${prefix} FAIL: tests 下没有匹配到任何 *.test.mjs（0 文件 = 0 用例，绝不能算绿 —— N-10）\n`,
    );
    return 1;
  }

  process.stdout.write(`${prefix} files(${files.length}):\n` + files.map((file) => `  - ${path.relative(REPO_ROOT, file)}\n`).join(""));

  // ② 真跑：固定 TAP reporter + `--experimental-sqlite`（夹具用 node:sqlite）
  //    + R-8 的显式并发上限与单文件超时（`buildTestArgs` 是唯一组装点）。
  const child = spawn(process.execPath, buildTestArgs(files), {
    cwd: REPO_ROOT,
    env: { ...process.env },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
    process.stdout.write(chunk);
  });
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => process.stderr.write(chunk));
  const exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => resolve(code === null ? 1 : code));
  });

  // ③ 判据链：可解析 → 非文件级通过 → fail=0 → pass≥1 → 子进程 exit 0。
  const summary = parseTapSummary(stdout);
  if (!summary.parsed) {
    process.stderr.write(`${prefix} FAIL: 无法从 TAP 输出解析出汇总（空汇总 / reporter 变更 = 假绿，K-11）\n`);
    return 1;
  }
  try {
    assertCaseLevelPass(stdout);
  } catch (error) {
    process.stderr.write(`${prefix} FAIL: ${error.message}\n`);
    return 1;
  }
  if ((summary.fail ?? 0) !== 0) {
    process.stderr.write(`${prefix} FAIL: fail=${summary.fail}（要求 0）⇒ 子进程 exit=${exitCode}\n`);
    return 1;
  }
  if ((summary.pass ?? 0) < 1) {
    process.stderr.write(`${prefix} FAIL: pass=${summary.pass}（0 用例 = 假绿，N-10 判据）\n`);
    return 1;
  }
  if (exitCode !== 0) {
    process.stderr.write(`${prefix} FAIL: 汇总达标但子进程 exit=${exitCode}\n`);
    return 1;
  }

  process.stdout.write(
    `${prefix} OK ✅ files=${files.length} tests=${summary.tests} pass=${summary.pass} fail=${summary.fail}\n`,
  );
  return 0;
}

/** `--self-test`：runner 自身判据的红证（构造 TAP 文本，不起子进程）。 */
async function selfTest() {
  const checks = [];
  const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

  // ① 0 文件必须红。
  const emptyCode = await runApiTests({ files: [] });
  check("0 文件必须 exit 1", emptyCode === 1, `实测 ${emptyCode}`);

  // ①'' R-8：并发上限与超时必须**显式**出现在子进程 argv 里（缺了 = 上限不受控）。
  const args = buildTestArgs(["x.test.mjs"]);
  check(
    "并发上限与超时必须显式传递（R-8）",
    args.includes(`--test-concurrency=${API_TEST_CONCURRENCY}`) &&
      args.includes(`--test-timeout=${API_TEST_TIMEOUT_MS}`),
    `实测 argv 含 concurrency=${args.includes(`--test-concurrency=${API_TEST_CONCURRENCY}`)} timeout=${args.includes(`--test-timeout=${API_TEST_TIMEOUT_MS}`)}`,
  );

  // ①' N-13：dist 缺失必须红 / dist 存在时陈旧清单可解析。
  const freshness = checkDistFreshness();
  if (freshness.missing) {
    const missingCode = await runApiTests({ files: ["nonexistent.probe.mjs"], skipFreshnessCheck: false });
    check("dist 缺失必须 exit 1", missingCode === 1, `实测 ${missingCode}`);
  } else {
    check("dist 存在时陈旧清单可解析", Array.isArray(freshness.stale));
  }

  // ② 文件级通过（N-9 形态）必须红 —— 复用 tap-runner 判据。
  let fileLevelThrew = null;
  try {
    assertCaseLevelPass(
      [
        "TAP version 13",
        "ok 1 - D:////WBT////WBTimeAI////apps////api////tests////x.test.mjs",
        "1..1",
        "# pass 1",
        "# fail 0",
      ].join("\n"),
    );
  } catch (error) {
    fileLevelThrew = error instanceof Error ? error.message : String(error);
  }
  check("文件级通过必须判红", fileLevelThrew !== null, fileLevelThrew ?? "未抛错");

  // ③ 0 用例（pass=0）必须红：parseTapSummary + pass<1 判据。
  const zero = parseTapSummary(["1..1", "# tests 1", "# pass 0", "# fail 0"].join("\n"));
  check("pass=0 必须被判据拒绝", zero.parsed === true && zero.pass === 0);

  // ④ 真实用例形态不得误伤。
  const named = parseTapSummary(["1..1", "# tests 1", "# pass 1", "# fail 0"].join("\n"));
  check("具名用例 + pass≥1 不得误伤", named.parsed === true && named.pass === 1);

  for (const item of checks) {
    process.stdout.write(`  ${item.ok ? "ok  " : "FAIL"} ${item.name}${item.ok ? "" : `  ← ${item.detail}`}\n`);
  }
  const failed = checks.filter((item) => !item.ok);
  process.stdout.write(
    `[api-tests self-test] ${failed.length === 0 ? "PASS" : "FAIL"} ${checks.length - failed.length}/${checks.length}\n`,
  );
  process.exitCode = failed.length === 0 ? 0 : 1;
}

if (process.argv.slice(2).includes("--self-test")) {
  selfTest().catch((error) => {
    process.stderr.write(`[api-tests self-test] FAIL: ${error.message}\n`);
    process.exitCode = 1;
  });
} else {
  try {
    process.exitCode = await runApiTests();
  } catch (error) {
    process.stderr.write(`[api-tests] FAIL: ${error.message}\n`);
    process.exitCode = 1;
  }
}
