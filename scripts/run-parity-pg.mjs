#!/usr/bin/env node
/**
 * `pnpm test:parity:pg` —— J-11 的 **PG 档**（V0.2.0 审计 #2 / FIX-09）。
 *
 * 这个脚本的核心职责不是"跑测试"，而是**让「未验证」这件事本身有明确的退出码与话术**：
 *
 * | 情形 | 行为 |
 * |---|---|
 * | 缺 `WBTIME_PG_URL` | **exit 1**，打印起隧道命令 + 「本轮未验证（PG 主机 2026-10-22 到期）」 |
 * | 有 URL 但连不上 / 库非空且未授权 reset | 红（由 `preparePgDatabase()` 的四道闸拒绝） |
 * | 有 URL 且能跑 | 跑 19 op，断言 `# fail 0` 且 `# pass ≥ 3`，输出方言与 pass 数 |
 *
 * **禁止**的两个做法（本轮明确不做）：
 *   * 缺 env 时 skip / exit 0 —— 那会把"没验证"伪装成"验证过"；
 *   * 缺 env 时自动退回 SQLite —— 那会让"PG 档"这个词失去意义。
 *
 * 为什么单列一个脚本而不是塞进 `test:all`：PG 档依赖外部主机（且**明天到期**），
 * 塞进主链会让「所有人本地跑 test:all」长期常红，从而诱导后人加 `continue-on-error`。
 * 反过来，它也不进 CI（`ts-integration` job）—— 理由同上，见 `.github/workflows/ci.yml`。
 *
 * 用法：
 *   pnpm test:parity:pg
 *   # 需要（口令见 gitignored 的 docs/*服务器总览.md，**不入库**）：
 *   #   export WBTIME_PG_URL='postgres://<PG_USER>:<PG_PASSWORD>@127.0.0.1:5433/wbtime_ai_parity'
 */

import { PG_RESET_ENV, describeReset, parityResetEnv } from "./lib/parity-env.mjs";
import { PARITY_PG, resolveGroup } from "./lib/suites.mjs";
import { runTapSuite } from "./lib/tap-runner.mjs";

/** PG 连接串环境变量名（与 `apps/api/tests/parity/j11-harness.mjs` 的 `PG_URL_ENV` 同名）。 */
const PG_URL_ENV = "WBTIME_PG_URL";

/** PG 主机环境变量名（与 harness 的 `PG_HOST_ENV` 同名）。 */
const PG_HOST_ENV = "WBTIME_PG_HOST";

/**
 * 起隧道命令（**不含任何密码 / 具体地址**）。
 *
 * 本脚本**不内置**主机地址：它和 SSH 用户名、口令同属 `docs/*服务器总览.md` 那一类信息，
 * 而那份文档是 **gitignored** 的 —— 把地址写进源码等于绕过那条 gitignore 的意图。
 * 未设置 `WBTIME_PG_HOST` 时保留 `<PG_HOST>` 占位符，提示文案仍可整段复制后替换。
 */
const TUNNEL_HINT = [
  "# PG 只监听远端 127.0.0.1:5432 ⇒ 必须经 SSH 隧道（本地 5433 → 远端 5432）",
  `ssh -N -L 5433:127.0.0.1:5432 <SSH_USER>@${pgHostForDisplay()}`,
  "# <SSH_USER> / <PG_USER> / 口令 / 主机：见 gitignored 的 docs/*服务器总览.md（永久不入库）",
  `#   主机也可用 ${PG_HOST_ENV} 覆盖（本脚本不内置任何地址）`,
  "#   连续失败会触发远端 fail2ban，登录试错留给窗口期集中执行（docs/环境基线.md §4.1）",
  "# 隧道起来后：",
  "export WBTIME_PG_URL='postgres://<PG_USER>:<PG_PASSWORD>@127.0.0.1:5433/wbtime_ai_parity'",
].join("\n");

/**
 * 展示用的 PG 主机：环境变量有值就用它，否则用占位符。
 *
 * @returns {string} 可打印的主机串（**不含**用户名/口令）。
 */
function pgHostForDisplay() {
  const host = String(process.env[PG_HOST_ENV] ?? "").trim();
  return host === "" ? "<PG_HOST>" : host;
}

const pgUrl = String(process.env[PG_URL_ENV] ?? "").trim();

if (pgUrl === "") {
  process.stderr.write(
    [
      `[run-parity-pg] FAIL: 未设置 ${PG_URL_ENV}。`,
      "",
      "PG 档在 2026-10-21 已于 dev 服务器实测 19/19（见 T2-11.md 的「双档实测」口径）；",
      "但**本次没有跑**，所以本次结论只能是：**仅 SQLite 档等价；PG 档未复跑**。",
      "不要把「历史实测通过」当作「本次通过」，也不要自动退回 SQLite 后仍叫它 PG 档。",
      "",
      TUNNEL_HINT,
      "",
      "（缺 URL ⇒ exit 1。这是刻意的：skip 或 exit 0 都会把「没验证」伪装成「验证过」。）",
    ].join("\n") + "\n"
  );
  process.exitCode = 1;
} else {
  // 只打印"是否设置"与主机部分，**不打印**连接串本身（里面通常含口令）。
  process.stdout.write(
    `[run-parity-pg] ${PG_URL_ENV} 已设置（host=${safeHost(pgUrl)}）⇒ 开始跑 PG 档\n`
  );
  // ── RESET 决策（默认开；`WBTIME_PG_RESET=0` 时尊重用户）─────────────────
  // 为什么默认开：本文件有 3 个 test 各自建夹具，PG 档共用同一个 parity 库，
  // 不清库则第 2、3 个必然撞 harness 闸 2（非空库）⇒ 官方命令会得到 1 过 2 红。
  // 安全边界不变：harness 仍强制库名含 parity、共享库 wbtime_ai 直接拒、
  // DROP 只限 61 张已知表 —— **不因"方便"放宽任何一道闸**。
  const reset = parityResetEnv();
  process.stdout.write(`${describeReset(reset)}\n`);
  try {
    const suite = resolveGroup(PARITY_PG);
    process.exitCode = await runTapSuite({
      ...suite,
      env: { ...suite.env, ...reset.env },
    });
    if (process.exitCode === 0) {
      process.stdout.write(
        "[run-parity-pg] **双档实测通过**（本次运行）。台账口径见 T2-11.md「双档实测」一节：" +
          "SQLite 19/19 + PG 19/19；PG 档含 1 处登记式输入替换（create_tool_permission.tool_id）；" +
          "**仍未验证**：py 侧在 PG 上的重放。\n"
      );
    }
  } catch (error) {
    process.stderr.write(`[run-parity-pg] FAIL: ${error.message}\n`);
    process.exitCode = 1;
  }
}

/**
 * 从连接串里取 `host:port/db`（**去掉** user/password 段）。
 *
 * @param {string} url PG 连接串。
 * @returns {string} 可安全打印的定位信息。
 */
function safeHost(url) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}:${parsed.port}/${parsed.pathname.replace(/^\//, "")}`;
  } catch {
    return "<无法解析的连接串>";
  }
}
