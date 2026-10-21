#!/usr/bin/env node
/**
 * `pnpm test:conformance` —— I-1 跨租户 404 一致性套件（4 族 × {read,write} = 8 case
 * + 3 条登记表/契约前置 = **11 个可执行 test**）。
 *
 * 两条与"假绿"直接相关的硬要求（V0.2.0 审计 #3）：
 *
 *  1. **文件路径显式**：只跑 `tests/conformance/tenant-404.cases.mjs` 这一个文件。
 *     它不叫 `*.test.mjs`，所以旧的「`tests` 下递归 `*.test.mjs`」那条通道
 *     从来**没有**执行过它 —— 却照样打印 `# pass 0 / exit 0`。这里用显式路径，永不靠 glob。
 *
 *  2. **夹具必须显式注入**：`WBTIME_CONFORMANCE_HARNESS` 指向
 *     `packages/e2e/tests/conformance/harness.mjs` 的 **`file://` 绝对 URL**
 *     （由 `scripts/lib/suites.mjs` 的 `resolveGroup()` 用 `pathToFileURL` 生成）。
 *     为什么必须是 URL 而不是裸路径：`cases.mjs` 用 `await import(specifier)` 加载夹具，
 *     而 ESM 在 Windows 上拒绝 `D:\...` 这类裸盘符路径（会被当成包名 ⇒
 *     ERR_MODULE_NOT_FOUND）。用 `pathToFileURL()` 后三平台（win32 / linux / darwin）一致。
 *     未注入时 8 个 case 会各自 `assert.fail("未验证（依赖 T2-07 未完成）")` —— 那是**红**，
 *     不是 skip；本脚本的职责就是把"红"变成默认行为，而不是靠人记得加参数。
 *
 * 判据：TAP `# pass N` 必须 **≥ 11**（3 条前置 + 8 个 case）且 `# fail 0`。
 * 任何一条 case 因夹具缺失而 assert.fail，`# fail` 就非 0 ⇒ 红。
 *
 * 文件清单与 `minPass` 的唯一来源是 `scripts/lib/suites.mjs` 的 `CONFORMANCE` ——
 * 与 `test:all` 共用同一份登记，避免「聚合入口少跑一组还叫全绿」。
 *
 * 用法：`node scripts/run-conformance.mjs`（CI 用 `pnpm test:conformance`）。
 */

import { CONFORMANCE, CONFORMANCE_ENV, resolveGroup } from "./lib/suites.mjs";
import { runTapSuite } from "./lib/tap-runner.mjs";

try {
  const suite = resolveGroup(CONFORMANCE);
  process.stdout.write(`[run-conformance] harness=${suite.env[CONFORMANCE_ENV]}\n`);
  process.exitCode = await runTapSuite(suite);
} catch (error) {
  process.stderr.write(`[run-conformance] FAIL: ${error.message}\n`);
  process.exitCode = 1;
}
