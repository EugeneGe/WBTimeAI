#!/usr/bin/env node
/**
 * 回归分层 runner（V0.2.0 审计 #14）—— `smoke` / `regression` / `full` 三档。
 *
 * 背景：此前的入口只有「按套件」粒度（`test:smoke` / `test:conformance` /
 * `test:legacy` / `test:all`），没有「按强度分层」的单一入口 —— CI 想跑快档只能
 * 自己拼脚本名，拼错就静默少跑。本 runner 把分层变成**显式选择**：
 *
 * | 档 | 组（来自 `scripts/lib/suites.mjs`，单一登记表） | 档下界 |
 * |---|---|---|
 * | `smoke` | SMOKE | ≥5 |
 * | `regression` | SMOKE + CONFORMANCE | ≥16 |
 * | `full` | LEGACY_FORWARD + LEGACY_REVERSE + SMOKE + CONFORMANCE（= `test:all` 覆盖面） | ≥21 |
 *
 * 判据（缺档 / 空档一律 exit≠0，K-11 口径）：
 *   1. 档名必须显式给出且在表内 —— 缺参 / 未知档 ⇒ exit 1（**没有**缺省档）；
 *   2. 档的组列表不得为空 —— 空档 ⇒ exit 1（`--self-test` 里有构造红证）；
 *   3. 每组各自过 `runTapSuite` 的执行数判据（minPass / 文件级通过 / fail=0）；
 *   4. 档汇总 `# pass` 总和（实解析值）≥ 档下界（下界 = 组 minPass 之和）。
 *
 * 用法：
 *   node scripts/run-tier.mjs smoke
 *   node scripts/run-tier.mjs regression
 *   node scripts/run-tier.mjs full
 *   node scripts/run-tier.mjs --self-test   （runner 自身判据的红证，不起子进程）
 *
 * npm 入口（显式选择，不设缺省档）：`pnpm test:tier:smoke` / `:regression` / `:full`。
 * `parity:pg` **不在**任何档里：它需要外部 PG（`WBTIME_PG_URL`），单独走
 * `scripts/run-parity-pg.mjs`（缺 URL 即红，不 skip）。
 */

import { ALL_GROUPS, CONFORMANCE, LEGACY_FORWARD, LEGACY_REVERSE, resolveGroup, SMOKE } from "./lib/suites.mjs";
import { runTapSuite } from "./lib/tap-runner.mjs";

/** 档登记表：档名 → 组列表（组必须来自 `suites.mjs` 的导出，不得内联重写）。 */
export const TIERS = Object.freeze({
  smoke: Object.freeze([SMOKE]),
  regression: Object.freeze([SMOKE, CONFORMANCE]),
  full: Object.freeze([LEGACY_FORWARD, LEGACY_REVERSE, SMOKE, CONFORMANCE]),
});

/** 档下界 = 组下界之和（组 minPass 是实测数，档下界随之，不独立拍脑袋）。 */
export function tierFloor(tier) {
  return TIERS[tier].reduce((sum, group) => sum + group.minPass, 0);
}

/** 解析档名；不在表内（或未给）返回 `null` —— 调用方必须红，不许缺省放行。 */
export function resolveTier(name) {
  if (typeof name !== "string") return null;
  return Object.hasOwn(TIERS, name) ? name : null;
}

/** 空档守卫（执行路径与 `--self-test` 的红证走同一实现）。 */
export function assertNonEmptyTier(name, groups) {
  if (!Array.isArray(groups) || groups.length === 0) {
    throw new Error(`档 ${String(name)} 的组列表为空 —— 空档 = 0 用例，绝不能算绿（K-11）`);
  }
}

/** runner 自身的判据自证（不起子进程，秒级）。 */
function selfTest() {
  const checks = [];
  const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

  // ① 每档非空、下界为正。
  for (const [name, groups] of Object.entries(TIERS)) {
    check(`档 ${name} 非空`, groups.length > 0);
    check(`档 ${name} 下界为正`, tierFloor(name) > 0, `实测 ${tierFloor(name)}`);
  }

  // ② 档内组必须能在 ALL_GROUPS 里找到（防「另写一份套件定义」的漂移）。
  const registryKeys = new Set(ALL_GROUPS.map((group) => group.key));
  for (const [name, groups] of Object.entries(TIERS)) {
    for (const group of groups) {
      check(`档 ${name} 的组 ${group.key} 在 suites 登记表内`, registryKeys.has(group.key));
    }
  }

  // ③ 分层包含关系：smoke ⊆ regression ⊆ full（档名语义不许漂移）。
  const keysOf = (tier) => TIERS[tier].map((group) => group.key).sort().join(",");
  check("smoke ⊆ regression", TIERS.regression.includes(SMOKE));
  check(
    "regression ⊆ full",
    TIERS.full.includes(SMOKE) && TIERS.full.includes(CONFORMANCE),
  );
  check(
    "full 覆盖面 == ALL_GROUPS（四组一个不少）",
    keysOf("full") === ALL_GROUPS.map((group) => group.key).sort().join(","),
  );

  // ④ 红证：未知档 / 缺档名必须被拒（不许有缺省档）。
  check("未知档必须被拒", resolveTier("no-such-tier") === null);
  check("缺档名必须被拒", resolveTier(undefined) === null);

  // ⑤ 红证：空档列表必须被拒（构造临时空档，不走 TIERS 本体）。
  let emptyRejected = false;
  try {
    assertNonEmptyTier("empty-proof", Object.freeze([]));
  } catch {
    emptyRejected = true;
  }
  check("空档列表必须被拒", emptyRejected);

  for (const item of checks) {
    process.stdout.write(`  ${item.ok ? "ok  " : "FAIL"} ${item.name}${item.ok ? "" : `  ← ${item.detail}`}\n`);
  }
  const failed = checks.filter((item) => !item.ok);
  process.stdout.write(
    `[tier self-test] ${failed.length === 0 ? "PASS" : "FAIL"} ${checks.length - failed.length}/${checks.length}\n`,
  );
  return failed.length === 0 ? 0 : 1;
}

const args = process.argv.slice(2);

if (args.includes("--self-test")) {
  process.exitCode = selfTest();
} else {
  // 档名解析：`run-tier.mjs smoke` 或 `run-tier.mjs --tier=smoke`；两者都没有 ⇒ 红。
  const flagTier = args.find((arg) => arg.startsWith("--tier="))?.slice("--tier=".length);
  const tier = resolveTier(flagTier ?? args[0]);

  if (tier === null) {
    process.stderr.write(
      `[tier] FAIL: 必须显式选择档名（smoke | regression | full），收到 ${JSON.stringify(flagTier ?? args[0] ?? null)}\n` +
        `用法: node scripts/run-tier.mjs <tier>（无缺省档 —— 缺档 = 缺证据）\n`,
    );
    process.exitCode = 1;
  } else {
    const groups = TIERS[tier];
    const floor = tierFloor(tier);
    process.stdout.write(
      `[tier] 档=${tier} 组=${groups.map((group) => group.key).join("+")} 档下界=${floor}\n`,
    );

    let allOk = true;
    let totalPass = 0;
    for (const group of groups) {
      /** 该组 TAP 实解析的 pass 数（`onSummary` 回填；失败时可能仍为 null）。 */
      let summary = null;
      let code = 1;
      try {
        const suite = resolveGroup(group);
        code = await runTapSuite({
          label: `tier:${tier}/${group.key}`,
          files: suite.files,
          env: suite.env,
          minPass: group.minPass,
          onSummary: (parsed) => {
            summary = parsed;
          },
        });
      } catch (error) {
        process.stderr.write(`[tier:${tier}/${group.key}] FAIL: ${error.message}\n`);
        code = 1;
      }
      if (code !== 0) allOk = false;
      totalPass += summary?.pass ?? 0;
    }

    // 档下界复核：用**实解析**的 pass 总和对照档下界（各组 minPass 已由
    // runTapSuite 各自锁死；这里再叠一层档级aggregate，两道判据互为冗余兜底）。
    if (allOk && totalPass < floor) {
      process.stderr.write(`[tier] FAIL: 档执行数 pass=${totalPass} < 下界 ${floor}\n`);
      allOk = false;
    }
    process.stdout.write(`[tier] 档=${tier} ${allOk ? "PASS ✅" : "FAIL ❌"} (pass=${totalPass}/${floor})\n`);
    process.exitCode = allOk ? 0 : 1;
  }
}
