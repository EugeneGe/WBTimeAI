/**
 * 测试套件的**唯一登记表**（`minPass` / 文件 / 夹具注入都只在这里写一次）。
 *
 * 为什么要有这张表：`test:smoke`、`test:conformance`、`test:legacy`、`test:all` 四个入口
 * 必须对「跑哪些文件、下界是多少」有**同一份**答案。若各入口各写一份，`test:all` 就会
 * 有一天悄悄少跑一组而没人发现 —— 那正是 V0.2.0 审计 #3 记的假绿形态（名字不变、
 * 覆盖面缩水）。这里集中登记后，聚合入口只是「遍历同一张表」。
 *
 * `minPass` 是**实测通过数**（不是宽松下界）：改用例数必须同步改这里。
 * 见 `scripts/lib/tap-runner.mjs` 头注。
 */

import { existsSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { REPO_ROOT, listTestFiles } from "./tap-runner.mjs";

/** conformance 夹具的注入变量名（与 `tenant-404.cases.mjs` 的 `HARNESS_ENV` 常量同名）。 */
export const CONFORMANCE_ENV = "WBTIME_CONFORMANCE_HARNESS";

/** conformance 夹具模块（导出 `createHarness()`）。 */
export const CONFORMANCE_HARNESS_FILE = "packages/e2e/tests/conformance/harness.mjs";

/**
 * py legacy 正向腿（`tests/e2e`）。
 *
 * 前置：本机 py 环境（harness 自己 spawn `scripts/selfproof/legacy_backend_launcher.py`）。
 * 实测 4 条 test（`auth` / `pagination` / `sse` 三文件）。
 */
export const LEGACY_FORWARD = Object.freeze({
  key: "legacy:forward",
  label: "legacy:forward",
  kind: "dir",
  dir: "packages/e2e/tests/e2e",
  // **必须显式给 `E2E_LEG`**：`_harness.mjs` 的 `LEG` 有默认值 `forward`，
  // 但"靠默认值"正是 reverse 腿幽灵绿的来源（见 LEGACY_REVERSE 的注释）。
  // 两条腿都写死自己的 leg，谁也不依赖另一条的默认值。
  env: { E2E_LEG: "forward" },
  minPass: 4,
  why: "py legacy 正向腿（DoD#4 四 case）",
});

/**
 * py legacy 反向腿（`tests/reverse`）。
 *
 * 反向腿验的是「进程 kill 后端口必须 ECONNREFUSED」—— 与正向腿的装配面不同，
 * 故单独一组、单独下界（实测 1 条）。
 */
export const LEGACY_REVERSE = Object.freeze({
  key: "legacy:reverse",
  label: "legacy:reverse",
  kind: "dir",
  dir: "packages/e2e/tests/reverse",
  // ⚠️ **`E2E_LEG=reverse` 缺一不可**（QA 独立验收抓到的真 P1）：
  // `reverse.test.mjs` 的用例是**条件注册**的（`if (runsLeg('reverse'))`）。不给这个
  // 环境变量时 `_harness.mjs` 的 `LEG` 默认 `forward` ⇒ 条件为假 ⇒ 文件里 **0 个用例**；
  // 而 `node --test` 会把「0 个子测试的文件」记成 `ok 1 - <文件路径>` ⇒ `# pass 1`
  // 满足 `minPass=1` ⇒ **幽灵绿**（实测 208ms，且 TAP 里只有文件路径、没有 `case-r-reverse-refused`）。
  // 所以这里**不准靠默认值**，必须显式声明本腿的 leg。
  env: { E2E_LEG: "reverse" },
  minPass: 1,
  why: "py legacy 反向腿（kill 后必须 ECONNREFUSED）",
});

/**
 * TS 后端冒烟（`tests/ts-backend`）：真进程 + 真端口（不是 `app.inject`）。
 * 实测 5 条 case（auth / pagination / sse / reverse / **refresh**）。
 */
export const SMOKE = Object.freeze({
  key: "smoke",
  label: "run-smoke",
  kind: "dir",
  dir: "packages/e2e/tests/ts-backend",
  // 4 → 5：FIX-10（V0.2.0 审计 #13）新增 `refresh.test.mjs`（轮换 + 旧 refresh 401）。
  minPass: 5,
  why: "TS 后端 5 case（真 TCP）",
});

/**
 * I-1 跨租户 404 conformance。
 *
 * `kind: "file"` 是刻意的：该文件叫 `*.cases.mjs`，**不匹配**任何 `*.test.mjs` glob ——
 * 审计 #3 里「从来没被执行过」的就是它。
 */
export const CONFORMANCE = Object.freeze({
  key: "conformance",
  label: "run-conformance",
  kind: "file",
  file: "packages/e2e/tests/conformance/tenant-404.cases.mjs",
  harness: CONFORMANCE_HARNESS_FILE,
  minPass: 11,
  why: "I-1 跨租户 404（3 前置 + 8 case）",
});

/** 全量（`test:all` 的覆盖面，顺序即执行顺序）。 */
export const ALL_GROUPS = Object.freeze([LEGACY_FORWARD, LEGACY_REVERSE, SMOKE, CONFORMANCE]);

/** legacy 两腿（`test:legacy` 的覆盖面）。 */
export const LEGACY_GROUPS = Object.freeze([LEGACY_FORWARD, LEGACY_REVERSE]);

/**
 * J-11 跨语言等价的 **PG 档**（`test:parity:pg`）。
 *
 * 与上面四组的区别：它**不在** `test:all` 里 —— 它需要一台可达的 PG（`WBTIME_PG_URL`），
 * 而本机隧道已断、PG 主机 2026-10-22 到期（见 `02-施工/00-施工期裁定.md` R-3x）。
 * 因此本组由 `scripts/run-parity-pg.mjs` 单独驱动：**缺 URL ⇒ exit 1**（不 skip、不算绿）。
 *
 * `files` 与 sqlite 档是**同一个**测试文件 —— 方言由 `WBTIME_PARITY_DIALECT` 决定，
 * 测试名会带上 `dialect=pg`，绿的时候能看出跑的是哪一档。
 */
export const PARITY_PG = Object.freeze({
  key: "parity:pg",
  label: "run-parity-pg",
  kind: "file",
  file: "apps/api/tests/parity/j11-19ops.test.mjs",
  env: { WBTIME_PARITY_DIALECT: "pg" },
  // 3 = 主用例（19 op）+ 结构级反例自检 + 值级反例自检。
  minPass: 3,
  why: "J-11 19 op 的 PG 档（需 WBTIME_PG_URL）",
});

/**
 * 把一个登记的套件解析成 {@link import("./tap-runner.mjs").runTapSuite} 的入参。
 *
 * @param {object} group 登记表里的一项（`ALL_GROUPS` / `PARITY_PG` 等）。
 * @returns {{label: string, files: string[], env: Record<string, string>, minPass: number}}
 * @throws {Error} 目录缺文件 / 夹具文件不存在（**不**降级成空跑）。
 */
export function resolveGroup(group) {
  if (group.kind === "dir") {
    const files = listTestFiles(group.dir);
    if (files.length === 0) {
      throw new Error(`[suites] ${group.key}: ${group.dir} 下没有任何测试文件`);
    }
    return { label: group.label, files, env: { ...(group.env ?? {}) }, minPass: group.minPass };
  }

  if (group.kind === "file") {
    const absolute = path.join(REPO_ROOT, group.file);
    if (!existsSync(absolute)) {
      throw new Error(`[suites] ${group.key}: 文件不存在：${absolute}`);
    }
    const env = { ...(group.env ?? {}) };
    if (group.harness !== undefined) {
      const harnessPath = path.join(REPO_ROOT, group.harness);
      if (!existsSync(harnessPath)) {
        throw new Error(`[suites] ${group.key}: 夹具文件不存在：${harnessPath}`);
      }
      // `pathToFileURL` 产出 `file:///D:/...`（win32）/ `file:///home/...`（POSIX），
      // 两种都是 `import()` 能吃的说明符 —— 裸路径在 Windows 上会被当成包名。
      const url = pathToFileURL(harnessPath).href;
      if (!url.startsWith("file://")) {
        throw new Error(`[suites] ${group.key}: 夹具说明符不是 file:// URL（实测 ${url}）`);
      }
      env[CONFORMANCE_ENV] = url;
    }
    return { label: group.label, files: [absolute], env, minPass: group.minPass };
  }

  throw new Error(`[suites] 未知的套件形态：${String(group.kind)}（只支持 dir / file）`);
}
