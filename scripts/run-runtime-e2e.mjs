#!/usr/bin/env node
/**
 * T3-14 · 运行时 e2e 的**受保护 runner**（同 `run-api-tests.mjs` 的 N-10 纪律）。
 *
 * 为什么不能直接 `node --test packages/e2e/tests/runtime`：
 *   1. 卡面把三个文件命名为 `*.mjs`（不是 `*.test.mjs`），`node --test` 的默认匹配
 *      不认它们 —— 一条 glob 匹配 0 文件时 node 打印 `# pass 0` 并 **exit 0**（假绿）；
 *   2. 三个文件各自是**独立脚本**（每个自己 `before/after` 起停服务），要逐个跑、
 *      逐个判退出码，才能区分"哪个文件红了"。
 *
 * 判据（全部满足才 exit 0）：
 *   ① 三个文件**显式枚举**（不靠 glob）；文件不存在 ⇒ exit 1（不是跳过）；
 *   ② 每个文件单独 `spawn`，**逐个**收退出码；
 *   ③ 任一文件 rc≠0 ⇒ 整体 exit 1，并在汇总里点名；
 *   ④ 每个文件的 stdout 里必须出现 `# pass N`（N ≥ 1）且 **没有** `# fail` > 0
 *      —— 只判 rc 会把"0 用例 exit 0"放过去；
 *   ⑤ 汇总打印 `files/pass/fail` 三数（给施工记录留可核证据）。
 *
 * 用法：
 *   node scripts/run-runtime-e2e.mjs
 *   node scripts/run-runtime-e2e.mjs --self-test   （runner 自身的判据红证，不起子进程）
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** 仓根。 */
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** 三个运行时 e2e 文件（**显式枚举**；卡面文件级产出）。 */
export const RUNTIME_FILES = [
  "packages/e2e/tests/runtime/main-chain.mjs",
  "packages/e2e/tests/runtime/tool-loop.mjs",
  "packages/e2e/tests/runtime/resume.mjs",
];

/** 子进程继承的环境（假 Provider 的闸门需要显式放行，与 R3-19 同口径）。 */
function childEnv() {
  return {
    ...process.env,
    NODE_ENV: "test",
    WBTIME_AI_ALLOW_FAKE_PROVIDER: "1",
  };
}

/**
 * 解析一个文件的 TAP 汇总（`# pass N` / `# fail N`）。
 *
 * @param {string} text 子进程输出。
 * @returns {{pass: number|null, fail: number|null, parsed: boolean}}
 */
export function parseSummary(text) {
  const pass = /^# pass (\d+)$/m.exec(text);
  const fail = /^# fail (\d+)$/m.exec(text);
  return {
    pass: pass === null ? null : Number(pass[1]),
    fail: fail === null ? null : Number(fail[1]),
    parsed: pass !== null && fail !== null,
  };
}

/**
 * 跑一个文件。
 *
 * @param {string} relFile 相对仓根的文件路径。
 * @returns {Promise<{file: string, rc: number, pass: number|null, fail: number|null, parsed: boolean, tail: string}>}
 */
export function runFile(relFile) {
  const absolute = path.join(REPO_ROOT, relFile);
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["--experimental-sqlite", absolute], {
      cwd: REPO_ROOT,
      env: childEnv(),
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      process.stdout.write(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
      process.stderr.write(chunk);
    });
    child.once("error", reject);
    child.once("close", (code) => {
      const summary = parseSummary(stdout);
      resolve({
        file: relFile,
        rc: code === null ? 1 : code,
        pass: summary.pass,
        fail: summary.fail,
        parsed: summary.parsed,
        tail: stderr.slice(-400),
      });
    });
  });
}

/**
 * 主流程。
 *
 * @param {string[]} [files] 文件清单（self-test 用）。
 * @returns {Promise<number>} 退出码。
 */
export async function runRuntimeE2e(files = RUNTIME_FILES) {
  const prefix = "[runtime-e2e]";
  if (files.length === 0) {
    process.stderr.write(`${prefix} FAIL: 文件清单为空（0 文件 = 0 用例，绝不能算绿 —— N-10）\n`);
    return 1;
  }
  for (const relFile of files) {
    if (!existsSync(path.join(REPO_ROOT, relFile))) {
      process.stderr.write(`${prefix} FAIL: 文件不存在 ${relFile}（不存在 ≠ 跳过）\n`);
      return 1;
    }
  }

  process.stdout.write(`${prefix} files(${files.length}):\n${files.map((file) => `  - ${file}\n`).join("")}`);
  const results = [];
  for (const relFile of files) {
    results.push(await runFile(relFile));
  }

  let totalPass = 0;
  let totalFail = 0;
  const problems = [];
  for (const result of results) {
    if (!result.parsed) {
      problems.push(`${result.file}: 无法解析 TAP 汇总（空输出 = 假绿）`);
      continue;
    }
    totalPass += result.pass ?? 0;
    totalFail += result.fail ?? 0;
    if (result.rc !== 0) problems.push(`${result.file}: 退出码 ${result.rc}`);
    if ((result.fail ?? 0) !== 0) problems.push(`${result.file}: fail=${result.fail}`);
    if ((result.pass ?? 0) < 1) problems.push(`${result.file}: pass=0（0 用例 = 假绿）`);
  }

  if (problems.length > 0) {
    process.stderr.write(`${prefix} FAIL:\n${problems.map((item) => `  - ${item}\n`).join("")}`);
    return 1;
  }
  process.stdout.write(
    `${prefix} OK ✅ files=${results.length} pass=${totalPass} fail=${totalFail}\n`,
  );
  return 0;
}

/** `--self-test`：runner 自身的判据红证（不起子进程）。 */
async function selfTest() {
  const checks = [];
  const check = (name, ok, detail = "") => checks.push({ name, ok, detail });

  check("0 文件必须 exit 1", (await runRuntimeE2e([])) === 1);
  check("文件不存在必须 exit 1", (await runRuntimeE2e(["packages/e2e/tests/runtime/nope.mjs"])) === 1);

  const empty = parseSummary("");
  check("空输出不可解析（假绿）", empty.parsed === false);
  const zero = parseSummary(["1..1", "# tests 1", "# pass 0", "# fail 0"].join("\n"));
  check("pass=0 可解析但会被 pass<1 判据拒绝", zero.parsed === true && zero.pass === 0);
  const good = parseSummary(["1..1", "# tests 1", "# pass 1", "# fail 0"].join("\n"));
  check("真实汇总不得误伤", good.parsed === true && good.pass === 1);

  for (const item of checks) {
    process.stdout.write(`  ${item.ok ? "ok  " : "FAIL"} ${item.name}${item.ok ? "" : `  ← ${item.detail}`}\n`);
  }
  const failed = checks.filter((item) => !item.ok);
  process.stdout.write(`[runtime-e2e self-test] ${failed.length === 0 ? "PASS" : "FAIL"} ${checks.length - failed.length}/${checks.length}\n`);
  process.exitCode = failed.length === 0 ? 0 : 1;
}

if (process.argv.slice(2).includes("--self-test")) {
  selfTest().catch((error) => {
    process.stderr.write(`[runtime-e2e self-test] FAIL: ${error.message}\n`);
    process.exitCode = 1;
  });
} else {
  try {
    process.exitCode = await runRuntimeE2e();
  } catch (error) {
    process.stderr.write(`[runtime-e2e] FAIL: ${error.message}\n`);
    process.exitCode = 1;
  }
}
