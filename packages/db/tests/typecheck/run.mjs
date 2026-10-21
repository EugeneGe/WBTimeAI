/**
 * 类型层反例执行器 · 「该红的必须在类型层红」的**正向证明**。
 *
 * 为什么需要一个执行器而不是直接跑 `tsc`：
 * 一个"能报错"的夹具什么都证明不了 —— 文件里随便写个语法错也会 exit 1。所以这里
 * 断言的是**报错的具体内容**：exit code != 0、输出点名该夹具文件、出现期望的关键字、
 * 且 `error TS` 条数**恰好**等于预期（多一条 = 判据被别的问题污染）。
 *
 * 反向也要能红：**若 tsc 意外 exit 0（反例编译通过）⇒ 本判据失败**，退出码 1 ——
 * 那意味着被守护的约束已经被削弱了。
 *
 * 两个夹具（T3-03 起分治，各配一个 config，避免互相掩盖）：
 *   1. `naked-id.ts`  —— J-8：裸 id 撞 `ScopedRef` 品牌（期望 1 条）；
 *   2. `no-parent.ts` —— R3-22：子表仓储的父引用不接受裸 id / 不可省略（期望 2 条）。
 *
 * 运行：`node tests/typecheck/run.mjs`（或 `pnpm --filter @wbtime/db test:typecheck`）
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DB_ROOT = path.resolve(HERE, "../..");
const TSC = path.join(DB_ROOT, "node_modules", "typescript", "bin", "tsc");

/** @type {readonly {name: string; config: string; file: string; expect: readonly string[]; expectedErrors: number; pass: string; fail: string}[]} */
const FIXTURES = [
  {
    name: "J-8 裸 id",
    config: "tsconfig.json",
    file: "naked-id.ts",
    expect: ["naked-id.ts", "ScopedRef"],
    expectedErrors: 1,
    pass: "裸 id 在类型层不可通过",
    fail: "裸 id 竟然编译通过了，I-1 的类型约束被削弱（J-8 失败）",
  },
  {
    name: "R3-22 子表无父参",
    config: "tsconfig.no-parent.json",
    file: "no-parent.ts",
    expect: ["no-parent.ts", "ScopedRef"],
    expectedErrors: 2,
    pass: "子表仓储的父引用不接受裸 id、也不可省略（R3-22）",
    fail: "裸 id / 缺父引用竟然编译通过了 —— R3-22 的父引用强制被削弱",
  },
];

/**
 * 跑一个夹具。
 *
 * @param {typeof FIXTURES[number]} fixture
 * @returns {string[]} 失败原因（空数组 = 通过）
 */
function check(fixture) {
  const config = path.join(HERE, fixture.config);
  const result = spawnSync(process.execPath, [TSC, "--noEmit", "-p", config], {
    cwd: DB_ROOT,
    encoding: "utf8",
  });

  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  const errorLines = output
    .split(/\r?\n/)
    .filter((line) => /error TS\d+/.test(line));

  const failures = [];
  if (result.error) {
    failures.push(`无法启动 tsc：${result.error.message}`);
  }
  if (result.status === 0) {
    failures.push(fixture.fail);
  } else if (result.status === null) {
    failures.push(`tsc 被信号终止（signal=${String(result.signal)}）`);
  }

  for (const expected of fixture.expect) {
    if (!output.includes(expected)) {
      failures.push(`tsc 输出里没有出现 ${expected} —— 报错不是「撞上 ScopedRef 品牌」`);
    }
  }

  if (errorLines.length !== fixture.expectedErrors) {
    failures.push(
      `期望恰好 ${fixture.expectedErrors} 条 error TS，实测 ${errorLines.length} 条` +
        `（反例被别的问题污染，或某条反例意外通过，判据不可信）：\n` +
        errorLines.map((line) => `    ${line}`).join("\n"),
    );
  }

  return { failures, output, errorLines, status: result.status, config };
}

let failed = 0;
for (const fixture of FIXTURES) {
  const { failures, output, errorLines, status, config } = check(fixture);
  if (failures.length > 0) {
    failed += 1;
    console.error(`[${fixture.name}] 失败：`);
    for (const failure of failures) console.error(`  - ${failure}`);
    console.error(`\n--- tsc 原始输出（${path.relative(DB_ROOT, config)}）---\n${output}`);
    continue;
  }
  console.log(`[${fixture.name}] PASS：${fixture.pass}`);
  console.log(`  命令：tsc --noEmit -p ${path.relative(DB_ROOT, config)}`);
  console.log(`  exit code：${String(status)}（!= 0 ✓）`);
  console.log(`  error TS 条数：${errorLines.length}`);
  for (const line of errorLines) console.log(`  ${line}`);
}

if (failed > 0) {
  console.error(`\n类型层反例执行器：${failed}/${FIXTURES.length} 个夹具失败`);
  process.exit(1);
}

console.log(`\n类型层反例执行器：${FIXTURES.length}/${FIXTURES.length} 个夹具全部按预期变红`);
process.exit(0);
