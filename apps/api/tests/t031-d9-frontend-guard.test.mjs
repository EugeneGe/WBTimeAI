/**
 * V0.3.1 · **D9②③** 判据载体（T031-06 收口 · 前端零改动前提下的契约守卫）。
 *
 * 为什么必须有这个文件（2026-10-23 主理人拍板）
 * ------------------------------------------
 *   D9 的原文要求「证据落 `contracts/frontend-baseline/**` 的 e2e runner」，
 *   但**行为级前端判据在本版做不了**，三条硬约束：
 *     ① 红线 = `apps/web/src/**` 零改动 ⇒ 不能在 `src/**\/__tests__` 加用例；
 *     ② `apps/web/src/lib/chat.ts:7` 依赖 `@/types` 路径别名 ⇒ `node --test`
 *        直跑前端模块不可行（要 loader 或 esbuild 现场 bundle = 新增工具链）；
 *     ③ 计划原文 `01-计划/README.md:64` 对 D9③ 自己就写了「③ **恒真但保留**，
 *        作『前端对未知通道必须静默丢弃』的契约守卫」—— 它本就被定性为**契约守卫**，
 *        不是行为判据。
 *   ⇒ 本文件把 ②③ 落成 **静态契约守卫**（只读被测源码的**文本**做断言，
 *   **不 import 任何前端模块** ⇒ 天然绕开别名问题，零新增工具链）；
 *   **不新建** `apps/web/tests/**`、**不改** `apps/web/vitest.config.ts`、
 *   不触碰工作树里的 `apps/web/src`。
 *
 * 本文件到底钉住了什么（**这是重点，别读成"前端有隔离"**）
 * ------------------------------------------------------
 *   **D9③（新帧静默丢弃）** —— 守卫**真实存在**，可以正面断言：
 *     `chat.ts` 的 `parseSseFrame` 有 `if (channel === null || !isSseChannel(channel)) return null;`
 *     且 `types/phase1.ts` 的 `SSE_CHANNELS` 白名单**不含** `subagent.started` / `subagent.finished`
 *     ⇒ 本版新增的 2 帧在 `parseSseFrame` 处**结构性**返回 `null`。
 *
 *   **D9②（`activeRunId` 恒 == 父 run id）** —— 守卫**不存在**，本文件钉住的是这个事实：
 *     `useChatStream.ts` 的 `dispatchEvent` 在 `agent.started` 分支里
 *     `const runId = asString(payload.run_id); if (runId) { store.setActiveRunId(runId); }`
 *     —— **没有任何「与当前 activeRunId / 父 run 匹配」的判定**。同一形状还有一处：
 *     `onEvent` 也无条件写 `progress.runId`，而它决定续传 URL（`openRunEventsStream(progress.runId, …)`）。
 *     ⇒ **D9② 的成立完全依赖后端 D2-a 隔离（子 run 帧不进父流），前端没有第二道闸。**
 *     这**不是**源码 Bug（加前端守卫就破 Q-5 红线），但必须被钉住：谁给前端加了守卫，
 *     本文件就转红，强制同步更新台账措辞（防"以为前端有隔离"的假象）。
 *
 *   **D2 的隔离是不是真的（G-2b 关系式）** — 不写成"含 `runId` 形参 + 含 `filter`"这种
 *   存在性断言，而写成两条**关系式**：
 *     ⓐ `owned`（行级过滤结果）必须在 `continualFrom` **之前**算出 —— 否则父子交错的
 *        父行呈现 `1、3、5`，被 gap-aware 裁成"洞"⇒ **父流静默丢帧**（预落地 #1 的硬约束）；
 *     ⓑ `owned` 的过滤谓词必须引用 `agent_event.run_id` **列**（`row.run_id`），
 *        不得引用帧 `payload` —— 前者是归属的唯一可靠载体（`02-施工/README.md` §8.5）。
 *     任一不成立 ⇒ D2 的隔离就是假的。
 *
 * 反例（双向验证：坏实现必红 / 好实现必绿）
 * ----------------------------------------
 *   一律把被测源码**复制到临时目录**再改坏，**绝不改工作树里的 `apps/web/src`**；
 *   临时产物落 `D:/Temp/WBTimeAI/`（`施工纪律.md` §4.10.6 临时产物唯一落点），用例结束即删。
 *     反例 A：白名单里加 `subagent.started` / 删掉 `!isSseChannel(channel)` ⇒ G-3 必红
 *     反例 B：给 `agent.started` 分支插 run 匹配守卫                     ⇒ G-2a 必红
 *     反例 C：`continualFrom(rows, …)`（先裁剪后过滤）/ `payload.run_id === runId` ⇒ G-2b 必红
 *     对照 D：同样复制但**不改坏** ⇒ 全部守卫必绿（证明仪器不是恒红）
 *
 * 行为面旁证（**本文件不跑，收口时单独跑**）
 * ----------------------------------------
 *   `pnpm --filter @wbtime/web test` 全量绿 = 既有前端用例不退化为证据。
 *   **前端运行时行为判据本版未做** —— 证据构成 = 静态契约守卫 + 既有前端全量绿
 *   + D2-a/D2-b 的后端隔离前置。已登记于 `03-台账/DoD-V0.3.1.md` §5.7。
 *
 * 复跑（只跑本文件，不要跑全量）：
 *   cd D:/WBT/WBTimeAI && node --experimental-sqlite --test apps/api/tests/t031-d9-frontend-guard.test.mjs
 */

import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// ---------------------------------------------------------------------------
// 路径与常量
// ---------------------------------------------------------------------------

/** 仓库根（本文件在 `apps/api/tests/` 下，向上三级）。 */
const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

const WEB_SRC_DIR = path.join(REPO_ROOT, "apps/web/src");
const CHAT_TS = path.join(WEB_SRC_DIR, "lib/chat.ts");
const PHASE1_TS = path.join(WEB_SRC_DIR, "types/phase1.ts");
const HOOK_TS = path.join(WEB_SRC_DIR, "hooks/useChatStream.ts");
const SSE_STREAM_TS = path.join(REPO_ROOT, "apps/api/src/modules/run/sse-stream.ts");

/** 本版新增、前端一个都不认识的 2 帧（D9③ 的被测对象）。 */
const DELTA_CHANNELS = ["subagent.started", "subagent.finished"];

/** 临时产物根（`施工纪律.md` §4.10.6）；不可用时回落系统临时目录。 */
const SCRATCH_BASES = ["D:/Temp/WBTimeAI", tmpdir()];

// ---------------------------------------------------------------------------
// 工具：源码读 / 定位 / 打印
// ---------------------------------------------------------------------------

/**
 * 读取源码文本。
 *
 * @param {string} file 绝对路径。
 * @returns {string} UTF-8 文本。
 */
function readSource(file) {
  return readFileSync(file, "utf8");
}

/**
 * 计算某个字符下标所在的行号（1 起）。
 *
 * @param {string} text 源码文本。
 * @param {number} index 字符下标。
 * @returns {number} 行号。
 */
function lineOf(text, index) {
  return text.slice(0, index).split("\n").length;
}

/**
 * 取某下标所在行的原文（用于证据打印：**给行号 + 原文，不做 no-op includes**）。
 *
 * @param {string} text 源码文本。
 * @param {number} index 字符下标。
 * @returns {string} 该行 trim 后的原文。
 */
function textOfLine(text, index) {
  const start = text.lastIndexOf("\n", index) + 1;
  const end = text.indexOf("\n", index);
  return text.slice(start, end === -1 ? text.length : end).trim();
}

/**
 * 把 `/* … *\/` 块注释替换成等长空白（保留换行，保持下标与行号不变）。
 *
 * 为什么需要：`sse-stream.ts` 的文档注释里**大量引用** `continualFrom(...)` 的用法示例，
 * 不剥注释会把注释当成调用点，判据立刻变成假红。
 *
 * @param {string} text 源码文本。
 * @returns {string} 剥掉块注释后的等长文本。
 */
function stripBlockComments(text) {
  let output = "";
  let index = 0;
  while (index < text.length) {
    if (text.startsWith("/*", index)) {
      const end = text.indexOf("*/", index + 2);
      const stop = end === -1 ? text.length : end + 2;
      for (let cursor = index; cursor < stop; cursor += 1) {
        output += text[cursor] === "\n" ? "\n" : " ";
      }
      index = stop;
    } else {
      output += text[index];
      index += 1;
    }
  }
  return output;
}

/**
 * 创建并返回一个临时目录（用例结束时由调用方删除）。
 *
 * @param {string} tag 目录名前缀。
 * @returns {string} 临时目录绝对路径。
 */
function makeScratchDir(tag) {
  const failures = [];
  for (const base of SCRATCH_BASES) {
    try {
      mkdirSync(base, { recursive: true });
      return mkdtempSync(path.join(base, `${tag}-`));
    } catch (error) {
      failures.push(`${base}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  throw new Error(`无法创建临时目录：${failures.join(" | ")}`);
}

// ---------------------------------------------------------------------------
// 守卫（**纯函数：输入源码文本 ⇒ 输出判定**；这样才能指向临时副本做反例）
// ---------------------------------------------------------------------------

/**
 * G-3①：`parseSseFrame` 必须有「不认识的通道 ⇒ `return null`」分支。
 *
 * @param {string} source `apps/web/src/lib/chat.ts` 的文本。
 * @returns {{ok: boolean, detail: string}} 判定与证据（含行号 + 原文）。
 */
function guardParseSseFrameDropsUnknown(source) {
  const fnStart = source.indexOf("export function parseSseFrame(");
  if (fnStart === -1) {
    return { ok: false, detail: "未找到 `export function parseSseFrame(` —— 函数被改名或删除" };
  }
  const fnEnd = source.indexOf("\n}", fnStart);
  const body = source.slice(fnStart, fnEnd === -1 ? source.length : fnEnd + 2);

  const guardIndex = body.indexOf("isSseChannel(");
  const nullIndex = body.indexOf("return null");
  if (guardIndex === -1) {
    return { ok: false, detail: "`parseSseFrame` 函数体内未引用 `isSseChannel(` —— 通道白名单守卫消失" };
  }
  if (nullIndex === -1) {
    return { ok: false, detail: "`parseSseFrame` 函数体内无 `return null` —— 未知通道不再被丢弃" };
  }
  if (nullIndex < guardIndex) {
    return {
      ok: false,
      detail:
        "`return null` 出现在 `isSseChannel(` **之前** —— 需人工复核是否仍在守卫未知通道" +
        `（isSseChannel@${lineOf(source, fnStart + guardIndex)}，return null@${lineOf(source, fnStart + nullIndex)}）`,
    };
  }
  const guardLine = lineOf(source, fnStart + guardIndex);
  const nullLine = lineOf(source, fnStart + nullIndex);
  return {
    ok: true,
    detail:
      `chat.ts:${guardLine} ⇒ \`${textOfLine(source, fnStart + guardIndex)}\`；` +
      `chat.ts:${nullLine} ⇒ \`${textOfLine(source, fnStart + nullIndex)}\``,
  };
}

/**
 * G-3②：前端通道白名单**不含**本版新增的 2 帧（⇒ 结构性静默丢弃）。
 *
 * @param {string} source `apps/web/src/types/phase1.ts` 的文本。
 * @returns {{ok: boolean, detail: string, channels: string[]}} 判定与证据。
 */
function guardWhitelistExcludesDeltaChannels(source) {
  const head = source.indexOf("export const SSE_CHANNELS");
  if (head === -1) {
    return { ok: false, detail: "未找到 `export const SSE_CHANNELS`", channels: [] };
  }
  const open = source.indexOf("[", head);
  const close = source.indexOf("];", open);
  if (open === -1 || close === -1) {
    return { ok: false, detail: "`SSE_CHANNELS` 数组字面量结构不可解析", channels: [] };
  }
  const block = source.slice(open, close);
  const channels = [...block.matchAll(/"([a-z][a-z0-9_.]*)"/g)].map((match) => match[1]);
  if (channels.length === 0) {
    return { ok: false, detail: "`SSE_CHANNELS` 数组内未解析出任何通道字面量（形态可能已变）", channels };
  }
  const leaked = DELTA_CHANNELS.filter((channel) => channels.includes(channel));
  return {
    ok: leaked.length === 0,
    detail:
      `phase1.ts:${lineOf(source, open)} 白名单共 ${channels.length} 条 ` +
      `[${channels.join(", ")}]` +
      (leaked.length === 0
        ? `；已确认不含 ${DELTA_CHANNELS.join(" / ")}`
        : `；**泄漏** ${leaked.join(" / ")} —— 新增帧会被前端当作已知通道消费`),
    channels,
  };
}

/**
 * G-2a：`agent.started` 写 `activeRunId` 时**不做 run 匹配**（钉住"前端无守卫"这一事实）。
 *
 * 判定逻辑（三条同时成立才算"无守卫"这一事实仍成立）：
 *   ① 该 case 分支引用了 `payload.run_id`（确实读了 run id）；
 *   ② 该分支调用了 `setActiveRunId(`（确实写了 activeRunId）；
 *   ③ 该分支**不引用** `activeRunId`（没有任何比对）。
 *
 * @param {string} source `apps/web/src/hooks/useChatStream.ts` 的文本。
 * @returns {{ok: boolean, detail: string}} 判定与证据。
 */
function guardActiveRunIdWrittenWithoutMatch(source) {
  const caseStart = source.indexOf('case "agent.started":');
  if (caseStart === -1) {
    return { ok: false, detail: '未找到 `case "agent.started":` 分支' };
  }
  const nextCase = source.indexOf('\n    case "', caseStart + 1);
  const fallback = source.indexOf("\n    default:", caseStart + 1);
  const candidates = [nextCase, fallback].filter((value) => value !== -1);
  const caseEnd = candidates.length === 0 ? source.length : Math.min(...candidates);
  const block = source.slice(caseStart, caseEnd);

  const readsRunId = block.includes("payload.run_id");
  const writesActiveRunId = block.includes("setActiveRunId(");
  const matchesRun = block.includes("activeRunId");

  const headLine = lineOf(source, caseStart);
  const evidence =
    `useChatStream.ts:${headLine} ⇒ \`${textOfLine(source, caseStart)}\`；` +
    `payload.run_id=${readsRunId} · setActiveRunId(=${writesActiveRunId} · 引用 activeRunId=${matchesRun}`;

  if (!readsRunId) {
    return { ok: false, detail: `该分支不再读 \`payload.run_id\` —— 载体形态已变，须人工复核（${evidence}）` };
  }
  if (!writesActiveRunId) {
    return { ok: false, detail: `该分支不再写 \`setActiveRunId(\` —— 载体重构，须人工复核（${evidence}）` };
  }
  if (matchesRun) {
    return {
      ok: false,
      detail:
        "该分支**现在引用了 `activeRunId`** ⇒ 前端已加 run 匹配守卫。" +
        `本判据固化的是"无前端守卫"这一事实，事实变了就必须同步更新台账措辞` +
        `（D9② 的证据结构从"依赖后端隔离"改为"后端隔离 + 前端守卫"）。证据：${evidence}`,
    };
  }
  return {
    ok: true,
    detail: `${evidence} ⇒ **确认无 run 匹配判定**；D9② 成立依赖后端 D2-a 隔离（子 run 帧不进父流）`,
  };
}

/**
 * G-2b①（关系式）：行级过滤 `owned` 必须在 `continualFrom` **之前**算出。
 *
 * 判据本体：`continualFrom(` 的每个调用点，其实参都必须以 `selectStreamableRows(` 开头。
 * 若有人写成 `continualFrom(rows, lastSeq)`（先裁剪后过滤），父子交错的父行
 * `1、3、5` 会被 gap-aware 判成"洞" ⇒ 父流静默丢帧。
 *
 * @param {string} source `apps/api/src/modules/run/sse-stream.ts` 的文本。
 * @returns {{ok: boolean, detail: string}} 判定与证据。
 */
function guardFilterBeforeConflation(source) {
  const code = stripBlockComments(source);
  const sites = [];
  const pattern = /\bcontinualFrom\s*\(/g;
  for (const match of code.matchAll(pattern)) {
    const index = match.index ?? 0;
    const before = code.slice(Math.max(0, index - 24), index);
    if (/\bfunction\s+$/.test(before)) {
      continue; // 函数**定义**本身，不是调用点
    }
    sites.push({ index, argument: code.slice(index + match[0].length, index + match[0].length + 40) });
  }
  if (sites.length === 0) {
    return { ok: false, detail: "未找到任何 `continualFrom(` 调用点 —— 载体形态已变" };
  }
  const bad = sites.filter((site) => !/^\s*selectStreamableRows\s*\(/.test(site.argument));
  const rendered = sites
    .map((site) => `${lineOf(code, site.index)}:(${site.argument.replace(/\s+/g, " ").trim()})`)
    .join(" | ");
  if (bad.length > 0) {
    return {
      ok: false,
      detail:
        `${bad.length}/${sites.length} 个调用点**未经行级过滤**直接进 \`continualFrom\` ⇒ ` +
        `父流静默丢帧风险（父行 1、3、5 被误判成洞）。调用点：${rendered}`,
    };
  }
  return { ok: true, detail: `${sites.length} 个调用点全部 \`continualFrom(selectStreamableRows(…)\`；行号：${rendered}` };
}

/**
 * G-2b②（关系式）：`owned` 的过滤谓词必须引用 **`agent_event.run_id` 列**（`row.run_id`），
 * 不得引用帧 `payload`。
 *
 * @param {string} source `apps/api/src/modules/run/sse-stream.ts` 的文本。
 * @returns {{ok: boolean, detail: string}} 判定与证据。
 */
function guardOwnedFilteredByRunIdColumn(source) {
  const code = stripBlockComments(source);
  const index = code.indexOf("const owned =");
  if (index === -1) {
    return { ok: false, detail: "未找到 `const owned =` —— 行级过滤声明消失" };
  }
  const line = textOfLine(code, index);
  const byColumn = /row\.run_id\s*===\s*runId/.test(line);
  const byPayload = /payload/.test(line);
  const detail = `sse-stream.ts:${lineOf(code, index)} ⇒ \`${line}\``;
  if (byPayload) {
    return { ok: false, detail: `过滤谓词引用了帧 \`payload\`（§8.5：归属的唯一可靠载体是行级 \`run_id\` 列）。${detail}` };
  }
  if (!byColumn) {
    return { ok: false, detail: `过滤谓词未引用 \`row.run_id === runId\` —— 归属不再按 \`agent_event.run_id\` 列判定。${detail}` };
  }
  return { ok: true, detail: `${detail} ⇒ 按列过滤，非 payload` };
}

// ---------------------------------------------------------------------------
// G-3 · D9③ 新帧静默丢弃（守卫**存在**，正面断言）
// ---------------------------------------------------------------------------

test("G-3 · D9③ 新帧静默丢弃：`parseSseFrame` 守卫未知通道 + 白名单不含 subagent.*", () => {
  assert.ok(
    readFileSync(path.join(REPO_ROOT, "package.json"), "utf8").includes("wbtime-ai"),
    `REPO_ROOT 解析错误，实测 ${REPO_ROOT}`,
  );

  const drop = guardParseSseFrameDropsUnknown(readSource(CHAT_TS));
  assert.equal(drop.ok, true, `D9③ 守卫①失败：${drop.detail}`);

  const whitelist = guardWhitelistExcludesDeltaChannels(readSource(PHASE1_TS));
  assert.equal(whitelist.ok, true, `D9③ 守卫②失败：${whitelist.detail}`);

  process.stdout.write(`  [G-3] ${drop.detail}\n`);
  process.stdout.write(`  [G-3] ${whitelist.detail}\n`);
});

// ---------------------------------------------------------------------------
// G-2a · D9② 钉住"前端无 run 匹配守卫"这一事实
// ---------------------------------------------------------------------------

test("G-2a · D9② `agent.started` 写 `activeRunId` 不做 run 匹配（事实固化，非安全属性）", () => {
  const hook = readSource(HOOK_TS);
  const guard = guardActiveRunIdWrittenWithoutMatch(hook);
  assert.equal(guard.ok, true, `G-2a 失败：${guard.detail}`);

  // 调用点计数 = **信息性输出**（不断言恰 1：任何重构都会让"恰 1"假红，而它证明不了安全属性）。
  const callSites = [...hook.matchAll(/setActiveRunId\s*\(/g)].length;
  assert.ok(callSites >= 1, `本文件应至少有一处 setActiveRunId( 调用，实测 ${callSites}`);

  // 同形状第二处：`onEvent` 也无条件写 `progress.runId`，而它决定续传 URL。仅信息性登记。
  const progressWrite = /progress\.runId\s*=\s*rid/.test(hook);

  process.stdout.write(`  [G-2a] ${guard.detail}\n`);
  process.stdout.write(
    `  [G-2a] useChatStream.ts 内 \`setActiveRunId(\` 调用点 ${callSites} 处（信息性，不断言数量）；` +
      `\`progress.runId = rid\` 无条件覆写=${progressWrite}（同形状第二处，决定续传 URL）\n`,
  );
});

// ---------------------------------------------------------------------------
// G-2b · D2 隔离的**关系式**（不是"含形参 + 含 filter"的存在性断言）
// ---------------------------------------------------------------------------

test("G-2b① 次序硬约束：`owned` 行级过滤在 `continualFrom` 之前", () => {
  const guard = guardFilterBeforeConflation(readSource(SSE_STREAM_TS));
  assert.equal(guard.ok, true, `G-2b① 失败：${guard.detail}`);
  process.stdout.write(`  [G-2b①] ${guard.detail}\n`);
});

test("G-2b② 归属载体：`owned` 按 `agent_event.run_id` 列过滤，不按 payload", () => {
  const guard = guardOwnedFilteredByRunIdColumn(readSource(SSE_STREAM_TS));
  assert.equal(guard.ok, true, `G-2b② 失败：${guard.detail}`);
  process.stdout.write(`  [G-2b②] ${guard.detail}\n`);
});

// ---------------------------------------------------------------------------
// 反例 A / B / C · 改坏必红；对照 D · 不改坏必绿（双向验证，证明仪器不是恒红）
// ---------------------------------------------------------------------------

test("反例 A · D9③ 改坏必红：白名单加 subagent.* / 删掉 `!isSseChannel` 守卫 ⇒ G-3 两侧齐红", () => {
  const scratch = makeScratchDir("t031-d9-a");
  try {
    const copy = path.join(scratch, "src");
    cpSync(WEB_SRC_DIR, copy, { recursive: true });

    // 改坏①：把新增帧混进白名单（等于前端"认识"了 subagent.*）
    const phase1Path = path.join(copy, "types/phase1.ts");
    const phase1 = readSource(phase1Path);
    const mutatedPhase1 = phase1.replace('  "agent.started",', '  "agent.started",\n  "subagent.started",');
    assert.notEqual(mutatedPhase1, phase1, "反例 A 预备失败：白名单字面量未命中，改坏未生效");
    writeFileSync(phase1Path, mutatedPhase1, "utf8");

    // 改坏②：删掉通道守卫（`!isSseChannel(channel)` ⇒ `false`）
    const chatPath = path.join(copy, "lib/chat.ts");
    const chat = readSource(chatPath);
    const mutatedChat = chat.replace("!isSseChannel(channel)", "false");
    assert.notEqual(mutatedChat, chat, "反例 A 预备失败：`!isSseChannel(channel)` 未命中，改坏未生效");
    writeFileSync(chatPath, mutatedChat, "utf8");

    const whitelist = guardWhitelistExcludesDeltaChannels(readSource(phase1Path));
    const drop = guardParseSseFrameDropsUnknown(readSource(chatPath));

    assert.equal(whitelist.ok, false, "反例 A 失败：白名单被污染后 G-3② 竟然仍绿（判据恒真）");
    assert.equal(drop.ok, false, "反例 A 失败：守卫被删后 G-3① 竟然仍绿（判据恒真）");
    process.stdout.write(`  [反例A·红] 白名单：${whitelist.detail}\n`);
    process.stdout.write(`  [反例A·红] 守卫：${drop.detail}\n`);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("反例 B · D9② 改坏必红：给 `agent.started` 插 run 匹配守卫 ⇒ G-2a 必红（事实变了要能被发现）", () => {
  const scratch = makeScratchDir("t031-d9-b");
  try {
    const copy = path.join(scratch, "src");
    cpSync(WEB_SRC_DIR, copy, { recursive: true });

    const hookPath = path.join(copy, "hooks/useChatStream.ts");
    const hook = readSource(hookPath);
    const mutated = hook.replace(
      "      const runId = asString(payload.run_id);\n      if (runId) {",
      "      const runId = asString(payload.run_id);\n      if (runId && runId !== store.activeRunId) {",
    );
    assert.notEqual(mutated, hook, "反例 B 预备失败：目标片段未命中，改坏未生效");
    writeFileSync(hookPath, mutated, "utf8");

    const guard = guardActiveRunIdWrittenWithoutMatch(readSource(hookPath));
    assert.equal(guard.ok, false, "反例 B 失败：加了前端守卫后 G-2a 竟然仍绿（判据恒真）");
    process.stdout.write(`  [反例B·红] ${guard.detail}\n`);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("反例 C · G-2b 改坏必红：先裁剪后过滤 / 按 payload 判归属 ⇒ 两条关系式各自转红", () => {
  const scratch = makeScratchDir("t031-d9-c");
  try {
    const original = readSource(SSE_STREAM_TS);

    // 改坏①：先裁剪后过滤（父行 1、3、5 会被判成"洞"）
    const orderBroken = original.replace(
      "continualFrom(selectStreamableRows(rows, options.runId), lastSeq)",
      "continualFrom(rows, lastSeq)",
    );
    assert.notEqual(orderBroken, original, "反例 C① 预备失败：调用点片段未命中，改坏未生效");

    // 改坏②：按帧 payload 判归属（§8.5 明令禁止的载体）
    const columnBroken = original.replace(
      "rows.filter((row) => row.run_id === runId)",
      "rows.filter((row) => (row.payload as { run_id?: string }).run_id === runId)",
    );
    assert.notEqual(columnBroken, original, "反例 C② 预备失败：过滤谓词未命中，改坏未生效");

    const orderGuard = guardFilterBeforeConflation(orderBroken);
    const columnGuard = guardOwnedFilteredByRunIdColumn(columnBroken);

    assert.equal(orderGuard.ok, false, "反例 C① 失败：先裁剪后过滤竟然仍绿（判据恒真）");
    assert.equal(columnGuard.ok, false, "反例 C② 失败：按 payload 判归属竟然仍绿（判据恒真）");
    process.stdout.write(`  [反例C①·红] ${orderGuard.detail}\n`);
    process.stdout.write(`  [反例C②·红] ${columnGuard.detail}\n`);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("对照 D · 同样复制但不改坏 ⇒ 全部守卫必绿（仪器双向验证的另一半）", () => {
  const scratch = makeScratchDir("t031-d9-d");
  try {
    const copy = path.join(scratch, "src");
    cpSync(WEB_SRC_DIR, copy, { recursive: true });

    const drop = guardParseSseFrameDropsUnknown(readSource(path.join(copy, "lib/chat.ts")));
    const whitelist = guardWhitelistExcludesDeltaChannels(readSource(path.join(copy, "types/phase1.ts")));
    const activeRunId = guardActiveRunIdWrittenWithoutMatch(readSource(path.join(copy, "hooks/useChatStream.ts")));

    assert.equal(drop.ok, true, `对照 D 失败（好实现被误判红）：${drop.detail}`);
    assert.equal(whitelist.ok, true, `对照 D 失败（好实现被误判红）：${whitelist.detail}`);
    assert.equal(activeRunId.ok, true, `对照 D 失败（好实现被误判红）：${activeRunId.detail}`);
    process.stdout.write(`  [对照D·绿] 复制整棵 apps/web/src 后三守卫全绿（仪器不是恒红）\n`);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});
