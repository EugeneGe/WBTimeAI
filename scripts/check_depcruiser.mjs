#!/usr/bin/env node
// T1-06 — run the layering rules, and prove they can go red.
//
// Why this wrapper exists (instead of calling depcruise straight from npm)
// -----------------------------------------------------------------------
// `dependency-cruiser` exits 0 for two very different reasons:
//
//   1. it walked the source and found no violation        -> real green
//   2. it walked **nothing** (0 modules) and so found none -> vacuous green
//
// Case 2 is the exact shape of this repo's K-11 defect ("an empty glob is
// vacuously true"). A CI step that calls depcruise directly cannot tell the
// two apart. So this wrapper:
//
//   * requires a **minimum module count** before it will report PASS;
//   * reports **per-rule** results instead of one folded boolean;
//   * has a `--self-test` that **injects a real violation** into a temp file
//     and asserts the gate goes red — then removes it and asserts green again.
//
// Exit codes: 0 pass · 1 violation/vacuous · 2 usage error · 9 self-test failed

import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  writeFileSync,
  rmSync,
  existsSync,
  readdirSync,
  readFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, relative, sep } from "node:path";

const REPO_ROOT = resolve(import.meta.dirname, "..");
const CONFIG = join(REPO_ROOT, ".dependency-cruiser.cjs");

// A half-empty scan is indistinguishable from a broken one.  V0.1.0 has 8-ish
// packages plus a full frontend app; 20 is a deliberately *low* floor that a
// real tree clears easily and an accidentally-empty one cannot.
const MIN_MODULES = 20;

const RULES = [
  "no-domain-orm-web",
  "orm-only-in-repositories",
  "no-package-imports-app",
];

// ---------------------------------------------------------------------------
// L-7 · 源码文本级 ORM 断言（补 depcruise 的盲区）
// ---------------------------------------------------------------------------
//
// 为什么需要这一层（实测 2026-10-21）
// ---------------------------------
// `orm-only-in-repositories` 这条规则**在当前配置下是惰性的**：往
// `packages/db/src/__probe_orm.ts` 写 `import { sql } from "drizzle-orm"` 之后
// `violations` 仍然是 0。原因不是配置写错，而是 depcruise 的模块图**不含
// node_modules 外部依赖**（实测 `connection.ts` 的 deps 只列出 `node:sqlite`，
// `task-repo.ts` 只列出两条内部依赖），而规则的 `to.path` 匹配的是
// `^(drizzle-orm|drizzle-kit)` —— 永远匹配不到图里不存在的东西。
//
// 结论：「ORM 只在 repositories」这条分层铁律，在 V0.1.0 的门禁里**从未被证明**，
// 那项 PASS 是假绿。修法不是去调 depcruise 的解析（配置不透明、跨平台不稳），
// 而是在**源码文本层**再判一次：import 语句是纯文本，读得到就是读得到。
//
// 白名单为什么是这五个（而不是只有 repositories + connection.ts）
// -------------------------------------------------------------
// 其中 `schema/**` 是**必要例外**：28 个生成物用 drizzle 的建表函数定义表，
// 它们必须 import ORM，且**禁止手改**（生成器产出）。`index.ts` 当前不 import ORM，
// 保留在名单内只是为了与 depcruise 的 `pathNot` 保持一致 —— 两个门禁对同一件事
// 给出不同结论，比其中一个更严更糟（人会去信那个绿的）。
const ORM_SCAN_ROOT = join(REPO_ROOT, "packages");

/** 允许出现 ORM / `@wbtime/db` import 的路径（posix 相对仓库根的路径前缀/正则）。 */
const ORM_ALLOWED = [
  /^packages\/db\/src\/repositories\//,
  /^packages\/db\/src\/schema\//, // 生成物：建表函数的唯一合法用处（禁手改）
  /^packages\/db\/src\/index\.ts$/, // 与 depcruise 的 pathNot 对齐
  /^packages\/db\/src\/(client|connection)/, // db 句柄工厂
];

/**
 * 匹配 `import ... from "X"` / `import("X")` / `require("X")` / `import "X"`。
 *
 * 覆盖四种形态是有意的：只判 `from "…"` 会漏掉动态 import 与副作用 import，
 * 而"绕过门禁"最省事的写法恰好就是这两种。
 */
const ORM_IMPORT_PATTERN =
  /(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|\bimport\s*)["'](drizzle-orm(?:\/[^"']*)?|drizzle-kit(?:\/[^"']*)?|@wbtime\/db(?:\/[^"']*)?)["']/;

/**
 * 自检探针的**固定路径清单**。
 *
 * 两个用途：① 注入清单；② 「上次异常中断」的清理清单 —— 探针写在 `packages/*\/src` 下，
 * 而 `packages/core` / `packages/db` 的 tsconfig `include: ["src/**\/*.ts"]` 会把它编进去，
 * 所以**残留一个探针就会让别人的 `tsc -b` 失败**。实测踩过：一次与其它门禁并行运行时
 * 残留 `packages/core/src/__probe_a.ts`，直接把 `packages/security` 的构建打红
 * （`error TS2307: Cannot find module 'drizzle-orm'`）。故本脚本在**任何**退出路径都清理，
 * 并在启动时自愈历史残留。
 */
const PROBE_PATHS = Object.freeze([
  "packages/domain/src/__injected_probe.ts",
  "packages/logging/src/__injected_probe.ts",
  "packages/event/src/__injected_probe.ts",
  "packages/core/src/__probe_a.ts",
  "packages/db/src/__probe_b.ts",
]);

/**
 * 删除探针文件（幂等）。
 *
 * @param {readonly string[]} paths 相对仓库根的路径。
 * @returns {number} 实际删掉的个数。
 */
function cleanupProbes(paths = PROBE_PATHS) {
  let removed = 0;
  for (const rel of paths) {
    const abs = join(REPO_ROOT, rel);
    if (existsSync(abs)) {
      rmSync(abs, { force: true });
      removed += 1;
    }
  }
  return removed;
}

/**
 * 启动时自愈：把历史残留的探针删掉并**大声报告**。
 *
 * 不静默删除：残留意味着上一次运行异常中断（进程被杀 / 崩溃），这本身是值得看见的信号。
 */
function healStaleProbes() {
  const removed = cleanupProbes();
  if (removed > 0) {
    console.log(
      `[check_depcruiser] WARN 清理了上次异常中断残留的探针 ${removed} 个` +
        "（它们会让 packages/* 的 tsc -b 失败，构建报错指向 __probe_*.ts 时先看这里）"
    );
  }
}

// 任何退出路径都清理：正常结束、异常抛出、Ctrl-C、被 kill。
// 这是"把探针写进仓库树"这个设计的必要代价（见 PROBE_PATHS 的说明）。
process.on("exit", () => {
  cleanupProbes();
});
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    cleanupProbes();
    process.exit(130);
  });
}

/** 递归列出 `packages/*\/src/**.ts`（跳过 node_modules / dist / 声明文件）。 */function listPackageSources(dir = ORM_SCAN_ROOT) {
  /** @type {string[]} */
  const out = [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "dist") continue;
      out.push(...listPackageSources(abs));
      continue;
    }
    if (!entry.name.endsWith(".ts") || entry.name.endsWith(".d.ts")) continue;
    out.push(abs);
  }
  return out;
}

/**
 * 源码文本级扫描：ORM / `@wbtime/db` 的 import 只许出现在白名单路径。
 *
 * 返回形状与 {@link analyse} 对齐（`ok` / `problems` / `lines`），好让调用方用
 * 同一套判定逻辑处理两个来源。
 */
function scanOrmImports() {
  const files = listPackageSources();
  /** @type {string[]} */
  const problems = [];
  const hits = [];
  let allowedHits = 0;

  for (const abs of files) {
    const rel = relative(REPO_ROOT, abs).split(sep).join("/");
    const text = readFileSync(abs, "utf8");
    const lines = text.split(/\r?\n/);
    const allowed = ORM_ALLOWED.some((re) => re.test(rel));
    for (let index = 0; index < lines.length; index += 1) {
      const match = ORM_IMPORT_PATTERN.exec(lines[index]);
      if (!match) continue;
      const where = `${rel}:${index + 1}`;
      if (allowed) {
        allowedHits += 1;
      } else {
        hits.push(`${where}  ${match[0].trim()}`);
        problems.push(`ORM import outside repositories/connection: ${where} (${match[1]})`);
      }
    }
  }

  // 与 MIN_MODULES 同一条思路：扫到的文件太少 = 扫描本身坏了，不能读成"没问题"。
  const MIN_SCANNED_FILES = 20;
  if (files.length < MIN_SCANNED_FILES) {
    problems.push(
      `INVALID(EMPTY): scanned ${files.length} source files < ${MIN_SCANNED_FILES} — ` +
        `a scan this small cannot be a pass`
    );
  }

  // 反"真空通过"：白名单文件里若一条都没匹配上，说明正则本身坏了（写窄了/被改坏），
  // 此时 violations=0 是**真空**而不是真通过 —— 正是本项目 K-11 的形态。
  if (allowedHits === 0) {
    problems.push(
      "INVALID(EMPTY): whitelisted files matched 0 ORM imports — " +
        "the scanner pattern itself is broken (vacuous pass refused)"
    );
  }

  const lines = [
    `orm-import scan: files=${files.length} allowed=${allowedHits} violations=${hits.length}`,
  ];
  for (const hit of hits) lines.push(`  ${hit}`);
  return { ok: problems.length === 0, problems, lines };
}

function runDepcruise(extraArgs = []) {
  const args = [
    "--config",
    CONFIG,
    "--output-type",
    "json",
    ...extraArgs,
    "packages",
    "apps",
  ];
  // On Windows the entry point is a ``.cmd`` shim, which ``execFileSync`` cannot
  // resolve from PATH without a shell.  Prefer the local shim explicitly and fall
  // back to a shell-resolved name: calling the bare name fails silently with
  // "could not parse JSON output", which reads like a config error but is really
  // a missing executable (measured 2026-10-21).
  const localShim = join(
    REPO_ROOT,
    "node_modules",
    ".bin",
    process.platform === "win32" ? "depcruise.CMD" : "depcruise",
  );
  const command = existsSync(localShim) ? localShim : "depcruise";
  try {
    const stdout = execFileSync(command, args, {
      cwd: REPO_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      // `maxBuffer` **必须**显式给足（实测 2026-10-21，V0.2.0 收口期）。
      // 默认 1 MiB；本仓模块图 599 个模块时 JSON 报告已是 **1,053,449 字节** ⇒
      // `execFileSync` 抛 ENOBUFS（`err.status === null`），stdout 被截断成非法 JSON，
      // 于是本脚本报 "could not parse depcruise JSON output" 并 FAIL。
      // 这条失败与"有没有违规"**无关**：它随代码量增长而随机出现（今天早些时候同一条
      // 命令还是 PASS），属于典型的"门禁随体积翻红"的假红 —— 必须用足够的缓冲区消掉，
      // 而不是去调 MIN_MODULES 之类的判据。
      maxBuffer: 64 * 1024 * 1024,
      shell: process.platform === "win32",
    });
    return { exit: 0, stdout };
  } catch (err) {
    // depcruise signals "violations found" via a non-zero exit; stdout still
    // carries the JSON report we need.
    return { exit: err.status ?? 1, stdout: err.stdout ?? "", stderr: err.stderr ?? "" };
  }
}

function analyse(stdout) {
  let report;
  try {
    report = JSON.parse(stdout);
  } catch {
    return { ok: false, problems: ["could not parse depcruise JSON output"], lines: [] };
  }
  const modules = report?.modules ?? [];
  // Violations live in ``summary.violations`` — NOT in
  // ``modules[].dependencies[].validations``.  Reading the wrong branch made every
  // rule report 0 and turned the baseline green for no reason: a self-test that
  // injects three genuine violations still said "0 violations" (measured
  // 2026-10-21).  That is this repo's K-11 vacuous-pass shape, so the absence of a
  // ``summary`` block is itself an error rather than an empty result.
  const summary = report?.summary;
  const problems = [];
  if (!summary || !Array.isArray(summary.violations)) {
    problems.push(
      "INVALID: depcruise output has no summary.violations — refusing to read absence as 'no violations'"
    );
  }
  const violations = Array.isArray(summary?.violations) ? summary.violations : [];

  if (modules.length < MIN_MODULES) {
    problems.push(
      `INVALID(EMPTY): scanned ${modules.length} modules < ${MIN_MODULES} — ` +
        `a scan this small cannot be a pass`
    );
  }

  const perRule = new Map(RULES.map((r) => [r, 0]));
  const unexpected = new Map();
  for (const violation of violations) {
    const name = violation?.rule?.name ?? "(unnamed)";
    if (perRule.has(name)) {
      perRule.set(name, perRule.get(name) + 1);
    } else {
      unexpected.set(name, (unexpected.get(name) ?? 0) + 1);
    }
  }

  const lines = [
    `scanned modules=${modules.length} (floor ${MIN_MODULES})`,
    `violations total=${violations.length}`,
  ];
  for (const [rule, hits] of perRule) {
    lines.push(`  rule ${rule}: violations=${hits}`);
    if (hits > 0) problems.push(`rule ${rule}: ${hits} violation(s)`);
  }
  for (const [rule, hits] of unexpected) {
    lines.push(`  rule ${rule} (not declared in RULES): violations=${hits}`);
    problems.push(`unexpected rule '${rule}': ${hits} violation(s)`);
  }
  return { ok: problems.length === 0, problems, lines };
}

/**
 * 两层合一的总判定：**依赖图规则**（depcruise）+ **源码文本级 ORM 断言**（L-7）。
 *
 * 任一侧红即整体红。两层互补而非重复：depcruise 能判「packages 不得 import apps」
 * 这类跨包方向（文本层判不了 `../../../apps/web/src/App` 这种相对穿越），文本层能判
 * 「packages/db 内部谁 import 了 drizzle-orm」——那恰好落在 depcruise 的解析盲区里
 * （见文件头部 L-7 说明）。
 */
function evaluate() {
  const graph = analyse(runDepcruise().stdout);
  const text = scanOrmImports();
  return {
    ok: graph.ok && text.ok,
    problems: [...graph.problems, ...text.problems],
    lines: [...graph.lines, ...text.lines],
  };
}


function selfTest() {
  console.log("[check_depcruiser] self-test");
  console.log(
    "  注意：自检期间会在 packages/*/src 下创建探针文件，**其它包的 `tsc -b` 可能在这几秒内失败**" +
      "（探针随清理消失）。验收请串行跑，不要与构建并行。"
  );
  healStaleProbes();
  let ok = true;

  // -- 1. baseline: the real tree must be green -------------------------------
  const base = evaluate();
  console.log(`  [${base.ok ? "OK" : "FAIL"}] baseline green: ${base.ok}`);
  if (!base.ok) {
    base.problems.forEach((p) => console.log(`         ${p}`));
    ok = false;
  }

  // -- 2. 依赖图规则注入：每条规则各注入一个真违规，必须变红 -------------------
  // 每个注入只针对一条规则，这样"某条规则其实什么都没匹配上"（例如 from glob 写错）
  // 会在这里暴露，而不是留到生产里。
  const injections = [
    {
      rule: "no-domain-orm-web",
      rel: "packages/domain/src/__injected_probe.ts",
      code: "import { sql } from 'drizzle-orm';\nexport const probe = sql;\n",
    },
    {
      rule: "orm-only-in-repositories",
      rel: "packages/logging/src/__injected_probe.ts",
      code: "import { sql } from 'drizzle-orm';\nexport const probe = sql;\n",
    },
    {
      rule: "no-package-imports-app",
      rel: "packages/event/src/__injected_probe.ts",
      code: "import { App } from '../../../apps/web/src/App';\nexport const probe = App;\n",
    },
  ];

  const created = [];
  try {
    for (const inj of injections) {
      const abs = join(REPO_ROOT, inj.rel);
      writeFileSync(abs, inj.code, "utf8");
      created.push(abs);
      const res = analyse(runDepcruise().stdout);
      const wentRed = !res.ok && res.problems.some((p) => p.includes(inj.rule));
      console.log(`  [${wentRed ? "OK" : "FAIL"}] injection '${inj.rule}' must go red: ${wentRed}`);
      if (!wentRed) {
        console.log(`         problems seen: ${JSON.stringify(res.problems)}`);
        ok = false;
      }
    }
  } finally {
    for (const abs of created) rmSync(abs, { force: true });
  }

  // -- 3. L-7 文本级断言注入：必须点名两个探针，且整体变红 ---------------------
  // 关键用例是第二个：`packages/db/src/__probe_b.ts` 位于 **drizzle 可解析** 的包里，
  // 正是 depcruise 的解析盲区（能解析 → 被解析成 node_modules 真实路径 → 规则的
  // `to.path=^drizzle-orm` 匹配不到）。只测 packages/core 那种"本来就解析不到"的路径
  // 会得到一个假绿：证明的只是规则能开火，不是它覆盖了危险区。
  const textInjections = [
    {
      label: "drizzle-orm in packages/core（解析不到的包）",
      rel: "packages/core/src/__probe_a.ts",
      code: 'import { sql } from "drizzle-orm";\nexport const probe = sql`1`;\n',
    },
    {
      label: "@wbtime/db in packages/db（解析得到的包 = depcruise 盲区）",
      rel: "packages/db/src/__probe_b.ts",
      code: 'import { UserRepo } from "@wbtime/db";\nexport const probe = UserRepo;\n',
    },
  ];

  const textCreated = [];
  try {
    for (const inj of textInjections) {
      const abs = join(REPO_ROOT, inj.rel);
      writeFileSync(abs, inj.code, "utf8");
      textCreated.push(abs);
    }

    const text = scanOrmImports();
    for (const inj of textInjections) {
      const named = text.problems.some((p) => p.includes(inj.rel));
      console.log(`  [${named ? "OK" : "FAIL"}] L-7 text scan must name '${inj.rel}': ${named}`);
      if (!named) {
        console.log(`         problems seen: ${JSON.stringify(text.problems)}`);
        ok = false;
      }
    }

    const combined = evaluate();
    const wentRed = !combined.ok;
    console.log(`  [${wentRed ? "OK" : "FAIL"}] L-7 combined gate must go red: ${wentRed}`);
    if (!wentRed) {
      console.log(`         problems seen: ${JSON.stringify(combined.problems)}`);
      ok = false;
    }

    // 违规行必须带「文件:行号 + 命中文本」—— 只说"有违规"等于让人自己去 grep。
    const hasLocus = text.lines.some((l) => /__probe_[ab]\.ts:\d+\s+.*(drizzle-orm|@wbtime\/db)/.test(l));
    console.log(`  [${hasLocus ? "OK" : "FAIL"}] L-7 violation lines carry file:line + import: ${hasLocus}`);
    if (!hasLocus) {
      console.log(`         lines seen: ${JSON.stringify(text.lines)}`);
      ok = false;
    }
  } finally {
    for (const abs of textCreated) rmSync(abs, { force: true });
  }

  // -- 4. 清理必须干净：探针不得残留（残留会污染下一次跑与 git status） --------
  const residue = [...injections, ...textInjections]
    .map((inj) => inj.rel)
    .filter((rel) => existsSync(join(REPO_ROOT, rel)));
  console.log(
    `  [${residue.length === 0 ? "OK" : "FAIL"}] probes removed (residue=${residue.length})${
      residue.length ? `: ${residue.join(", ")}` : ""
    }`
  );
  if (residue.length > 0) ok = false;

  // -- 5. 恢复：注入移除后必须回到绿 -----------------------------------------
  const after = evaluate();
  console.log(`  [${after.ok ? "OK" : "FAIL"}] green restored after cleanup: ${after.ok}`);
  if (!after.ok) {
    after.problems.forEach((p) => console.log(`         ${p}`));
    ok = false;
  }

  console.log(`[check_depcruiser] ${ok ? "PASS" : "FAIL"}`);
  return ok;
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--self-test")) {
    process.exit(selfTest() ? 0 : 9);
  }
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log("usage: node scripts/check_depcruiser.mjs [--self-test]");
    process.exit(0);
  }
  if (!existsSync(CONFIG)) {
    console.log(`[check_depcruiser] FAIL missing config: ${CONFIG}`);
    process.exit(2);
  }

  healStaleProbes();
  const res = evaluate();
  res.lines?.forEach((l) => console.log(`[check_depcruiser] ${l}`));
  res.problems.forEach((p) => console.log(`[check_depcruiser]   PROBLEM: ${p}`));
  console.log(`[check_depcruiser] ${res.ok ? "PASS" : "FAIL"}`);
  process.exit(res.ok ? 0 : 1);
}

main();
