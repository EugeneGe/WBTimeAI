/**
 * J-8 执行器 · 「裸 id 必须编译失败」的**正向证明**。
 *
 * 为什么需要一个执行器而不是直接跑 `tsc`：
 * 一个"能报错"的夹具什么都证明不了 —— 文件里随便写个语法错也会 exit 1。所以这里
 * 断言的是**报错的具体内容**：
 *
 *   1. `tsc --noEmit -p tests/typecheck/tsconfig.json` 的 exit code **必须 != 0**；
 *   2. 输出必须点名 `naked-id.ts`；
 *   3. 输出必须提到 `ScopedRef`（错在参数品牌上，而不是别处写错）；
 *   4. `error TS` 恰好 **1** 条（多一条就说明判据被别的问题污染了）。
 *
 * 反向也要能红：**若 tsc 意外 exit 0（裸 id 编译通过）⇒ 本判据失败**，退出码 1 ——
 * 那意味着 I-1 的类型约束被削弱了。
 *
 * 运行：`node tests/typecheck/run.mjs`（或 `pnpm --filter @wbtime/db test:typecheck`）
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DB_ROOT = path.resolve(HERE, "../..");
const TSC = path.join(DB_ROOT, "node_modules", "typescript", "bin", "tsc");
const CONFIG = path.join(HERE, "tsconfig.json");

/** 期望命中：裸 id 调 findById 的参数类型错（TS2345）。 */
const EXPECTED_TEXT = ["naked-id.ts", "ScopedRef"];

const result = spawnSync(process.execPath, [TSC, "--noEmit", "-p", CONFIG], {
  cwd: DB_ROOT,
  encoding: "utf8",
});

/** @type {string} */
const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
const errorLines = output
  .split(/\r?\n/)
  .filter((line) => /error TS\d+/.test(line));

const failures = [];

if (result.error) {
  failures.push(`无法启动 tsc：${result.error.message}`);
}
if (result.status === 0) {
  failures.push(
    "tsc 意外以 exit code 0 结束 —— 裸 id 竟然编译通过了，I-1 的类型约束被削弱（J-8 失败）"
  );
} else if (result.status === null) {
  failures.push(`tsc 被信号终止（signal=${String(result.signal)}）`);
}

for (const expected of EXPECTED_TEXT) {
  if (!output.includes(expected)) {
    failures.push(`tsc 输出里没有出现 ${expected} —— 报错不是「裸 id 撞上 ScopedRef 品牌」`);
  }
}

if (errorLines.length !== 1) {
  failures.push(
    `期望恰好 1 条 error TS，实测 ${errorLines.length} 条（反例被别的问题污染，判据不可信）：\n` +
      errorLines.map((line) => `    ${line}`).join("\n")
  );
}

if (failures.length > 0) {
  console.error("J-8 失败：");
  for (const failure of failures) console.error(`  - ${failure}`);
  console.error("\n--- tsc 原始输出 ---\n" + output);
  process.exit(1);
}

console.log("J-8 PASS：裸 id 在类型层不可通过");
console.log(`  命令：tsc --noEmit -p ${path.relative(DB_ROOT, CONFIG)}`);
console.log(`  exit code：${String(result.status)}（!= 0 ✓）`);
console.log(`  error TS 条数：${errorLines.length}`);
for (const line of errorLines) console.log(`  ${line}`);
process.exit(0);
