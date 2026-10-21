#!/usr/bin/env node
/**
 * FIX-08 · 依赖审计门禁（20xx 审计 #6「CI 零 SAST/SCA」的可落地部分）。
 *
 * 为什么不能照审计报告直接接 `pnpm audit --audit-level high`
 * --------------------------------------------------------------
 * 实测（2026-10-21，本仓）：全量 audit 有 **2 critical + 3 high**，但**全部落在
 * `apps/web` 的 devDependencies**（`vite` / `tinypool` / `braces` 链）。而 Q-5 与
 * 「前端 0 改动」是本版硬边界 —— 升级即破版。于是"接一个会在本版常红的门禁"等于
 * 逼后人加 `continue-on-error`（本仓 §4.7-4 明确禁止），那正是要消灭的东西。
 *
 * 因此把判据拆成两档：
 *   * **prod 档**（`--prod`）：high + critical 必须为 **0**。这一档**参与判定**，
 *     当前实测 0/0（213 个生产依赖），能绿也能红 —— 是真门禁。
 *   * **full 档**（不加 `--prod`）：**仅报告**，打印 high/critical 计数 + 一行 Q-5 说明，
 *     **永不因此失败**。它的作用是"留证据"：让"前端 devDeps 有 2 critical"这件事
 *     在每次 CI 里都可见，而不是靠人记得。
 *
 * 判定与执行分离
 * -------------
 * `parseAuditReport` / `decide` 都是**纯函数**，故 `--self-test` 可以用内置夹具证明
 * "含 high ⇒ exit 1"与"干净 ⇒ exit 0"两个方向都真的成立 —— 判据本身有红证，
 * 而不是"跑一次看起来是绿的"。真实跑则必须 exit 0。
 *
 * 退出码：0 = 通过 · 1 = 有阻断级漏洞 · 2 = **审计端点不可达 / JSON 非法**
 * （第 2 种必须独立于 1：把"查不到"当成"通过"是本仓 K-11 的形态，绝对不能混）。
 */

import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** 仓库根（`scripts/` 的上一级）。 */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** 参与判定的严重级：只有这两级会阻断。 */
export const BLOCKING_SEVERITIES = /** @type {const} */ (["high", "critical"]);

/** 报告里的全部严重级（顺序固定，便于打印对齐）。 */
export const ALL_SEVERITIES = /** @type {const} */ (["info", "low", "moderate", "high", "critical"]);

/** 退出码：通过。 */
export const EXIT_PASS = 0;
/** 退出码：存在 high/critical。 */
export const EXIT_BLOCKING = 1;
/** 退出码：端点不可达 / JSON 非法 / 报告缺 metadata。 */
export const EXIT_UNAVAILABLE = 2;

/**
 * 默认 registry。
 *
 * 必须显式指定 npmjs：npmmirror 之类镜像**没有 `/security/advisories/bulk` 端点**，
 * 走镜像会拿到 404 而不是漏洞数据 —— 那会把"查不到"伪装成"没问题"。
 * 需要换源时用 `WBTIME_AUDIT_REGISTRY`（例如 CI 内网代理）。
 */
export const DEFAULT_REGISTRY = "https://registry.npmjs.org";

/** Q-5 说明（full 档打印这一行；它是口径，不是注释）。 */
export const Q5_NOTE =
  "apps/web 的 devDependencies（vite / tinypool / braces）受 Q-5「1.0 内禁框架升级 + 前端 0 改动」冻结，" +
  "升级不在本版；本行仅为留证，不参与判定。";

/**
 * 解析 `pnpm audit --json` 的输出。
 *
 * @param {string} raw 进程 stdout。
 * @returns {{ok: true, counts: Record<string, number>, blocking: Array<object>}
 *   | {ok: false, error: string}}
 */
export function parseAuditReport(raw) {
  let document;
  try {
    document = JSON.parse(String(raw));
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return { ok: false, error: `audit 输出不是合法 JSON（${reason}）—— 端点不可达或被代理改写` };
  }

  const vulnerabilities = document?.metadata?.vulnerabilities;
  if (vulnerabilities === null || typeof vulnerabilities !== "object") {
    return {
      ok: false,
      error:
        "audit 报告缺少 metadata.vulnerabilities —— 不是 pnpm audit 的 JSON 报告" +
        "（可能是 404 页面、认证提示或 registry 错误）",
    };
  }

  /** @type {Record<string, number>} */
  const counts = {};
  for (const severity of ALL_SEVERITIES) {
    const value = Number(vulnerabilities[severity] ?? 0);
    counts[severity] = Number.isFinite(value) ? value : 0;
  }

  // 明细只对阻断级收集（要打印 module / severity / paths）。
  // 注意：清单来自 advisories，判定依据来自 metadata —— 两者不一致时以 metadata 为准
  // （见 decide()：数量 > 0 就阻断，即使 advisories 缺 severity 字段）。
  const blocking = [];
  const advisories = document?.advisories ?? {};
  for (const advisory of Object.values(advisories)) {
    const severity = String(advisory?.severity ?? "unknown");
    if (!BLOCKING_SEVERITIES.includes(/** @type {any} */ (severity))) continue;
    const findings = Array.isArray(advisory?.findings) ? advisory.findings : [];
    blocking.push({
      module: String(advisory?.module_name ?? advisory?.module ?? "(unknown)"),
      severity,
      title: String(advisory?.title ?? "(no title)"),
      versions: findings.map((finding) => String(finding?.version ?? "?")),
      paths: findings.flatMap((finding) =>
        Array.isArray(finding?.paths) ? finding.paths.map(String) : []
      ),
      url: String(advisory?.url ?? ""),
    });
  }

  return { ok: true, counts, blocking };
}

/**
 * 由解析结果给出**唯一**判定（纯函数 —— self-test 直接断言它）。
 *
 * @param {ReturnType<typeof parseAuditReport>} report
 * @returns {{ok: boolean, exitCode: number, problems: string[]}}
 */
export function decide(report) {
  if (!report.ok) {
    return { ok: false, exitCode: EXIT_UNAVAILABLE, problems: [report.error] };
  }
  const blockingCount = BLOCKING_SEVERITIES.reduce(
    (total, severity) => total + (report.counts[severity] ?? 0),
    0
  );
  if (blockingCount > 0) {
    return {
      ok: false,
      exitCode: EXIT_BLOCKING,
      problems: [`high + critical = ${blockingCount}（prod 档必须为 0）`],
    };
  }
  return { ok: true, exitCode: EXIT_PASS, problems: [] };
}

/**
 * 跑一次 `pnpm audit --json`。
 *
 * @param {{prod: boolean, registry: string}} options
 * @returns {{stdout: string, stderr: string, exitCode: number}}
 */
export function runAudit({ prod, registry }) {
  const args = ["audit", "--json", "--registry", registry];
  if (prod) args.push("--prod");
  try {
    const stdout = execFileSync("pnpm", args, {
      cwd: REPO_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      // Windows 上 pnpm 是 .cmd 垫片，非 shell 模式解析不到（与 check_depcruiser 同一手法）。
      shell: process.platform === "win32",
      // 报告随依赖树增长；默认 1 MiB 会 ENOBUFS 把"绿"变成"解析失败"
      // （check_depcruiser 今天刚踩过同一个坑）。
      maxBuffer: 32 * 1024 * 1024,
    });
    return { stdout, stderr: "", exitCode: 0 };
  } catch (error) {
    const status = typeof error?.status === "number" ? error.status : 1;
    return {
      stdout: String(error?.stdout ?? ""),
      stderr: String(error?.stderr ?? ""),
      // pnpm audit 用 exit 1 表示"发现漏洞"，这是**正常**结果；真正不可达时
      // stdout 里没有 JSON（下面的 parse 会把它判成 EXIT_UNAVAILABLE）。
      exitCode: status,
    };
  }
}

/** 打印一行计数。 */
function printCounts(label, counts) {
  const parts = ALL_SEVERITIES.map((severity) => `${severity}=${counts[severity] ?? 0}`);
  console.log(`[audit-gate] ${label}：${parts.join(" ")}`);
}

/** 真实跑：prod 参与判定，full 仅报告。 */
function runReal() {
  const registry = process.env["WBTIME_AUDIT_REGISTRY"] || DEFAULT_REGISTRY;
  console.log(`[audit-gate] registry=${registry}`);

  // ---- prod 档（判定）----
  const prodRun = runAudit({ prod: true, registry });
  const prodReport = parseAuditReport(prodRun.stdout);
  if (!prodReport.ok) {
    console.error(`[audit-gate] FAIL(EXIT_UNAVAILABLE)：${prodReport.error}`);
    if (prodRun.stderr.trim() !== "") {
      console.error(`[audit-gate] pnpm stderr：${prodRun.stderr.trim().split("\n").slice(0, 5).join("\n")}`);
    }
    console.error(
      "[audit-gate] 「查不到」不等于「没问题」—— 本门禁拒绝把它当成通过（退出码 2）。"
    );
    return EXIT_UNAVAILABLE;
  }

  printCounts("prod 档", prodReport.counts);
  const prodDecision = decide(prodReport);
  for (const finding of prodReport.blocking) {
    console.error(
      `[audit-gate]   BLOCKING ${finding.severity} · ${finding.module}@${finding.versions.join(",")} · ${finding.title}`
    );
    for (const path of finding.paths.slice(0, 5)) console.error(`[audit-gate]     path: ${path}`);
    if (finding.url !== "") console.error(`[audit-gate]     advisory: ${finding.url}`);
  }
  console.log(
    `[audit-gate] prod 档：high+critical = ${(prodReport.counts.high ?? 0) + (prodReport.counts.critical ?? 0)}` +
      ` ⇒ ${prodDecision.ok ? "PASS" : "FAIL"}`
  );

  // ---- full 档（仅报告，永不失败）----
  const fullRun = runAudit({ prod: false, registry });
  const fullReport = parseAuditReport(fullRun.stdout);
  if (!fullReport.ok) {
    // full 档不参与判定，但"查不到"仍要可见 —— 用 warn 打印，不改退出码。
    console.warn(`[audit-gate] full 档取不到报告（仅报告档，不影响判定）：${fullReport.error}`);
  } else {
    printCounts("full 档（仅报告）", fullReport.counts);
    console.log(
      `[audit-gate] full 档：high=${fullReport.counts.high ?? 0} critical=${fullReport.counts.critical ?? 0}` +
        `（不参与判定）`
    );
    console.log(`[audit-gate] full 档说明：${Q5_NOTE}`);
    for (const finding of fullReport.blocking.slice(0, 10)) {
      console.log(
        `[audit-gate]   report-only ${finding.severity} · ${finding.module}@${finding.versions.join(",")}`
      );
    }
  }

  for (const problem of prodDecision.problems) console.error(`[audit-gate] FAIL: ${problem}`);
  console.log(`[audit-gate] ${prodDecision.ok ? "PASS" : "FAIL"}`);
  return prodDecision.exitCode;
}

// ---------------------------------------------------------------------------
// self-test：证明判据真的会红，也真的会绿
// ---------------------------------------------------------------------------

/** 夹具：含 1 high + 1 critical（必须阻断）。 */
const FIXTURE_BLOCKING = {
  metadata: { vulnerabilities: { info: 0, low: 1, moderate: 2, high: 1, critical: 1 } },
  advisories: {
    9001: {
      module_name: "fixture-pkg",
      severity: "critical",
      title: "fixture: remote code execution",
      findings: [{ version: "1.2.3", paths: ["apps__api>fixture-pkg@1.2.3"] }],
      url: "https://example.invalid/advisories/GHSA-fixture",
    },
  },
};

/** 夹具：干净（必须通过）。 */
const FIXTURE_CLEAN = {
  metadata: { vulnerabilities: { info: 0, low: 0, moderate: 3, high: 0, critical: 0 } },
  advisories: {},
};

/** 夹具：数量在 metadata 里、明细缺失（拷问"以 metadata 为准"）。 */
const FIXTURE_COUNT_ONLY = {
  metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 2, critical: 0 } },
  advisories: {},
};

function selfTest() {
  const results = [];
  const check = (name, condition, detail = "") => {
    results.push({ name, ok: Boolean(condition), detail });
  };

  const blocking = parseAuditReport(JSON.stringify(FIXTURE_BLOCKING));
  check("含 high/critical 的夹具能被解析", blocking.ok);
  check("含 high/critical ⇒ exit 1（红）", decide(blocking).exitCode === EXIT_BLOCKING, `实际 ${decide(blocking).exitCode}`);
  check(
    "阻断级明细带 module/severity/paths",
    blocking.ok && blocking.blocking[0]?.module === "fixture-pkg" && blocking.blocking[0]?.paths.length === 1
  );

  const clean = parseAuditReport(JSON.stringify(FIXTURE_CLEAN));
  check("干净夹具 ⇒ exit 0（绿）", decide(clean).exitCode === EXIT_PASS, `实际 ${decide(clean).exitCode}`);

  const countOnly = parseAuditReport(JSON.stringify(FIXTURE_COUNT_ONLY));
  check(
    "只有 metadata 计数、无 advisories 明细时仍阻断（metadata 是判定权威）",
    decide(countOnly).exitCode === EXIT_BLOCKING
  );

  check("非 JSON ⇒ exit 2（不许当通过）", decide(parseAuditReport("<html>404</html>")).exitCode === EXIT_UNAVAILABLE);
  check("缺 metadata ⇒ exit 2", decide(parseAuditReport(JSON.stringify({ advisories: {} }))).exitCode === EXIT_UNAVAILABLE);
  check("空串 ⇒ exit 2", decide(parseAuditReport("")).exitCode === EXIT_UNAVAILABLE);
  check(
    "moderate 不阻断（与「只拦 high/critical」口径一致）",
    decide(parseAuditReport(JSON.stringify(FIXTURE_CLEAN))).exitCode === EXIT_PASS
  );

  for (const item of results) {
    console.log(`[audit-gate:self-test] ${item.ok ? "[OK]" : "[FAIL]"} ${item.name}${item.detail ? ` (${item.detail})` : ""}`);
  }
  const failed = results.filter((item) => !item.ok);
  console.log(
    `[audit-gate:self-test] ${failed.length === 0 ? "PASS" : "FAIL"}：${results.length - failed.length}/${results.length}`
  );
  return failed.length === 0 ? EXIT_PASS : EXIT_BLOCKING;
}

const argv = process.argv.slice(2);
if (argv.includes("--self-test")) {
  process.exit(selfTest());
} else if (argv.length > 0) {
  console.error(`[audit-gate] 未知参数：${argv.join(" ")}（支持 --self-test）`);
  process.exit(EXIT_UNAVAILABLE);
} else {
  process.exit(runReal());
}
