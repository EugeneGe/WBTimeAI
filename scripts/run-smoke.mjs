#!/usr/bin/env node
/**
 * `pnpm test:smoke` —— TS 后端冒烟（4 个 case，真进程 + 真端口）。
 *
 * 覆盖：`packages/e2e/tests/ts-backend/*.test.mjs`（登记在 `scripts/lib/suites.mjs`
 * 的 `SMOKE`，文件清单与 `minPass` 都从那里读 —— 单一来源）
 *   ① `case-1-ts-auth`（register 201 / login 200 / 错口令 401 / 5 错后 423）
 *   ② `case-2-ts-pagination`（列表完整性 + 确定性）
 *   ③ `case-3-ts-sse`（真实长连接 SSE 夹具：真建流/真读帧/真断开/零泄漏 + 后端 run 端点确缺）
 *   ④ `case-4-ts-reverse`（kill 后端口 ECONNREFUSED）
 *
 * 前置：`apps/api/dist/main.js` 必须已编译（`pnpm test:ts` 会先 build；
 * 单独跑本脚本前先 `pnpm --filter "@wbtime/api..." build`）。缺构建产物时冒烟会以
 * "进程在就绪前退出"红掉，那是**真红**（不是假绿），符合"缺证据不许绿"的口径。
 *
 * 判据（不是"exit 0 就算过"）：TAP `# pass N` 必须 **≥ 4** 且 `# fail 0`。
 * 理由见 `scripts/lib/tap-runner.mjs` 头注（0 文件匹配 = 假绿）。
 *
 * 用法：`node scripts/run-smoke.mjs`（CI 用 `pnpm test:smoke`）。
 */

import { resolveGroup, SMOKE } from "./lib/suites.mjs";
import { runTapSuite } from "./lib/tap-runner.mjs";

try {
  process.exitCode = await runTapSuite(resolveGroup(SMOKE));
} catch (error) {
  process.stderr.write(`[run-smoke] FAIL: ${error.message}\n`);
  process.exitCode = 1;
}
