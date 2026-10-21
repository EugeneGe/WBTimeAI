#!/usr/bin/env node
/**
 * `pnpm test:legacy` —— py legacy 两个腿（**子集入口**，被 `test:all` 复用）。
 *
 * 两条腿分开跑、各自断言执行数，因为她们的**前置条件与装配面不同**：
 *
 * | 组 | 目录 | `E2E_LEG` | 前置 | 实测 pass |
 * |---|---|---|---|---|
 * | `legacy:forward` | `tests/e2e` | `forward` | 本机 py 环境（harness 自己 spawn `scripts/selfproof/legacy_backend_launcher.py`） | 4 |
 * | `legacy:reverse` | `tests/reverse` | **`reverse`** | 同上（反向腿：kill 后必须 ECONNREFUSED） | 1 |
 *
 * ⚠️ **`E2E_LEG` 必须显式给**（QA 独立验收抓到的真 P1，2026-10-21）：
 * `tests/reverse/reverse.test.mjs` 的用例是**条件注册**的（`if (runsLeg('reverse'))`）。
 * 不传 `E2E_LEG=reverse` 时 `_harness.mjs` 的 `LEG` 默认 `forward` ⇒ 条件为假 ⇒
 * 文件里 0 个用例；而 `node --test` 把「0 个子测试的文件」记成 `ok 1 - <文件路径>`
 * ⇒ `# pass 1` 满足 `minPass=1` ⇒ **幽灵绿**（实测 208ms、TAP 里没有 `case-r-reverse-refused`）。
 * 现在两条腿的 `E2E_LEG` 都写死在 `scripts/lib/suites.mjs` 里，**不依赖任何默认值**；
 * `tap-runner` 另有一道「文件级通过不算用例」的判据兜底。
 *
 * 为什么不用一个 `node --test "tests/**"` 了事（V0.2.0 审计 #3 的教训）：
 * 一个 glob 把两组混在一起跑，**任何一组匹配 0 文件都看不出来** —— 汇总里只有总数。
 * 拆成两组各自 `minPass`，少一组就红。
 *
 * 文件清单、`minPass` 与 `E2E_LEG` 的唯一来源是 `scripts/lib/suites.mjs`（`LEGACY_GROUPS`）。
 *
 * 用法：
 *   node scripts/run-legacy.mjs                  # 两条腿都跑（默认，等价于 `--leg both`）
 *   node scripts/run-legacy.mjs --leg forward     # 只跑正向腿（`packages/e2e` 的 `test` / `test:forward`）
 *   node scripts/run-legacy.mjs --leg reverse     # 只跑反向腿（`test:reverse`）
 *
 * CI 的 `ts-integration` job **不**跑本脚本：它需要 py 环境，属于离线档 / selfproof 档的
 * 证据面（本版仍由 `python scripts/selfproof/run_selfproof.py` 与本地验证据承担）。
 */

import { LEGACY_GROUPS, resolveGroup } from "./lib/suites.mjs";
import { runTapSuite } from "./lib/tap-runner.mjs";

/**
 * 解析 `--leg` 参数。
 *
 * @param {string[]} argv `process.argv.slice(2)`。
 * @returns {"both"|"forward"|"reverse"} 本次要跑的腿。
 * @throws {Error} 取值非法（**不**静默回落到 both —— 打错字却"跑了两条腿"会让人误判）。
 */
export function parseLeg(argv) {
  const index = argv.indexOf("--leg");
  if (index === -1) return "both";
  const value = String(argv[index + 1] ?? "").trim();
  if (value === "both" || value === "forward" || value === "reverse") return value;
  throw new Error(`--leg 只接受 forward / reverse / both，实测 ${JSON.stringify(value)}`);
}

/** 本次要跑的腿。 */
const leg = parseLeg(process.argv.slice(2));

/** 只保留与本次腿匹配的组（`both` 全保留）。 */
const groups = LEGACY_GROUPS.filter((group) => {
  if (leg === "both") return true;
  return group.key === `legacy:${leg}`;
});

if (groups.length === 0) {
  process.stderr.write(`[run-legacy] FAIL: --leg ${leg} 没有匹配的登记组（检查 suites.mjs）\n`);
  process.exitCode = 1;
} else {
  let failed = 0;
  for (const group of groups) {
    let code = 1;
    try {
      code = await runTapSuite(resolveGroup(group));
    } catch (error) {
      process.stderr.write(`[${group.label}] FAIL: ${error.message}\n`);
      code = 1;
    }
    if (code !== 0) failed += 1;
  }
  process.exitCode = failed === 0 ? 0 : 1;
}
