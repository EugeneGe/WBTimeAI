/**
 * 共用 TAP 执行器 —— `scripts/run-smoke.mjs` / `scripts/run-conformance.mjs` 的**唯一实现**。
 *
 * 存在的理由（V0.2.0 审计 #3 / FIX-03）：此前的入口是
 * `node --test <glob>`（如 `tests` 下递归 `*.test.mjs`）—— 一旦 glob 匹配 **0 个文件**，node 会打印
 * `# pass 0` 并 **exit 0**：套件"全绿"，而它一个 case 都没跑（conformance 的
 * `.cases.mjs` 就是这种形态，从未被执行过）。这类假绿的共性是**只看 exit code**，
 * 所以本执行器把判据从"退出码"换成"**执行数**"：
 *
 *   1. 文件路径**显式**给出（由 `readdirSync` 展开，不把 glob 交给 node —— 零匹配
 *      在 shell 展开阶段就变成空参数，在 node 里变成一个不存在的字面量）；
 *   2. 每个文件**先 stat 一遍**，缺失 ⇒ 立刻 exit 1（不会"少跑一个文件还绿"）；
 *   3. 解析 TAP 汇总的 `# pass N`，**N < minPass ⇒ exit 1**（`minPass` 是每个套件
 *      写死的下界，改了用例数就必须同步改下界 —— 这条是刻意的摩擦）；
 *   4. `# fail` 非 0 或**汇总无法解析**（空输出 / reporter 变更）⇒ exit 1。
 *      无法解析**绝不能**当成"零失败"（K-11：空集合 ⇒ INVALID）。
 *
 * **裸 glob 入口的「0 文件假绿」由本 runner 兜住**：`node --test "<glob>"` 在匹配 0 文件时
 * 会打印 `# pass 0` 并 **exit 0**。凡是要进 CI / 进验收口径的测试入口，都必须走本 runner
 * 或 `scripts/lib/suites.mjs` 的登记表；新增入口一律登记，不要再写裸 glob 脚本。
 *
 * 退出码：成功 0；任何一条判据不满足 1。
 */

import { spawn } from "node:child_process";
import { existsSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** 仓库根（`scripts/lib/tap-runner.mjs` → `scripts/lib` → `scripts` → 根）。 */
export const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  ".."
);

/**
 * 传给 `node` 的固定开关。
 *
 * `--experimental-sqlite` 不是"顺手加的"：冒烟夹具 `tests/ts-backend/_backend.mjs` 与
 * conformance 夹具 `tests/conformance/harness.mjs` 都 `import { DatabaseSync } from
 * "node:sqlite"`（灌 DDL 用），Node 22 上必须显式开启；漏掉它子进程会在 import 阶段
 * 直接失败 —— 而那种失败看起来像"用例红"，会浪费排查时间。
 */
export const NODE_FLAGS = Object.freeze(["--experimental-sqlite"]);

/** 强制 TAP reporter：spec reporter 的汇总行格式随 Node 版本变化，TAP 稳定。 */
const REPORTER_FLAG = "--test-reporter=tap";

/**
 * 解析 TAP 汇总（`node --test --test-reporter=tap` 的尾部）。
 *
 * 只认**汇总行**（`# tests 4` / `# pass 4` / `# fail 0`），不数 `ok N` —— 后者会被
 * 子测试的缩进行干扰，且"数 ok 行"在 reporter 变体下同样脆弱。
 *
 * @param {string} text 子进程 stdout 全文。
 * @returns {{tests: number|null, pass: number|null, fail: number|null, parsed: boolean}}
 *   `parsed === false` ⇒ 没找到任何汇总行，调用方必须判红。
 */
export function parseTapSummary(text) {
  const body = String(text ?? "");
  const pick = (key) => {
    const match = new RegExp(`^[\\s#]*${key}\\s+(\\d+)\\s*$`, "m").exec(body);
    return match === null ? null : Number.parseInt(match[1], 10);
  };
  const summary = { tests: pick("tests"), pass: pick("pass"), fail: pick("fail") };
  summary.parsed = summary.pass !== null;
  return summary;
}

/**
 * 从 TAP 里抽出**顶层** `ok N - <name>` 的 name（缩进行是子测试，不算）。
 *
 * @param {string} text 子进程 stdout 全文。
 * @returns {string[]} 顶层通过项的 name（保持出现顺序）。
 */
export function listTopLevelOkNames(text) {
  const names = [];
  const pattern = /^ok\s+\d+\s+-\s+(.+?)\s*$/gm;
  let match = pattern.exec(String(text ?? ""));
  while (match !== null) {
    names.push(match[1]);
    match = pattern.exec(String(text ?? ""));
  }
  return names;
}

/**
 * 判断一个 TAP 顶层 name 是否**形如文件路径**（而不是用例名）。
 *
 * 判据：以 `.mjs` / `.cjs` / `.js` / `.ts` / `.mts` 结尾 **且** 含路径分隔符。
 * 要求"含分隔符"是为了不误伤「用例名正好叫 `foo.test.mjs`」这种写法
 * （团队约定里不会这么起名，但判据不该靠约定）。
 *
 * @param {string} name TAP 顶层 name。
 * @returns {boolean} 形如文件路径为 `true`。
 */
export function looksLikeFilePath(name) {
  const value = String(name ?? "").trim();
  if (!/[\\/]/.test(value)) return false;
  return /\.(mjs|cjs|js|ts|mts)$/i.test(value);
}

/**
 * **识破「文件级通过」**：`node --test` 对「0 个子测试的文件」会记
 * `ok 1 - <文件路径>`。此时 `# pass 1` 是**文件数**，不是**用例数** ——
 * 条件注册（`if (runsLeg(...))`）把用例整体跳过时就会长成这样，
 * 于是 `minPass` 被文件数满足，门禁"绿"了但一条用例都没跑。
 *
 * 判据：**全部**顶层 `ok` 的 name 都是文件路径形态 ⇒ 红。
 * 只要有一条是真用例名就不报（避免误伤"部分文件 + 部分用例"的混合输出）。
 *
 * @param {string} text 子进程 stdout 全文。
 * @throws {Error} 仅有文件级通过项时抛（错误文案固定，写清原因）。
 */
export function assertCaseLevelPass(text) {
  const names = listTopLevelOkNames(text);
  if (names.length === 0) return;
  const fileLike = names.filter((name) => looksLikeFilePath(name));
  if (fileLike.length !== names.length) return;
  throw new Error(
    `文件级通过不算用例（条件注册把用例跳过时 node 会这样报）：` +
      `${names.length} 个顶层 ok 全是文件路径，0 个具名用例` +
      `（例：${names[0]}）。请检查该套件是否漏传环境变量（如 E2E_LEG=reverse）。`
  );
}

/**
 * 把一个目录下的测试文件展开成**显式绝对路径**列表（不交给 node 的 glob）。
 *
 * @param {string} relativeDir 相对仓库根的目录。
 * @param {string} [suffix] 文件名后缀过滤（默认 `.test.mjs`；conformance 的
 *   `.cases.mjs` 由调用方显式给路径，不走本函数）。
 * @returns {string[]} 绝对路径（按名称排序，保证输出稳定可比）。
 * @throws {Error} 目录不存在或不是目录（**不**返回空数组 —— 静默空集就是假绿）。
 */
export function listTestFiles(relativeDir, suffix = ".test.mjs") {
  const absoluteDir = path.join(REPO_ROOT, relativeDir);
  if (!existsSync(absoluteDir) || !statSync(absoluteDir).isDirectory()) {
    throw new Error(`[tap-runner] 目录不存在：${absoluteDir}`);
  }
  return readdirSync(absoluteDir)
    .filter((name) => name.endsWith(suffix))
    .sort()
    .map((name) => path.join(absoluteDir, name));
}

/**
 * 跑一个「执行数必须达标」的套件。
 *
 * @param {object} options 执行参数。
 * @param {string} options.label 套件名（日志前缀）。
 * @param {string[]} options.files 显式文件路径（绝对或相对仓库根）。
 * @param {Record<string, string>} [options.env] 追加/覆盖的环境变量。
 * @param {number} options.minPass 执行数下界（`# pass N` 必须 ≥ 它）。
 * @param {(summary: {tests: number|null, pass: number|null, fail: number|null}) => void}
 *   [options.onSummary] 解析出汇总后的回调（聚合执行器用它统计各组 pass 数；
 *   缺省不调用 —— 不影响单套件用法）。
 * @returns {Promise<number>} 进程退出码（0 = 达标）。
 */
export async function runTapSuite(options) {
  const { label, files, env = {}, minPass, onSummary } = options;
  const prefix = `[${label}]`;

  if (!Array.isArray(files) || files.length === 0) {
    process.stderr.write(`${prefix} FAIL: 文件列表为空（0 个文件 = 0 个 case，绝不能算绿）\n`);
    return 1;
  }
  if (!Number.isInteger(minPass) || minPass <= 0) {
    process.stderr.write(`${prefix} FAIL: minPass 必须是正整数，收到 ${String(minPass)}\n`);
    return 1;
  }

  // ① 先 stat 每个文件：路径写错 / 文件被改名 ⇒ 在起子进程之前就红。
  const missing = files.filter((file) => !existsSync(path.resolve(REPO_ROOT, file)));
  if (missing.length > 0) {
    process.stderr.write(
      `${prefix} FAIL: ${missing.length} 个文件不存在（路径写错或被改名）：\n` +
        missing.map((file) => `  - ${file}\n`).join("")
    );
    return 1;
  }

  process.stdout.write(
    `${prefix} files(${files.length}):\n` + files.map((file) => `  - ${path.basename(file)}\n`).join("")
  );
  const envKeys = Object.keys(env);
  if (envKeys.length > 0) {
    process.stdout.write(
      `${prefix} env: ${envKeys.map((key) => `${key}=${env[key]}`).join(" ")}\n`
    );
  }

  // ② 起子进程：stdout 全量收集（用于解析），同时转发（CI 日志可见）。
  const child = spawn(
    process.execPath,
    [...NODE_FLAGS, "--test", REPORTER_FLAG, ...files],
    {
      cwd: REPO_ROOT,
      env: { ...process.env, ...env },
      stdio: ["ignore", "pipe", "pipe"],
    }
  );

  let stdout = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
    process.stdout.write(chunk);
  });
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => process.stderr.write(chunk));

  const exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => resolve(code === null ? 1 : code));
  });

  // ③ 判据：汇总可解析 + fail=0 + pass ≥ minPass。三条**全部**要满足。
  const summary = parseTapSummary(stdout);
  if (typeof onSummary === "function") onSummary(summary);
  if (!summary.parsed) {
    process.stderr.write(
      `${prefix} FAIL: 无法从 TAP 输出解析出汇总（空汇总 / reporter 变更 = 假绿，K-11）\n`
    );
    return 1;
  }
  // 先识破「文件级通过」——否则 `# pass 1` 会被当成"跑了 1 条用例"而放行。
  try {
    assertCaseLevelPass(stdout);
  } catch (error) {
    process.stderr.write(`${prefix} FAIL: ${error.message}\n`);
    return 1;
  }
  if (orDefault(summary.fail, 0) !== 0) {
    process.stderr.write(`${prefix} FAIL: fail=${summary.fail}（要求 0）⇒ 子进程 exit=${exitCode}\n`);
    return 1;
  }
  if (orDefault(summary.pass, 0) < minPass) {
    process.stderr.write(
      `${prefix} FAIL: 执行数不足 pass=${summary.pass} < ${minPass}` +
        `（glob 匹配 0 文件仍 exit 0 的假绿就是这样产生的）\n`
    );
    return 1;
  }
  if (exitCode !== 0) {
    process.stderr.write(`${prefix} FAIL: 汇总达标但子进程 exit=${exitCode}\n`);
    return 1;
  }

  process.stdout.write(
    `${prefix} OK ✅ tests=${summary.tests} pass=${summary.pass} fail=${summary.fail} ` +
      `(minPass=${minPass})\n`
  );
  return 0;
}

/**
 * `null` 归一成缺省值（TAP 汇总里 `# fail` 理论上恒在；缺了按 0 处理**仅**用于
 * "fail 是否为 0" 这一条 —— `pass` 那一侧仍然是硬要求，见上面的 `parsed`）。
 *
 * @param {number|null} value 解析值。
 * @param {number} fallback 缺省值。
 * @returns {number}
 */
function orDefault(value, fallback) {
  return value === null ? fallback : value;
}
