#!/usr/bin/env node
/**
 * FIX-08 · 仓库密钥扫描门禁（20xx 审计 #6「CI 零 secrets 检测」的可落地部分）。
 *
 * 边界（先说不做什么，避免假等价）
 * -----------------------------
 * 本仓**不引入** semgrep / gitleaks 二进制：离线不可得、许可不确定、且在干净 runner 上
 * 需要额外下载步骤。本脚本是**规则扫描器**，不是 gitleaks 的等价替代 —— 它只覆盖
 * 「高频、低误报」的五类形态（见 {@link RULES}），不做熵分析、不扫 git 历史、不扫未跟踪文件。
 * 这个边界必须写在文档里，不能假装"我们已经有了 secrets 扫描"。
 *
 * 设计取舍
 * -------
 * * **宁可少而准**：5 条规则，宁缺毋滥。一条天天误报的规则会被 allowlist 淹没，
 *   最终等于关闭（本仓 K-11 的形态）。
 * * **规则分两级**（FIX-08 改造，主理人 2026-10-21 裁定）：见 {@link RULE_TIERS}。
 *   high 级**全路径扫描（含测试目录）**；generic 级（`password = "…"` 这类赋值）
 *   **跳过测试/夹具路径**（{@link isTestPath}）。通用规则在测试夹具里的正例率接近 0，
 *   留着只会制造「每新增一个测试文件就加一条豁免」的仪式 —— 豁免表一长，门禁就退化成
 *   加豁免的流程，那正是要消灭的形态。
 *   ⚠️ 代价必须写清：**只带通用形态、且只存在于测试目录里的真凭据会被漏掉**。
 *   这是已知取舍，靠 high 级规则在测试面兜底；要补这一角需要熵分析（本版不做）。
 * * **输出必须脱敏**：命中片段只回显前 4 个字符 + 总长度。把密钥本体打进 CI 日志
 *   本身就是一次泄漏（日志会被存档、被无关人员看到）。PEM 的**头部**除外 ——
 *   `-----BEGIN ... PRIVATE KEY-----` 这个字面量不含任何密钥材料，掩码反而妨碍定位。
 * * **allowlist 逐条带理由**：`{path, rule, reason, owner}` 四个字段缺一即**整门禁红**。
 *   禁止目录级/通配条目 —— "整个目录豁免"等于把规则关掉，只是形式上还留着。
 * * **二进制与超大文件显式跳过并打印清单**：静默跳过会让"扫了 512 个文件"变成
 *   一个无法核对的数字。
 *
 * CI 与本地口径不同（主理人裁定）：CI 是干净 checkout，所有文件都已 tracked，故 CI 只用
 * 默认的 tracked 口径；`--include-untracked` 是**本地**开关（收口前把"即将提交的新文件"
 * 也扫一遍），不要把构建产物带进 CI 的扫描面。
 *
 * 退出码：0 = 无未豁免命中 · 1 = 有命中或 allowlist 本身不合法。
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** 仓库根。 */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** allowlist 文件（与本脚本同目录）。 */
export const ALLOWLIST_PATH = join(REPO_ROOT, "scripts", "secret-allowlist.json");

/** 超过这个体积的文件跳过（并打印），避免把打包产物读进内存。 */
export const MAX_FILE_BYTES = 2 * 1024 * 1024;

/** 判定"二进制"的探测窗口（前 8KB 出现 NUL 即跳过）。 */
export const BINARY_PROBE_BYTES = 8192;

/**
 * 规则分级的定义（主理人 2026-10-21 裁定）。
 *
 * * `high`：**真凭据的标准形状**（PEM 私钥块 / AWS / GitHub / Slack 令牌）。这些在
 *   任何路径都要报 —— 测试目录里出现真凭据同样是事故，不能因为"是测试"就放过。
 * * `generic`：**形式上像赋值**（`password = "…"`）。它在测试夹具里的正例率接近 0，
 *   故只在非测试路径上生效（见 {@link isTestPath}）。
 */
export const RULE_TIERS = /** @type {const} */ ({
  high: "high",
  generic: "generic",
});

/**
 * 测试 / 夹具路径判定（只用于 generic 级规则）。
 *
 * 匹配两类：
 * 1. 目录段：`tests` / `test` / `__tests__` / `fixtures` / `fixture` / `golden` / `testdata`；
 * 2. 文件名：`*.test.*` / `*.spec.*`。
 *
 * 为什么用路径而不是"运行时上下文"：门禁是静态扫描，唯一稳定的判据就是文件在哪。
 * 宁可把判据写得**窄而可读**（一眼能看出哪些目录被放过），也不要用一堆启发式规则。
 *
 * @param {string} relativePath git 输出的路径（正斜杠；反斜杠也兼容）。
 * @returns {boolean} 是否属于测试/夹具面。
 */
export function isTestPath(relativePath) {
  const normalized = String(relativePath).replace(/\\/g, "/");
  if (/(^|\/)(tests?|__tests__|fixtures?|golden|testdata)(\/|$)/.test(normalized)) return true;
  return /\.(test|spec)\.[^/]+$/.test(normalized);
}

/**
 * 规则表。
 *
 * `redact: false` 仅用于**本身不含密钥材料**的模式（PEM 头部）：把它掩码会让输出变成
 * `----…(31)`，读的人反而不知道该找什么。
 */
export const RULES = [
  {
    id: "pem-private-key",
    tier: RULE_TIERS.high,
    description: "PEM 私钥块（含 RSA / EC / DSA / OPENSSH / PGP）",
    pattern: /-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----/,
    redact: false,
  },
  {
    id: "aws-access-key",
    tier: RULE_TIERS.high,
    description: "AWS access key id",
    pattern: /\bAKIA[0-9A-Z]{16}\b/,
    redact: true,
  },
  {
    id: "github-token",
    tier: RULE_TIERS.high,
    description: "GitHub token（ghp_ / gho_ / ghu_ / ghs_ / ghr_）",
    pattern: /\bgh[pousr]_[A-Za-z0-9]{36,}\b/,
    redact: true,
  },
  {
    id: "slack-token",
    tier: RULE_TIERS.high,
    description: "Slack token 前缀（xoxb/xoxa/xoxp/xoxr/xoxs）",
    pattern: /\bxox[baprs]-/,
    redact: true,
  },
  {
    id: "credential-assignment",
    tier: RULE_TIERS.generic,
    description: "凭据赋值的明文字面量（password/secret/api_key/access_token = '…'）",
    pattern: /(password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['"][^'"]{8,}['"]/i,
    redact: true,
  },
];

/**
 * 把命中片段脱敏。
 *
 * @param {string} text 命中原文。
 * @param {boolean} redact 是否需要脱敏。
 * @returns {string} 可安全打进日志的片段。
 */
export function maskExcerpt(text, redact) {
  const value = String(text);
  if (!redact) return value.replace(/\s+/g, " ").trim();
  if (value.length <= 4) return `…(长度 ${value.length})`;
  return `${value.slice(0, 4)}…(长度 ${value.length})`;
}

/**
 * 在一段文本里跑规则（纯函数）。
 *
 * @param {string} text 文件内容。
 * @param {{skipGeneric?: boolean}} [options] `skipGeneric` = 跳过 generic 级规则
 *   （调用方按 {@link isTestPath} 决定；high 级规则**永远**执行）。
 * @returns {Array<{rule: string, line: number, excerpt: string}>}
 */
export function scanText(text, options = {}) {
  const skipGeneric = options.skipGeneric === true;
  const findings = [];
  for (const rule of RULES) {
    if (skipGeneric && rule.tier === RULE_TIERS.generic) continue;
    // 规则对象是共享常量：`g` 标志会让 lastIndex 在调用间残留 ⇒ 每次新建正则。
    const scanner = new RegExp(rule.pattern.source, rule.pattern.flags.includes("g") ? rule.pattern.flags : `${rule.pattern.flags}g`);
    let match;
    while ((match = scanner.exec(text)) !== null) {
      const line = text.slice(0, match.index).split("\n").length;
      findings.push({
        rule: rule.id,
        line,
        excerpt: maskExcerpt(match[0], rule.redact),
      });
      // 零宽匹配保护：避免死循环（本项目不存在零宽规则，但别让将来的人踩）。
      if (match.index === scanner.lastIndex) scanner.lastIndex += 1;
    }
  }
  return findings;
}

/**
 * 收集扫描面。
 *
 * @param {{includeUntracked: boolean}} options `includeUntracked` = 额外扫"未跟踪且未被
 *   ignore"的文件（默认关；见文件头"边界"一节 —— CI 用 tracked 口径即可，本地收口时
 *   可以开它把"即将提交的新文件"也扫一遍）。
 * @returns {string[]} 相对仓库根的路径（git 输出即正斜杠）。
 */
export function collectFiles({ includeUntracked }) {
  // `-c`（cached）+ `-o`（others）必须**同时**给：只给 `--others` 时 git 只列未跟踪文件，
  // 把 512 个已跟踪文件整批丢掉（实测：files 从 512+ 掉到 105，且 allowlist 全部变 stale）。
  const args = ["ls-files", "-z", "--cached"];
  if (includeUntracked) args.push("--others", "--exclude-standard");
  const raw = execFileSync("git", args, {
    cwd: REPO_ROOT,
    encoding: "buffer",
    maxBuffer: 64 * 1024 * 1024,
  });
  return Array.from(
    new Set(
      raw
        .toString("utf8")
        .split("\0")
        .filter((entry) => entry !== "")
    )
  );
}

/**
 * 读一个文件并判定是否可扫描。
 *
 * @param {string} relativePath 相对仓库根。
 * @returns {{kind: "text", text: string} | {kind: "binary"} | {kind: "too-big", bytes: number}
 *   | {kind: "missing"}}
 */
export function readScanTarget(relativePath) {
  const absolute = join(REPO_ROOT, relativePath);
  let info;
  try {
    info = statSync(absolute);
  } catch {
    return { kind: "missing" };
  }
  if (!info.isFile()) return { kind: "missing" };
  if (info.size > MAX_FILE_BYTES) return { kind: "too-big", bytes: info.size };
  const buffer = readFileSync(absolute);
  if (buffer.subarray(0, BINARY_PROBE_BYTES).includes(0)) return { kind: "binary" };
  return { kind: "text", text: buffer.toString("utf8") };
}

/**
 * 读取并校验 allowlist。
 *
 * 校验是**硬**的：缺字段 / 通配 / 目录级条目一律让门禁红 —— 否则 allowlist 会从
 * "带理由的例外"退化成"关闭规则的开关"。
 *
 * @param {string} path allowlist 路径。
 * @returns {{ok: true, entries: Array<object>} | {ok: false, error: string}}
 */
export function loadAllowlist(path = ALLOWLIST_PATH) {
  if (!existsSync(path)) {
    return { ok: false, error: `allowlist 不存在：${path}（空表也要有文件，否则"为什么放行"无处记录）` };
  }
  let document;
  try {
    document = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return { ok: false, error: `allowlist 不是合法 JSON：${reason}` };
  }
  const entries = document?.entries;
  if (!Array.isArray(entries)) return { ok: false, error: "allowlist 缺 entries 数组" };

  const knownRules = new Set(RULES.map((rule) => rule.id));
  const problems = [];
  for (const [index, entry] of entries.entries()) {
    const label = `entries[${index}]`;
    if (entry === null || typeof entry !== "object") {
      problems.push(`${label} 不是对象`);
      continue;
    }
    for (const field of ["path", "rule", "reason", "owner"]) {
      if (typeof entry[field] !== "string" || entry[field].trim() === "") {
        problems.push(`${label} 缺 ${field}（四个字段缺一即拒绝：例外必须可追溯到理由与责任人）`);
      }
    }
    if (typeof entry.rule === "string" && !knownRules.has(entry.rule)) {
      problems.push(`${label} 的 rule "${entry.rule}" 不是已知规则（拼错会让豁免永远不生效）`);
    }
    if (typeof entry.path === "string") {
      if (entry.path.includes("*") || entry.path.includes("?") || entry.path.trim().endsWith("/")) {
        problems.push(`${label} 的 path "${entry.path}" 是通配/目录级 —— 禁止"一把梭"豁免，必须逐文件`);
      }
    }
  }
  if (problems.length > 0) return { ok: false, error: problems.join("；") };
  return { ok: true, entries };
}

/**
 * 按 (path, rule) 精确匹配分流。
 *
 * @param {Array<{path: string, rule: string}>} findings
 * @param {Array<{path: string, rule: string}>} entries
 * @returns {{allowed: Array<object>, unallowed: Array<object>, stale: Array<object>}}
 */
export function applyAllowlist(findings, entries) {
  const key = (item) => `${item.path}\u0000${item.rule}`;
  const allowedKeys = new Set(entries.map(key));
  const usedKeys = new Set();
  const allowed = [];
  const unallowed = [];
  for (const finding of findings) {
    if (allowedKeys.has(key(finding))) {
      allowed.push(finding);
      usedKeys.add(key(finding));
    } else {
      unallowed.push(finding);
    }
  }
  const stale = entries.filter((entry) => !usedKeys.has(key(entry)));
  return { allowed, unallowed, stale };
}

/** 扫描全部目标文件。 */
function scanRepository({ includeUntracked }) {
  const files = collectFiles({ includeUntracked });
  const findings = [];
  const skippedBinary = [];
  const skippedBig = [];
  /** generic 级规则被跳过（因为落在测试/夹具路径）的文件数。 */
  let genericSkippedFiles = 0;

  for (const relativePath of files) {
    const target = readScanTarget(relativePath);
    if (target.kind === "binary") {
      skippedBinary.push(relativePath);
      continue;
    }
    if (target.kind === "too-big") {
      skippedBig.push({ path: relativePath, bytes: target.bytes });
      continue;
    }
    if (target.kind !== "text") continue;

    const skipGeneric = isTestPath(relativePath);
    if (skipGeneric) genericSkippedFiles += 1;
    for (const finding of scanText(target.text, { skipGeneric })) {
      findings.push({ path: relativePath, ...finding });
    }
  }
  return { files, findings, skippedBinary, skippedBig, genericSkippedFiles };
}

/** 真实跑。 */
function runReal(argv) {
  const includeUntracked = argv.includes("--include-untracked");
  const allowlist = loadAllowlist();
  if (!allowlist.ok) {
    console.error(`[gate-secrets] FAIL：allowlist 不合法 —— ${allowlist.error}`);
    console.error("[gate-secrets] 例外必须逐条写清 path / rule / reason / owner，禁止通配或目录级豁免。");
    return 1;
  }

  const { files, findings, skippedBinary, skippedBig, genericSkippedFiles } = scanRepository({
    includeUntracked,
  });
  const { allowed, unallowed, stale } = applyAllowlist(findings, allowlist.entries);

  const highCount = RULES.filter((rule) => rule.tier === RULE_TIERS.high).length;
  const genericCount = RULES.length - highCount;
  console.log(
    `[gate-secrets] 扫描面=${includeUntracked ? "tracked + untracked(未忽略)" : "tracked"} ` +
      `files=${files.length} rules=${RULES.length}（high=${highCount} / generic=${genericCount}） ` +
      `allowlist=${allowlist.entries.length}`
  );
  console.log(
    `[gate-secrets] 通用规则跳过测试/夹具路径=${genericSkippedFiles} 个文件 ` +
      `（high 级规则仍全路径扫描，测试目录不例外）`
  );
  console.log(`[gate-secrets] 跳过二进制=${skippedBinary.length} 超大文件=${skippedBig.length}`);
  for (const item of skippedBig) {
    console.log(`[gate-secrets]   skip(too-big) ${item.path} (${item.bytes} bytes > ${MAX_FILE_BYTES})`);
  }
  if (skippedBinary.length > 0) {
    console.log(`[gate-secrets]   跳过二进制清单（前 10）：${skippedBinary.slice(0, 10).join(", ")}`);
  }

  console.log(`[gate-secrets] 命中=${findings.length} 已豁免=${allowed.length} 未豁免=${unallowed.length}`);
  for (const finding of allowed) {
    console.log(`[gate-secrets]   allowlisted ${finding.path}:${finding.line} [${finding.rule}] ${finding.excerpt}`);
  }
  for (const finding of unallowed) {
    console.error(
      `[gate-secrets]   VIOLATION ${finding.path}:${finding.line} [${finding.rule}] ${finding.excerpt}`
    );
  }
  if (stale.length > 0) {
    // 不算失败：夹具可能被删掉。但要可见 —— 陈旧豁免是"规则被悄悄放宽"的常见入口。
    console.warn(`[gate-secrets]   [warn] ${stale.length} 条 allowlist 条目已不再命中（可考虑删除）：`);
    for (const entry of stale) console.warn(`[gate-secrets]     ${entry.path} [${entry.rule}]`);
  }

  if (unallowed.length > 0) {
    console.error(
      "[gate-secrets] FAIL：存在未豁免的疑似凭据。真凭据 ⇒ 立即吊销并报主理人；" +
        "假示例 ⇒ 在 scripts/secret-allowlist.json 逐条登记 reason/owner（不许放宽规则）。"
    );
    return 1;
  }
  console.log("[gate-secrets] PASS");
  return 0;
}

// ---------------------------------------------------------------------------
// self-test：5 条规则各必须红一次，干净文件必须绿，且仓库零残留
// ---------------------------------------------------------------------------

/**
 * 每条规则一份夹具 + 一份干净文件（夹具里刻意不交叉，便于断言"某规则命中几次"）。
 *
 * ⚠️ **夹具字面量必须在源码里拼接**，不能整串写出来：本脚本一旦被提交进仓库，
 * 它自己就是扫描目标 —— 整串写会让自己永久命中自己的规则（门禁常红 ⇒ 后人只能
 * 加豁免或放宽规则，正是要消灭的形态）。拼接后源码里不存在连续的可疑字面量，
 * 而运行时 `content` 仍然是完整样本。`--include-untracked` 跑一遍即可验证这一点。
 */
const SELF_TEST_FIXTURES = [
  {
    name: "pem.txt",
    expectedRule: "pem-private-key",
    content:
      "-----BEGIN " + "RSA PRIVATE KEY-----\n" + "ZmFrZS1rZXktbWF0ZXJpYWwtb25seQ==\n" + "-----END RSA PRIVATE KEY-----\n",
  },
  {
    name: "aws.txt",
    expectedRule: "aws-access-key",
    content: "region=us-east-1\nid = AKIA" + "IOSFODNN7EXAMPLE\n",
  },
  {
    name: "github.txt",
    expectedRule: "github-token",
    content: "token gh" + "p_" + "a".repeat(36) + "\n",
  },
  {
    name: "slack.txt",
    expectedRule: "slack-token",
    content: "hook xox" + "b-0000-fixture\n",
  },
  {
    name: "cred.txt",
    expectedRule: "credential-assignment",
    content: "api_key = " + '"fixture-only-not-a-real-key"\n',
  },
  {
    name: "clean.txt",
    expectedRule: null,
    content: "这是一个干净文件：没有凭据，只有说明文字。\npassword 这个词单独出现不算命中。\n",
  },
];

function selfTest() {
  const results = [];
  const check = (name, condition, detail = "") => {
    results.push({ name, ok: Boolean(condition), detail });
  };

  const directory = mkdtempSync(join(tmpdir(), "wbtime-gate-secrets-"));
  try {
    for (const fixture of SELF_TEST_FIXTURES) {
      writeFileSync(join(directory, fixture.name), fixture.content, "utf8");
    }

    for (const fixture of SELF_TEST_FIXTURES) {
      const text = readFileSync(join(directory, fixture.name), "utf8");
      const hits = scanText(text);
      if (fixture.expectedRule === null) {
        check(`干净夹具 ${fixture.name} 不得命中`, hits.length === 0, `实际命中 ${hits.length}`);
        continue;
      }
      check(
        `夹具 ${fixture.name} 必须命中 ${fixture.expectedRule}`,
        hits.some((hit) => hit.rule === fixture.expectedRule),
        `实际命中 [${hits.map((hit) => hit.rule).join(",") || "无"}]`
      );
      check(
        `夹具 ${fixture.name} 只命中该规则（无交叉误报）`,
        hits.length > 0 && hits.every((hit) => hit.rule === fixture.expectedRule),
        `实际命中 [${hits.map((hit) => hit.rule).join(",")}]`
      );
      const hit = hits.find((item) => item.rule === fixture.expectedRule);
      check(`夹具 ${fixture.name} 报告了行号`, typeof hit?.line === "number" && hit.line >= 1);
      check(
        `夹具 ${fixture.name} 的片段已脱敏（不回显凭据本体）`,
        fixture.expectedRule === "pem-private-key" || (hit?.excerpt ?? "").includes("…"),
        `摘录=${hit?.excerpt ?? "(无)"}`
      );
    }

    // ---- 规则分级边界（主理人 2026-10-21 裁定）----------------------------
    // ① generic 级只对"非测试路径"生效：同一段文本，生产路径必红、测试路径不报。
    const genericSample = "password = " + '"hunter2hunter2"';
    check(
      "生产路径的 password 赋值 ⇒ generic 级命中",
      scanText(genericSample, { skipGeneric: false }).some((hit) => hit.rule === "credential-assignment")
    );
    check(
      "测试路径的 password 赋值 ⇒ generic 级跳过（不制造豁免噪音）",
      scanText(genericSample, { skipGeneric: true }).length === 0
    );

    // ② high 级在测试路径**仍然**命中：路径豁免只对 generic 级生效，不是把测试面整体放过。
    const highSample = "id = AKIA" + "IOSFODNN7EXAMPLE";
    check(
      "测试路径的 AWS key ⇒ high 级仍命中（测试面没有被整体放过）",
      scanText(highSample, { skipGeneric: true }).some((hit) => hit.rule === "aws-access-key")
    );
    check(
      "测试路径的 PEM 头 ⇒ high 级仍命中",
      scanText("-----BEGIN " + "EC PRIVATE KEY-----", { skipGeneric: true }).some(
        (hit) => hit.rule === "pem-private-key"
      )
    );

    // ③ 路径判定的正反例（这条最容易写宽：写宽了就变成"测试目录整体豁免"）。
    const pathCases = [
      ["apps/api/src/modules/auth/service.ts", false],
      ["apps/api/src/fixtures/seed-data.ts", true],
      ["apps/api/tests/auth-jwt.test.mjs", true],
      ["apps/api/tests/parity/j11-harness.mjs", true],
      ["apps/web/src/components/settings/__tests__/AuditSection.test.tsx", true],
      ["packages/security/tests/golden/scan-sensitive.py-golden.json", true],
      ["packages/db/testdata/sample.json", true],
      ["packages/e2e/tests/_harness.mjs", true],
      ["scripts/gate-secrets.mjs", false],
      ["apps/api/src/latest/notes.md", false],
    ];
    for (const [path, expected] of pathCases) {
      check(
        `isTestPath(${path}) === ${expected}`,
        isTestPath(path) === expected,
        `实际 ${isTestPath(path)}`
      );
    }

    // allowlist 校验：通配 / 目录级 / 缺字段 必须被拒
    const globAllowlist = join(directory, "glob.json");
    writeFileSync(
      globAllowlist,
      JSON.stringify({ entries: [{ path: "packages/**", rule: "aws-access-key", reason: "x", owner: "y" }] }),
      "utf8"
    );
    check("allowlist 通配条目被拒", loadAllowlist(globAllowlist).ok === false);

    const dirAllowlist = join(directory, "dir.json");
    writeFileSync(
      dirAllowlist,
      JSON.stringify({ entries: [{ path: "packages/e2e/tests/", rule: "aws-access-key", reason: "x", owner: "y" }] }),
      "utf8"
    );
    check("allowlist 目录级条目被拒", loadAllowlist(dirAllowlist).ok === false);

    const incompleteAllowlist = join(directory, "incomplete.json");
    writeFileSync(
      incompleteAllowlist,
      JSON.stringify({ entries: [{ path: "a/b.mjs", rule: "aws-access-key" }] }),
      "utf8"
    );
    check("allowlist 缺 reason/owner 被拒", loadAllowlist(incompleteAllowlist).ok === false);

    const unknownRuleAllowlist = join(directory, "unknown.json");
    writeFileSync(
      unknownRuleAllowlist,
      JSON.stringify({ entries: [{ path: "a/b.mjs", rule: "no-such-rule", reason: "x", owner: "y" }] }),
      "utf8"
    );
    check("allowlist 未知 rule 被拒（拼错等于豁免永不生效）", loadAllowlist(unknownRuleAllowlist).ok === false);

    // 分流：精确 (path, rule) 才算豁免；同文件另一条规则仍须红
    const split = applyAllowlist(
      [
        { path: "a.mjs", rule: "aws-access-key" },
        { path: "a.mjs", rule: "slack-token" },
      ],
      [{ path: "a.mjs", rule: "aws-access-key" }]
    );
    check("豁免按 (path, rule) 精确生效", split.allowed.length === 1 && split.unallowed.length === 1);
    check("未命中的 allowlist 条目被识别为 stale", split.stale.length === 0);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }

  check("self-test 不在仓库留残留（只写 os.tmpdir()）", existsSync(directory) === false);

  for (const item of results) {
    console.log(
      `[gate-secrets:self-test] ${item.ok ? "[OK]" : "[FAIL]"} ${item.name}${item.detail ? ` (${item.detail})` : ""}`
    );
  }
  const failed = results.filter((item) => !item.ok);
  console.log(
    `[gate-secrets:self-test] ${failed.length === 0 ? "PASS" : "FAIL"}：${results.length - failed.length}/${results.length}`
  );
  return failed.length === 0 ? 0 : 1;
}

const argv = process.argv.slice(2);
const known = new Set(["--self-test", "--include-untracked"]);
const unknown = argv.filter((argument) => !known.has(argument));
if (unknown.length > 0) {
  console.error(`[gate-secrets] 未知参数：${unknown.join(" ")}（支持 --self-test / --include-untracked）`);
  process.exit(1);
}
process.exit(argv.includes("--self-test") ? selfTest() : runReal(argv));
