/**
 * V0.3.1 · **D6 游标缺口**判据载体（**入库回归测试**，不是临时探针）。
 *
 * 为什么存在（team-lead 2026-10-23 裁定，逐字）
 * ------------------------------------------
 *   QA 上报：D6 的「无 `seq` 兜底分支去留」裁定责任在 T031-05，而既有 spike 判据
 *   （`subagent-spike.test.mjs`）三条**一条都验不出来** —— 它的 S-2 只验**帧内容归属**
 *   （`data.run_id` 集合），完全不验**游标来源**。
 *
 *   这是**独立的第二种静默崩溃路径**，与 S-2 覆盖的（父流被子 run 的 `agent.completed`
 *   提前终止 / `activeRunId` 被改写）**并列**，同属 K5b。
 *
 *   裁定：不塞进 3 人日 spike 时间盒（三件最不确定的事已定死），作为
 *   **T031-05 出口判据 / T031-06 收口**提前落盘，与 D2/D6/D7/D9 同批验收。
 *
 * 精确坐标
 * --------
 *   - TS 侧对应物：`apps/api/src/modules/run/sse-stream.ts:153` 的 `let lastSeq`
 *     —— **连接级本地水位**。
 *   - py 线原型：`yielded_seq`（`wbtime_ai_api/sse/stream.py:105/124/134/164-170`），
 *     无 `seq` 事件走 `yielded_seq += 1` 的**本地自增兜底**。
 *     TS 侧**没有**叫 `yielded_seq` 的变量 —— 别去找它，要判的是**同一形态**：
 *     「无 seq 事件用什么编号冒充 `id:`」。
 *   - 相关：`continualFrom`（gap-aware 纯函数）、`encodeDataFrame`（`@wbtime/event`）、
 *     `routes/runs.ts` 的 SSE 端点。
 *
 * 危险点（本载体要抓住的东西）
 * --------------------------
 *   兜底分支产出的编号是**连接本地自增**，**不属于任何 run 的 `(run_id, seq)` 空间**。
 *   父子并发下，子 run 的无 `seq` 事件会把**父流的水位顶上去** ⇒ 两种后果之一：
 *     ① 父流**跳帧**（水位被顶高后 `afterSeq + 1` 的期望值对不上真实父 run 事件
 *        ⇒ gap-aware 直接停，客户端永远空回放）；
 *     ② 把子 run 的自增编号**当作父的 `id:` 发出去** ⇒ 前端 `Last-Event-ID` 续传
 *        **拉错 run**。
 *   两者都是**静默崩溃，不是报错**。
 *
 * 为什么 W-1 必须配 W-2 / W-3（`seq` 是 **run 内**序号带来的陷阱）
 * -------------------------------------------------------------
 *   `seq` 是 run 内自 1 起的序号（由 `event-cursor.test.mjs` B-4 钉死）。所以
 *   「子 run 的 `seq=3`」在**数字上**完全可能等于「父 run 的 `seq=3`」：
 *     * 单看 W-1（id 是否落在父空间）会被这种**撞号**骗过；
 *     * 真正的症状是「父 run 自己的那条 `seq=3` 事件**不见了**」（被跳帧）。
 *   故 W-1 除了"id 归属"还加了"**父 run 的帧一帧不落 + 帧内容逐条对上**"，
 *   W-2 则用 payload 探针钉住"无 seq 的那一行**不得**携带任何整数 `id:`"。
 *
 * 载体的两条硬形态（P0-0「命令能跑 ≠ 断言会红」+ P1-3「执行者 ≠ 判定者」）
 * --------------------------------------------------------------------
 *   ① **缺实现 = 断言失败，不是"无法 import"的崩溃**。本文件**不**在顶层 `import`
 *      任何 V0.3.1 新增/改动模块；一律走 §0 的 {@link loadModule} 守卫式动态导入。
 *      缺失 ⇒ `found === false` ⇒ 由 `assert.equal(found, true, …)` 以
 *      **`ERR_ASSERTION`** 红（exit 1），**不是** `ERR_MODULE_NOT_FOUND` 崩在加载期。
 *   ② **单向断言一律配反向断言**。W-3 就是 W-1 / W-2 的反向断言：用"连接本地自增"
 *      参考实现喂进**同一套仪器**，仪器必须报红；同时证明"只有父 run 在跑"时仪器
 *      **不红**（防恒红）。缺任何一半，判据都是恒真/恒假的摆设。
 *
 * 调用契约（**本载体声明，实现方须按此接线**）
 * ------------------------------------------
 *   本文件由 QA 在生产实现**之前**落盘，故下列签名是**判据**而非猜测记录。
 *   实现方若采用不同签名 ⇒ 用例保持红 ⇒ **须回报 QA 改判据，不得改断言迁就实现**
 *   （P0-0 步骤 ③：若修复需要放宽断言 ⇒ 回到 ① 重定）。
 *
 *   - `streamRunFrames({ runId, readAfter, isTerminal, afterSeq, pollIntervalMs,
 *     maxPolls, write, signal })`：`runId` 形参**必须被消费** —— 只下发归属 `runId`
 *     的行；返回的 `lastSeq`（水位）**只能由归属行推进**。
 *   - **无 `seq` 的行**（`row.seq` 缺失），两条路线任选其一，本载体**都判绿**：
 *       · **路线 A（去掉兜底）**：不下发该帧，**且水位不因它前进**，
 *         且**不得让整条流崩掉**（同 `frameOf` 对内部行的既有口径：跳过而非抛错，
 *         见 `sse-stream.ts` 头部注释 —— 一条脏行不许杀整条流）；
 *       · **路线 B（保留兜底）**：可以下发，但必须**显式标记**（帧不带 `id:` 行 /
 *         `id:` 不是非负整数 / `data` 带声明键 `seq_source` `seq_origin`
 *         `watermark_source` / `event` 为声明通道 `stream.unsequenced`
 *         `stream.watermark.unsequenced`），**且该编号的作用域必须是 run 而非
 *         connection**（单条连接的行为无法区分二者 ⇒ 须另有常量声明，见 W-2-3）。
 *     两者之外的形态（**用整数 `id:` 静默冒充** / **抛裸 `RangeError` 杀流**）⇒ 红。
 *
 * 复跑（与 G031-4 · S2 同款）
 * -------------------------
 *   `cd D:/WBT/WBTimeAI && node --experimental-sqlite --test apps/api/tests/sse-watermark.test.mjs`
 *   退出码：**1** = 载体在、门禁未过；文件不存在 = **2**（判据载体缺失，属"未落地"）。
 */

import assert from "node:assert/strict";
import test from "node:test";

import { encodeDataFrame } from "@wbtime/event";

import { makeApp, request } from "./routes-harness.mjs";
import {
  createAgentWithVersion,
  createConversation,
  seedEvent,
  seedRun,
  seedWorkspace,
} from "./fixtures/run-fixture.mjs";

// ---------------------------------------------------------------------------
// §-1 · 常量与测试数据（钉在名字上，不写"第一个匹配的"）
// ---------------------------------------------------------------------------

/** 父 run（与 spike 载体的 `…p1` 区分开，避免两个载体互相污染 id 空间）。 */
const PARENT = "pppppppp-0000-4000-8000-0000000000p2";

/** 子 run。 */
const CHILD = "cccccccc-0000-4000-8000-0000000000c2";

/** 无 `seq` 行的 payload 探针键/值（W-2 靠它把"那一行"认出来）。 */
const PROBE_KEY = "probe";
const PROBE_VALUE = "unsequenced";

/** 冻结件里**结构上不带** `run_id` 的 4 条通道（19 项实测；与 spike 载体同口径）。 */
const CHANNELS_WITHOUT_RUN_ID = Object.freeze([
  "knowledge.indexed",
  "memory.written",
  "approval.requested",
  "approval.decided",
]);

/** "显式标记"的声明形态（路线 B 的识别面）。 */
const DECLARED_MARK_KEYS = Object.freeze(["seq_source", "seq_origin", "watermark_source"]);
const DECLARED_UNSEQUENCED_CHANNELS = Object.freeze([
  "stream.unsequenced",
  "stream.watermark.unsequenced",
]);

/** 路线 B 要求的作用域声明常量候选名（实现方任选其一，或给出同义物）。 */
const POLICY_EXPORT_NAMES = Object.freeze([
  "MISSING_SEQ_POLICY",
  "SEQ_MISSING_POLICY",
  "SEQ_FALLBACK_POLICY",
  "UNSEQUENCED_POLICY",
  "WATERMARK_SCOPE",
  "SEQ_SOURCE_SCOPE",
]);

/**
 * 造一行 `agent_event`（`seq === null` ⇒ **不带 seq**，即 D6 兜底分支的输入）。
 *
 * @param {string} runId
 * @param {number|null} seq `null` ⇒ 缺 seq。
 * @param {number|null} iteration payload 里的身份标记（`null` ⇒ 无 seq 行）。
 * @param {object} [extra] 追加进 payload 的键。
 */
function row(runId, seq, iteration, extra = {}) {
  return {
    run_id: runId,
    ...(seq === null ? {} : { seq }),
    type: "agent.thinking",
    payload: { run_id: runId, iteration, ...extra },
  };
}

/** W-1 / W-4-1 · 父子并发：子 run 的 `seq` 在数字上**接续**父的水位（跨 run 帧 + 跳帧）。 */
const CROSS_RUN_ROWS = Object.freeze([
  row(PARENT, 1, 1),
  row(PARENT, 2, 2),
  row(CHILD, 3, 101),
  row(CHILD, 4, 102),
  row(PARENT, 3, 3),
  row(PARENT, 4, 4),
]);

/** 父 run 的完整 `(run_id, seq)` 空间。 */
const PARENT_SEQS = Object.freeze([1, 2, 3, 4]);

/** W-2a · **父 run 自己**的事件缺 seq —— 最静默：自增编号会与父 run 真 seq **撞号**。 */
const PARENT_UNSEQUENCED_ROWS = Object.freeze([
  row(PARENT, 1, 1),
  row(PARENT, 2, 2),
  row(PARENT, null, null, { [PROBE_KEY]: PROBE_VALUE }),
  row(PARENT, 3, 3),
]);

const PARENT_UNSEQUENCED_SPACE = Object.freeze([1, 2, 3]);

/** W-2b · **子 run** 的事件缺 seq —— 把父流水位顶到父空间**之外**。 */
const CHILD_UNSEQUENCED_ROWS = Object.freeze([
  row(PARENT, 1, 1),
  row(PARENT, 2, 2),
  row(PARENT, 3, 3),
  row(PARENT, 4, 4),
  row(CHILD, null, null, { [PROBE_KEY]: PROBE_VALUE }),
]);

const CHILD_UNSEQUENCED_SPACE = Object.freeze([1, 2, 3, 4]);

// ---------------------------------------------------------------------------
// §0 · 守卫式解析 + 观察面工具（"缺实现 = 断言失败"的机械装置）
// ---------------------------------------------------------------------------

const DOMAIN = Object.freeze({
  sseStream: "../dist/modules/run/sse-stream.js",
  /** V0.3.1 可能新增的水位模块（**假设件**）：不存在 ⇒ `found:false` ⇒ 断言红。 */
  watermark: "../dist/modules/run/sse-watermark.js",
});

/**
 * 守卫式动态导入：存在与不存在返回**同一种形状**，区别只在 `found`。
 *
 * @param {string} spec 相对本文件的模块路径。
 * @returns {{found: boolean, module: object|null, spec: string, reason: string}}
 */
async function loadModule(spec) {
  try {
    return { found: true, module: await import(spec), spec, reason: "" };
  } catch (error) {
    return {
      found: false,
      module: null,
      spec,
      reason: `${spec} :: ${error.code ?? error.constructor.name}`,
    };
  }
}

/**
 * 在若干候选模块里按名字找导出。
 *
 * @param {Array<{found: boolean, module: object|null, spec: string, reason: string}>} loaded
 * @param {string[]} names 候选导出名（按优先级）。
 * @returns {{found: boolean, name: string|null, value: unknown, tried: string[]}}
 */
function pickExport(loaded, names) {
  const tried = [];
  for (const entry of loaded) {
    if (!entry.found || entry.module === null) {
      tried.push(entry.reason);
      continue;
    }
    for (const name of names) {
      const value = entry.module[name];
      if (value !== undefined) return { found: true, name, value, tried };
      tried.push(`${entry.spec} 无导出 ${name}`);
    }
  }
  return { found: false, name: null, value: null, tried };
}

/** SSE 响应体 / 帧文本数组 → 帧文本数组。 */
function splitFrames(body) {
  return body
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk !== "" && chunk.startsWith("id:"));
}

/**
 * 帧文本 → 结构化观察。
 *
 * `seq` 与 `idRaw` **必须分开**：`idRaw === null` 是"根本没有 `id:` 行"，
 * `seq === null` 是"`id:` 行存在但不是非负整数"。两者都是路线 B 的合法标记形态，
 * 而"整数 `seq`"才是可能冒充的那个。
 *
 * @returns {{idRaw: string|null, seq: number|null, event: string|null, data: object|null, raw: string}}
 */
function parseFrame(frame) {
  const idLine = /^id: (.*)$/m.exec(frame);
  const event = /^event: (.+)$/m.exec(frame);
  const data = /^data: (.+)$/m.exec(frame);
  let parsed = null;
  if (data !== null) {
    try {
      parsed = JSON.parse(data[1]);
    } catch {
      parsed = null;
    }
  }
  const idRaw = idLine === null ? null : idLine[1].trim();
  const seq = idRaw !== null && /^\d+$/.test(idRaw) ? Number(idRaw) : null;
  return {
    idRaw,
    seq,
    event: event === null ? null : event[1],
    data: parsed === null || typeof parsed !== "object" || Array.isArray(parsed) ? null : parsed,
    raw: frame,
  };
}

/** 帧是否带**声明标记**（路线 B 的识别面）。 */
function isMarked(parsed) {
  if (parsed.idRaw === null) return true; // 不带 id: 行 ⇒ 客户端拿不到游标
  if (parsed.seq === null) return true; // id: 不是非负整数
  if (parsed.event !== null && DECLARED_UNSEQUENCED_CHANNELS.includes(parsed.event)) return true;
  if (parsed.data !== null && DECLARED_MARK_KEYS.some((key) => Object.hasOwn(parsed.data, key))) {
    return true;
  }
  return false;
}

/**
 * **水位归属审计**（W-1 / W-2b / W-3 的判定仪器）。
 *
 * 四条独立的红：
 *   ① 跨 run 帧进父流（`data.run_id` 既不是父 run、也不在 4 条白名单通道内）；
 *   ② `id:` 落在父 run 的 `(run_id, seq)` 空间之外 —— 该编号**不属于本 run**；
 *   ③ 父 run 本该下发的 seq 有缺失 —— **跳帧**（水位被顶高的直接症状）；
 *   ④ 水位 `lastSeq` 落在父空间之外 —— 被非父 run 的行推进了。
 *
 * @param {object} input
 * @param {string[]} input.frames 已下发帧文本。
 * @param {string} input.parentRunId
 * @param {number[]} input.parentSeqs 父 run **完整**的 seq 空间（归属判定真源）。
 * @param {number[]} [input.expectedSeqs] 本条流**必须**下发的 seq（缺省 = `parentSeqs`）。
 * @param {number|null} input.lastSeq `streamRunFrames` 返回的水位。
 * @param {number} [input.allowedBase] 水位允许的起始值（= 本次的 `afterSeq`）。
 * @returns {{ownedIds: number[], iterations: unknown[], foreign: string[],
 *            unsequenced: string[], violations: string[]}}
 */
function auditWatermark(input) {
  const {
    frames,
    parentRunId,
    parentSeqs,
    expectedSeqs,
    lastSeq,
    allowedBase = 0,
  } = input;
  const must = expectedSeqs ?? parentSeqs;
  const ownedIds = [];
  const iterations = [];
  const foreign = [];
  const unsequenced = [];
  const violations = [];

  for (const frame of frames) {
    const parsed = parseFrame(frame);
    if (parsed.data === null) {
      violations.push(`帧 ${parsed.idRaw ?? "无 id 行"} 的 data 不是 JSON：${frame.replace(/\n/g, "\\n")}`);
      continue;
    }
    const runId = parsed.data.run_id;
    const ownerOk =
      runId === parentRunId ||
      (parsed.event !== null && CHANNELS_WITHOUT_RUN_ID.includes(parsed.event));
    if (!ownerOk) {
      foreign.push(`id=${parsed.idRaw ?? "无 id 行"} run_id=${String(runId)}`);
      violations.push(
        `跨 run 帧进父流：id=${parsed.idRaw ?? "无 id 行"} run_id=${String(runId)} ` +
          `event=${parsed.event ?? "?"} —— 父流只许下发 ${parentRunId} 的事件（D2 / D6）`
      );
      continue;
    }
    if (parsed.seq === null) {
      unsequenced.push(`id=${parsed.idRaw ?? "无 id 行"} event=${parsed.event ?? "?"}`);
      continue;
    }
    if (!parentSeqs.includes(parsed.seq)) {
      foreign.push(`id=${parsed.seq} run_id=${String(runId)}`);
      violations.push(
        `id: ${parsed.seq} 不在父 run 的 (run_id, seq) 空间 [${parentSeqs.join(",")}] 内 ` +
          `—— 该编号不属于本 run（W-1）`
      );
      continue;
    }
    ownedIds.push(parsed.seq);
    iterations.push(parsed.data.iteration ?? null);
  }

  const missing = must.filter((seq) => !ownedIds.includes(seq));
  if (missing.length > 0) {
    violations.push(
      `父 run 的 seq [${missing.join(",")}] 一帧都没下发 —— 水位被顶高后的**跳帧**` +
        `（客户端永远空回放；实测下发 ${ownedIds.join(",") || "空"}）`
    );
  }

  if (lastSeq !== null && lastSeq !== allowedBase && !parentSeqs.includes(lastSeq)) {
    violations.push(
      `水位 lastSeq=${lastSeq} 落在父 run 的 (run_id, seq) 空间 [${parentSeqs.join(",")}] 之外 ` +
        `—— 水位被非父 run 的行推进（D6 静默崩溃路径①）`
    );
  }

  return { ownedIds, iterations, foreign, unsequenced, violations };
}

/**
 * 把一次"无 seq 行"的观察归一成 `{ recognized, kind }`。
 *
 * `recognized: false`（`kind: "crash"`）⇔ 整条流被抛错打断 ⇒ 调用方**必须**先断言
 * `recognized === true`。少了这一条，"流崩了 ⇒ 没下发 ⇒ 视为拒绝"就是**假绿**。
 *
 * @param {{threw: boolean, frames: string[], lastSeq: number|null, error: unknown}} outcome
 * @returns {{recognized: boolean, kind: "rejected"|"marked"|"silent"|"crash",
 *            shape: string, probeFrames: object[]}}
 */
function normalizeUnsequenced(outcome) {
  if (outcome.threw) {
    const error = outcome.error;
    return {
      recognized: false,
      kind: "crash",
      shape: `threw ${error?.name ?? "?"}: ${String(error?.message ?? "")}`,
      probeFrames: [],
    };
  }
  const probeFrames = outcome.frames
    .map(parseFrame)
    .filter((parsed) => parsed.data !== null && parsed.data[PROBE_KEY] === PROBE_VALUE);

  if (probeFrames.length === 0) {
    return { recognized: true, kind: "rejected", shape: "未下发该帧（流未崩）", probeFrames: [] };
  }
  const unmarked = probeFrames.filter((parsed) => !isMarked(parsed));
  if (unmarked.length === 0) {
    return {
      recognized: true,
      kind: "marked",
      shape: `带声明标记下发 ×${probeFrames.length}`,
      probeFrames,
    };
  }
  return {
    recognized: true,
    kind: "silent",
    shape: `以整数 id 静默下发：${unmarked.map((parsed) => parsed.idRaw).join(",")}`,
    probeFrames,
  };
}

/**
 * 跑一次 `streamRunFrames`（不抛错；"崩"体现在 `threw`）。
 *
 * @param {Function} fn
 * @param {{rows: object[], runId: string, afterSeq?: number}} options
 */
async function probeStream(fn, options) {
  const frames = [];
  try {
    const result = await fn({
      runId: options.runId,
      readAfter: async () => options.rows,
      isTerminal: async () => true,
      afterSeq: options.afterSeq ?? 0,
      pollIntervalMs: 0,
      maxPolls: 1,
      write: (frame) => frames.push(frame.toString()),
    });
    return { threw: false, frames, lastSeq: result?.lastSeq ?? null, result, error: null };
  } catch (error) {
    return { threw: true, frames, lastSeq: null, result: null, error };
  }
}

/**
 * **参考实现**：`yielded_seq` 式**连接本地自增兜底**（py 线原型 `sse/stream.py` 的形态，
 * 也是 `sse-stream.ts:153` `let lastSeq` 的对应物）。
 *
 * 这不是生产实现，是判据的**反向标尺**：把它喂给同一套仪器，仪器**必须**报红（W-3）。
 * 它同时是反例 `v031-watermark-local-increment` 要改成的样子。
 *
 * 建模口径：兜底编号从**当前连接水位**派生（`lastSeq + 1`），不是独立从 0 计数 ——
 * 唯有如此"子 run 的无 seq 事件把父流水位顶上去"（D6 路径①）才可复现。
 *
 * @param {{rows: object[], afterSeq?: number}} options
 */
function localIncrementStream(options) {
  const afterSeq = options.afterSeq ?? 0;
  let lastSeq = afterSeq;
  const frames = [];
  for (const item of options.rows) {
    // 无 seq ⇒ 连接本地水位 + 1（**不属于任何 run 的 (run_id, seq) 空间**）
    const seq = Number.isInteger(item.seq) ? item.seq : lastSeq + 1;
    frames.push(encodeDataFrame(seq, item.type, item.payload ?? {}).toString());
    lastSeq = seq;
  }
  return { frames, lastSeq, reason: "terminal" };
}

/** 路线 B 的作用域声明常量是否真的说了"run"（而不是 connection）。 */
function policyMentionsRun(value) {
  if (typeof value === "string") return /run/i.test(value);
  if (value !== null && typeof value === "object") {
    for (const key of ["scope", "kind", "of", "source"]) {
      if (typeof value[key] === "string" && /run/i.test(value[key])) return true;
    }
  }
  return false;
}

// 顶层一次性解析（不抛错；缺实现只体现在 `found === false`）。
const MODULES = {
  sseStream: await loadModule(DOMAIN.sseStream),
  watermark: await loadModule(DOMAIN.watermark),
};

const STREAM_FN = pickExport([MODULES.sseStream], ["streamRunFrames", "stream_run"]);
const CONTINUAL_FN = pickExport([MODULES.sseStream], ["continualFrom"]);
const POLICY = pickExport([MODULES.sseStream, MODULES.watermark], [...POLICY_EXPORT_NAMES]);

// ---------------------------------------------------------------------------
// §0 · 仪器自证（先证明"尺子"是准的，再拿它去量实现）
// ---------------------------------------------------------------------------

test("0-1 · 仪器自证：帧解析器区分「无 id: 行」「非整数 id」「整数 id」三种形态", () => {
  const [withId] = splitFrames('id: 7\nevent: agent.thinking\ndata: {"run_id":"p","iteration":7}\n\n');
  const parsed = parseFrame(withId);
  assert.equal(parsed.seq, 7);
  assert.equal(parsed.idRaw, "7");
  assert.equal(parsed.event, "agent.thinking");
  assert.deepEqual(parsed.data, { run_id: "p", iteration: 7 });

  // 标记形态 ①：不带 id: 行 ⇒ 客户端拿不到游标。
  const noId = parseFrame('event: agent.thinking\ndata: {"run_id":"p"}\n');
  assert.equal(noId.idRaw, null);
  assert.equal(noId.seq, null);
  assert.equal(isMarked(noId), true);

  // 标记形态 ②：id: 不是非负整数。
  const nullId = parseFrame('id: null\nevent: agent.thinking\ndata: {"run_id":"p"}\n');
  assert.equal(nullId.idRaw, "null");
  assert.equal(nullId.seq, null);
  assert.equal(isMarked(nullId), true);

  // 未标记：整数 id ⇒ 可被客户端当作游标续传 ⇒ 冒充风险面。
  assert.equal(isMarked(parsed), false);
});

test("0-2 · 仪器自证：父 run 独占流 ⇒ 审计**不红**（防恒红 / 防把判据写成一红到底）", () => {
  const frames = PARENT_SEQS.map((seq) =>
    encodeDataFrame(seq, "agent.thinking", { run_id: PARENT, iteration: seq }).toString()
  );
  const audit = auditWatermark({
    frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_SEQS,
    lastSeq: 4,
  });
  assert.deepEqual(audit.violations, [], "父 run 独占时必须全绿，否则仪器是恒红的摆设");
  assert.deepEqual(audit.ownedIds, [1, 2, 3, 4]);
  assert.deepEqual(audit.foreign, []);
});

test("0-3 · 仪器自证：携带子 run 编号的流 ⇒ 审计**必红**（防恒绿 / 防假绿）", () => {
  const frames = [
    encodeDataFrame(1, "agent.thinking", { run_id: PARENT, iteration: 1 }).toString(),
    encodeDataFrame(3, "agent.thinking", { run_id: CHILD, iteration: 101 }).toString(),
  ];
  const audit = auditWatermark({
    frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_SEQS,
    lastSeq: 3,
  });
  assert.equal(
    audit.violations.length >= 1,
    true,
    "子 run 的帧进父流必须被审计判红，否则 W-1 是恒真的摆设"
  );
  assert.deepEqual(audit.foreign, [`id=3 run_id=${CHILD}`]);
});

test("0-4 · 仪器自证：单独构造「水位被顶到父空间外」也能被抓住", () => {
  const frames = PARENT_SEQS.map((seq) =>
    encodeDataFrame(seq, "agent.thinking", { run_id: PARENT, iteration: seq }).toString()
  );
  // 帧全部干净，但水位被顶到 5（父空间是 1..4）—— 只有水位检查能抓到。
  const audit = auditWatermark({
    frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_SEQS,
    lastSeq: 5,
  });
  assert.deepEqual(audit.foreign, [], "帧面是干净的");
  assert.equal(
    audit.violations.some((line) => line.includes("水位 lastSeq=5")),
    true,
    "水位落在父空间之外必须单独成红（D6 路径①）"
  );
});

test("0-5 · 仪器自证：流崩掉 ⇒ normalizeUnsequenced 判 crash/unrecognized（防假绿）", () => {
  const crashed = normalizeUnsequenced({
    threw: true,
    frames: [],
    lastSeq: null,
    error: new RangeError("encodeDataFrame: seq 必须是非负整数，收到 undefined"),
  });
  assert.deepEqual(
    { recognized: crashed.recognized, kind: crashed.kind },
    { recognized: false, kind: "crash" },
    "崩掉必须判 unrecognized —— 否则「流崩了 ⇒ 没下发 ⇒ 视为显式拒绝」就是假绿"
  );

  const dropped = normalizeUnsequenced({ threw: false, frames: [], lastSeq: 3 });
  assert.deepEqual(
    { recognized: dropped.recognized, kind: dropped.kind },
    { recognized: true, kind: "rejected" }
  );
});

test("0-6 · 仪器自证：参考实现确实是「连接本地自增」（标尺本身没写错）", () => {
  const outcome = localIncrementStream({ rows: PARENT_UNSEQUENCED_ROWS });
  // P1→1, P2→2, 无 seq→3（水位 +1）, P3 真 seq=3 ⇒ 两个 id 都是 3（撞号）。
  assert.deepEqual(
    outcome.frames.map((frame) => parseFrame(frame).seq),
    [1, 2, 3, 3],
    "参考实现必须真的产出「本地自增编号与父 run 真 seq 撞号」的形态"
  );
  assert.equal(outcome.lastSeq, 3);
  const verdict = normalizeUnsequenced({ threw: false, frames: outcome.frames, lastSeq: 3 });
  assert.equal(
    verdict.kind,
    "silent",
    "撞号形态下 W-1 的「id 落在父空间内」是绿的 —— 只有 W-2 的探针能抓住它"
  );
});

// ---------------------------------------------------------------------------
// §1 · W-1 · 水位归属：父流的每个 `id:` 必须落在父 run 的 `(run_id, seq)` 空间内
// ---------------------------------------------------------------------------

test("W-0 · 判据载体：streamRunFrames / continualFrom 就位", () => {
  assert.equal(
    STREAM_FN.found,
    true,
    `apps/api/src/modules/run/sse-stream.ts 必须导出 streamRunFrames；实测：${STREAM_FN.tried.join(" | ")}`
  );
  assert.equal(typeof STREAM_FN.value, "function", `streamRunFrames 必须是函数，实测 ${typeof STREAM_FN.value}`);
  assert.equal(CONTINUAL_FN.found, true, `continualFrom 必须仍可导出；实测：${CONTINUAL_FN.tried.join(" | ")}`);
});

test("W-1 · 父子并发：父流每个 id: 全在父 run 的 (run_id, seq) 空间内，且父 run 的帧一帧不落", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  const outcome = await probeStream(STREAM_FN.value, { rows: CROSS_RUN_ROWS, runId: PARENT });
  assert.equal(
    outcome.threw,
    false,
    `父流不得崩（本次异常：${String(outcome.error?.message ?? "无")}）`
  );

  const audit = auditWatermark({
    frames: outcome.frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_SEQS,
    expectedSeqs: PARENT_SEQS,
    lastSeq: outcome.lastSeq,
    allowedBase: 0,
  });
  assert.deepEqual(audit.violations, [], "父流出现不属于父 run 的编号 ⇒ 立即红（W-1）");
  assert.deepEqual(audit.ownedIds, [1, 2, 3, 4], "父 run 的 4 帧必须按序全下发，不得跳帧");
  assert.deepEqual(audit.iterations, [1, 2, 3, 4], "下发的必须是父 run 的真事件（iteration 1..4）");
  assert.equal(outcome.lastSeq, 4, "水位只能停在父 run 自己的最后一条 seq 上");
});

// ---------------------------------------------------------------------------
// §2 · W-2 · 无 `seq` 兜底：要么显式拒绝、要么显式标记，不得静默自增冒充
// ---------------------------------------------------------------------------

test("W-2a · 父 run 自己的事件缺 seq ⇒ 不得用整数 id: 静默冒充（撞号场景）", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  const outcome = await probeStream(STREAM_FN.value, {
    rows: PARENT_UNSEQUENCED_ROWS,
    runId: PARENT,
  });
  assert.equal(
    outcome.threw,
    false,
    "无 seq 的行**不得让整条流崩掉** —— 与 `frameOf` 对内部行的既有口径一致" +
      "（跳过而非抛错：一条脏行不许杀整条流）。" +
      `本次异常：${String(outcome.error?.message ?? "无")}`
  );

  const verdict = normalizeUnsequenced(outcome);
  assert.equal(verdict.recognized, true, `必须先能识别形态（实测 ${verdict.shape}）`);
  assert.notEqual(
    verdict.kind,
    "silent",
    "无 seq 的行**不得**携带任何整数 id: 冒充父 run 的游标（D6 静默崩溃路径②）"
  );

  const audit = auditWatermark({
    frames: outcome.frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_UNSEQUENCED_SPACE,
    expectedSeqs: PARENT_UNSEQUENCED_SPACE,
    lastSeq: outcome.lastSeq,
    allowedBase: 0,
  });
  assert.deepEqual(audit.violations, [], "父流不得出现越界编号 / 越界水位");
  assert.deepEqual(
    audit.iterations,
    [1, 2, 3],
    "父 run 的三条真事件必须原样下发（iteration 1,2,3）；" +
      "若 id:3 的帧是自增编号冒充的，这里会退化成 [1,2,null] —— 跳帧被内容层抓住"
  );
});

test("W-2b · 子 run 的事件缺 seq ⇒ 既不得进父流，也不得把父流水位顶高", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  const outcome = await probeStream(STREAM_FN.value, {
    rows: CHILD_UNSEQUENCED_ROWS,
    runId: PARENT,
  });
  assert.equal(
    outcome.threw,
    false,
    `父流不得崩（本次异常：${String(outcome.error?.message ?? "无")}）`
  );

  const verdict = normalizeUnsequenced(outcome);
  assert.equal(verdict.recognized, true, `必须先能识别形态（实测 ${verdict.shape}）`);
  assert.notEqual(verdict.kind, "silent", "子 run 的无 seq 事件不得顶着父 run 的 id: 下发");

  const audit = auditWatermark({
    frames: outcome.frames,
    parentRunId: PARENT,
    parentSeqs: CHILD_UNSEQUENCED_SPACE,
    expectedSeqs: CHILD_UNSEQUENCED_SPACE,
    lastSeq: outcome.lastSeq,
    allowedBase: 0,
  });
  assert.deepEqual(audit.violations, [], "父流的编号与水位都必须留在父 run 的空间内（W-1 + D6 路径①）");
  assert.deepEqual(audit.ownedIds, [1, 2, 3, 4], "父 run 的 4 帧一帧不落");
  assert.equal(
    outcome.lastSeq,
    4,
    "水位必须停在父 run 的最后一条真 seq 上 —— 被无 seq 的子 run 行顶到 5 即为静默崩溃"
  );
});

test("W-2-3 · 裁定登记：选「保留兜底」(marked) 必须有可机械判定的 run 作用域声明", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  const outcome = await probeStream(STREAM_FN.value, {
    rows: CHILD_UNSEQUENCED_ROWS,
    runId: PARENT,
  });
  const verdict = normalizeUnsequenced(outcome);

  // 只测一个方向会被"一律拒绝"蒙混过关，也会把"静默自增"当成合法实现 ⇒ 本条双判。
  assert.notEqual(verdict.kind, "crash", "整条流崩掉不算「显式拒绝」（见 W-2a）");
  assert.notEqual(verdict.kind, "silent", "静默用整数 id: 冒充 ⇒ 红");

  if (verdict.kind === "marked") {
    assert.equal(
      POLICY.found,
      true,
      "实现选择了「保留兜底并显式标记」⇒ 必须另有常量声明该编号的作用域是 **run** 而非 " +
        "connection —— 单条连接的行为**无法**区分二者，缺声明则「隔离」不可机械判定。" +
        `候选导出名 ${POLICY_EXPORT_NAMES.join("/")}；实测：${POLICY.tried.join(" | ")}`
    );
    assert.equal(
      policyMentionsRun(POLICY.value),
      true,
      `作用域常量必须落在 run 上（实测 ${POLICY.name} = ${JSON.stringify(POLICY.value)}）`
    );
  }
  // kind === "rejected"（去掉兜底）⇒ 本条不适用，无需常量声明。
});

// ---------------------------------------------------------------------------
// §3 · W-3 · 反向断言（防假绿）：判据**真的会红**
// ---------------------------------------------------------------------------

test("W-3-1 · 反向断言：喂「连接本地自增」参考实现 ⇒ W-1 / W-2 的仪器必须转红", () => {
  // ① W-1 的仪器（跨 run 帧 + 跳帧）：子 run 的 seq 数字上接续父的水位。
  const crossRun = localIncrementStream({ rows: CROSS_RUN_ROWS });
  const crossAudit = auditWatermark({
    frames: crossRun.frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_SEQS,
    expectedSeqs: PARENT_SEQS,
    lastSeq: crossRun.lastSeq,
  });
  assert.equal(
    crossAudit.violations.length >= 2,
    true,
    "本地自增实现下 W-1 必须转红（跨 run 帧 + 父 run 跳帧），否则 W-1 是恒真的摆设"
  );
  assert.equal(
    crossAudit.foreign.length >= 1,
    true,
    `必须抓到跨 run 帧；实测 foreign=${JSON.stringify(crossAudit.foreign)}`
  );

  // ② W-2a 的仪器（撞号 ⇒ 只有探针能抓住）。
  const parentUnseq = localIncrementStream({ rows: PARENT_UNSEQUENCED_ROWS });
  assert.equal(
    normalizeUnsequenced({ threw: false, frames: parentUnseq.frames, lastSeq: parentUnseq.lastSeq })
      .kind,
    "silent",
    "本地自增实现下 W-2a 必须转红 —— 这条证明「id 全在父空间内」并不足以判绿"
  );

  // ③ W-2b 的仪器（水位被顶到父空间外）。
  const childUnseq = localIncrementStream({ rows: CHILD_UNSEQUENCED_ROWS });
  const childAudit = auditWatermark({
    frames: childUnseq.frames,
    parentRunId: PARENT,
    parentSeqs: CHILD_UNSEQUENCED_SPACE,
    expectedSeqs: CHILD_UNSEQUENCED_SPACE,
    lastSeq: childUnseq.lastSeq,
  });
  assert.equal(
    childAudit.violations.length >= 2,
    true,
    "本地自增实现下 W-2b 必须转红（跨 run 帧 + 水位越界）"
  );
  assert.equal(childUnseq.lastSeq, 5, "参考实现把水位顶到了父空间之外的 5");
});

test("W-3-2 · 反向断言的另一半：正确（按 run 隔离）实现 ⇒ 同一套仪器**必须绿**", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  // 模拟"正确实现"的产出：先按 runId 归属过滤，再走同一条流。
  const scoped = CROSS_RUN_ROWS.filter((item) => item.run_id === PARENT);
  const outcome = await probeStream(STREAM_FN.value, { rows: scoped, runId: PARENT });
  assert.equal(outcome.threw, false, `不得崩（${String(outcome.error?.message ?? "无")}）`);

  const audit = auditWatermark({
    frames: outcome.frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_SEQS,
    expectedSeqs: PARENT_SEQS,
    lastSeq: outcome.lastSeq,
  });
  assert.deepEqual(
    audit.violations,
    [],
    "按 run 隔离的流必须全绿 —— 若这里也红，说明仪器是恒红的摆设（W-3 的另一半）"
  );
});

// ---------------------------------------------------------------------------
// §4 · W-4 · `Last-Event-ID` 续传不串 run
// ---------------------------------------------------------------------------

test("W-4-1 · 单元层续传：拿父流的 id: 续传 ⇒ 拉回的必须仍是父 run 的事件", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  // 客户端上一轮拿到最后一个 id: 2（属于父 run），用它续传。
  const outcome = await probeStream(STREAM_FN.value, {
    rows: CROSS_RUN_ROWS,
    runId: PARENT,
    afterSeq: 2,
  });
  assert.equal(outcome.threw, false, `不得崩（${String(outcome.error?.message ?? "无")}）`);

  const audit = auditWatermark({
    frames: outcome.frames,
    parentRunId: PARENT,
    parentSeqs: PARENT_SEQS,
    expectedSeqs: [3, 4],
    lastSeq: outcome.lastSeq,
    allowedBase: 2,
  });
  assert.deepEqual(
    audit.violations,
    [],
    "用父流的 id 续传却拉回别的 run 的编号 ⇒ 前端 Last-Event-ID 拉错 run（D6 路径②）"
  );
  assert.deepEqual(audit.ownedIds, [3, 4], "续传只应补父 run 的 3、4 两帧");
  assert.deepEqual(audit.iterations, [3, 4], "拉回的必须是父 run 的真事件，不是同号的子 run 事件");
});

test("W-4-2 · 真链路：Last-Event-ID 续传 + 同号不串 run（**回归护栏**，非 D6 判别面）", async () => {
  // ⚠️ 与 R-2 同构的假绿风险：`RunEventRepo.listAfter` **已在仓储层按 run_id 过滤**，
  //    `GET /runs/{id}/events` 根本喂不进跨 run 行 ⇒ 本条**结构上抓不到** D6 的越界水位。
  //    它在此的作用是**回归护栏**：钉住"同号不同 run 不串"，一旦将来有人去掉仓储层的
  //    run_id 过滤，本条立刻红。D6 的判别面是 W-1 / W-2 / W-4-1（单元层，可喂跨 run 行）。
  const fixture = await makeApp({ username: "wm-w4" });
  try {
    seedWorkspace(fixture);
    const { agentId, versionId } = await createAgentWithVersion(fixture, "wm-parent-agent");
    const conversationId = await createConversation(fixture, agentId);
    const parentRunId = seedRun(fixture, {
      agentId,
      versionId,
      conversationId,
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
    });
    const childRunId = seedRun(fixture, {
      agentId,
      versionId,
      conversationId,
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
    });

    // 父 run 4 条（seq 1..4）；子 run 6 条（seq 1..6）—— seq 是 run 内序号，故意重叠。
    for (const seq of [1, 2, 3, 4]) {
      seedEvent(fixture, parentRunId, seq, "agent.thinking", {
        run_id: parentRunId,
        iteration: seq,
      });
    }
    for (const seq of [1, 2, 3, 4, 5, 6]) {
      seedEvent(fixture, childRunId, seq, "agent.thinking", {
        run_id: childRunId,
        iteration: 100 + seq,
      });
    }

    const first = await request(fixture, "GET", `/api/v1/runs/${parentRunId}/events?after_seq=0`);
    assert.equal(first.statusCode, 200);
    const firstFrames = splitFrames(first.body).map(parseFrame);
    assert.deepEqual(
      firstFrames.map((parsed) => parsed.seq),
      [1, 2, 3, 4]
    );
    const lastId = firstFrames[firstFrames.length - 1].seq;
    assert.equal(lastId, 4);

    // ① 用父流最后拿到的 id 续传父 run ⇒ 空（父 run 没有 5+）。
    const resumed = await fixture.app.inject({
      method: "GET",
      url: `/api/v1/runs/${parentRunId}/events`,
      headers: { authorization: fixture.authHeader, "last-event-id": String(lastId) },
    });
    assert.equal(resumed.statusCode, 200);
    assert.deepEqual(splitFrames(resumed.body).map((frame) => parseFrame(frame).seq), []);

    // ② 同一个 id 拿去续传**子** run ⇒ 拉回的必须是子 run 自己的 5、6，不是父 run 的事件。
    const onChild = await fixture.app.inject({
      method: "GET",
      url: `/api/v1/runs/${childRunId}/events`,
      headers: { authorization: fixture.authHeader, "last-event-id": String(lastId) },
    });
    assert.equal(onChild.statusCode, 200);
    const childFrames = splitFrames(onChild.body).map(parseFrame);
    assert.deepEqual(
      childFrames.map((parsed) => parsed.seq),
      [5, 6],
      "同号不同 run 不得串：Last-Event-ID=4 续传子 run 只能补子 run 自己的 5、6"
    );
    for (const parsed of childFrames) {
      assert.equal(
        parsed.data.run_id,
        childRunId,
        "续传拉回的帧必须全部属于被请求的 run（不得混入父 run 的事件）"
      );
    }

    // ③ 父 run 从头再拉一次 ⇒ 帧全部属于父 run（串 run 的话这里会出现子 run 的编号）。
    const parentAudit = auditWatermark({
      frames: splitFrames(first.body),
      parentRunId,
      parentSeqs: [1, 2, 3, 4],
      lastSeq: lastId,
    });
    assert.deepEqual(parentAudit.violations, [], "父流的 id 与帧必须全部落在父 run 的空间内");
  } finally {
    await fixture.close();
  }
});
