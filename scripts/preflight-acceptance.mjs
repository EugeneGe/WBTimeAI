#!/usr/bin/env node
/**
 * T2-11 / R-27 · **验收前置检查**（一条命令，三件事）。
 *
 * 为什么需要它
 * -----------
 * 本轮实测出两类"会让验收结果骗人"的环境噪声：
 *
 * 1. **探针残留**：门禁的 `--self-test` 会把探针写进 `packages/*\/src`（那在各自
 *    `tsconfig.include` 里）。若上一次运行异常中断，残留文件会**持续**让别人的
 *    `tsc -b` 红，而报错指向一个没人认识的 `__probe_a.ts`。实测发生过。
 * 2. **构建与测试并行**：`tsc -b` 在写 `dist/`、测试在读 `dist/`。触发条件不是
 *    "并行跑两条 test"，而是"**任一进程在写该包 dist 时，有人在读**"。症状是
 *    **随机单条失败、重跑即绿** —— 这种最容易被当噪声忽略（本轮 `rbac-guard` 那次
 *    "偶发 fail" 就是它）。
 *
 * 三件事
 * ------
 * ① 探针残留扫描 ⇒ 有残留直接失败（并打印怎么清）；
 * ② 并发构建检测（近 N 秒内 `dist/` 或 `*.tsbuildinfo` 被写过 ⇒ 视为正在构建）⇒ 失败；
 * ③ 无论结果如何，都打印"验收必须串行"的明确提示。
 *
 * 用法
 * ----
 * ```bash
 * node scripts/preflight-acceptance.mjs              # 默认窗口 5s
 * node scripts/preflight-acceptance.mjs --window 10  # 自定义窗口（秒）
 * ```
 *
 * 退出码：0 通过 · 1 检出问题 · 2 用法错误。
 *
 * 已知边界（不夸大）
 * ----------------
 * 并发构建检测靠的是**文件系统时间戳**，所以：
 * * 刚启动、还没写第一个文件的构建**看不到**（窗口是滞后的）——它无法替代"串行"本身，
 *   只是把"已经发生"的并行挡住；
 * * 反过来，如果刚好有人**刚刚**跑完构建（5 秒内），会被误判为"正在构建"。这是刻意
 *   选择的方向：**宁可让人等几秒重跑，也不要让一个假失败被当成真缺陷**。
 */

import { readdirSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";

const REPO_ROOT = resolve(import.meta.dirname, "..");

/** 探针文件名模式（`check_depcruiser.mjs` 的注入 + 手工复现用的探针都覆盖）。 */
const PROBE_PATTERNS = [/^__probe.*\.ts$/, /^__injected_probe.*\.ts$/];

/** 扫描根（只扫这两棵，不扫 node_modules）。 */
const SCAN_ROOTS = ["packages", "apps"];

/** 构建产物所在目录名。命中它（或 `*.tsbuildinfo`）即视为"可能正在构建"。 */
const BUILD_OUTPUT_DIR = "dist";

/** 时间窗口默认值（秒）。 */
const DEFAULT_WINDOW_SECONDS = 5;

/** 解析 `--window <秒>`。 */
function parseWindow(argv) {
  const index = argv.indexOf("--window");
  if (index === -1) return DEFAULT_WINDOW_SECONDS;
  const raw = argv[index + 1];
  const seconds = Number(raw);
  if (!Number.isFinite(seconds) || seconds < 0) {
    console.error(`[preflight] 用法错误：--window 需要一个 ≥0 的秒数，收到 ${String(raw)}`);
    process.exit(2);
  }
  return seconds;
}

/** 递归收集探针文件（返回相对仓库根的 posix 路径）。 */
function findProbes(dir = REPO_ROOT) {
  const found = [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === ".git") continue;
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...findProbes(abs));
      continue;
    }
    if (!entry.name.endsWith(".ts")) continue;
    if (PROBE_PATTERNS.some((pattern) => pattern.test(entry.name))) {
      found.push(relative(REPO_ROOT, abs).split(sep).join("/"));
    }
  }
  return found;
}

/** 递归收集"近 N 秒内被写过的构建产物"。 */
function findRecentBuildWrites(windowMs, dir = REPO_ROOT) {
  const hits = [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return hits;
  }
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === ".git") continue;
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) {
      hits.push(...findRecentBuildWrites(windowMs, abs));
      continue;
    }
    const inDist = abs.split(sep).includes(BUILD_OUTPUT_DIR);
    const isBuildInfo = entry.name.endsWith(".tsbuildinfo");
    if (!inDist && !isBuildInfo) continue;
    let stat;
    try {
      stat = statSync(abs);
    } catch {
      continue;
    }
    if (Date.now() - stat.mtimeMs <= windowMs) {
      hits.push(relative(REPO_ROOT, abs).split(sep).join("/"));
    }
  }
  return hits;
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log("usage: node scripts/preflight-acceptance.mjs [--window <seconds>]");
    process.exit(0);
  }
  if (argv.length > 0 && !argv.includes("--window")) {
    console.error(`[preflight] 未知参数：${argv.join(" ")}（支持 --window <秒>）`);
    process.exit(2);
  }

  const windowSeconds = parseWindow(argv);
  const windowMs = windowSeconds * 1000;
  console.log(`[preflight] 验收前置检查（窗口 ${windowSeconds}s）`);

  let failed = false;

  // ① 探针残留
  const probes = SCAN_ROOTS.flatMap((root) => findProbes(join(REPO_ROOT, root)));
  if (probes.length === 0) {
    console.log("  [OK]   ① 无探针残留（__probe* / __injected_probe*）");
  } else {
    failed = true;
    console.log(`  [FAIL] ① 检出 ${probes.length} 个探针残留 —— 它们会让 packages/* 的 tsc -b 失败：`);
    for (const file of probes) console.log(`           ${file}`);
    console.log("         清理：node scripts/check_depcruiser.mjs（启动时会自愈并 WARN）");
  }

  // ② 并发构建
  const writes = findRecentBuildWrites(windowMs);
  if (writes.length === 0) {
    console.log(`  [OK]   ② ${windowSeconds}s 内无 dist/ 或 *.tsbuildinfo 写入（无并发构建迹象）`);
  } else {
    failed = true;
    const sample = writes.slice(0, 5).join(", ");
    console.log(
      `  [FAIL] ② 检出 ${writes.length} 个近 ${windowSeconds}s 内被写过的构建产物 —— ` +
        "很可能有并发 tsc -b 在写 dist："
    );
    console.log(`           ${sample}${writes.length > 5 ? " …" : ""}`);
    console.log("         原因：tsc -b 写 dist / 测试读 dist ⇒ 随机单条失败、重跑即绿（R-27）");
  }

  // ③ 提示（永远打印）
  console.log("  [NOTE] ③ 验收必须**串行**：不要与任何 tsc -b 并行，也不要并行跑两个包的测试。");

  console.log(`[preflight] ${failed ? "FAIL" : "PASS"}`);
  process.exit(failed ? 1 : 0);
}

main();
