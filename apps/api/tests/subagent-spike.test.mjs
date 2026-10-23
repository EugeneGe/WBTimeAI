/**
 * V0.3.1 · G031-4 spike 判据载体（**入库回归测试**，不是临时探针）。
 *
 * 三件最不确定的事（K2 / 施工链 §3.1 G031-4 逐字）
 * ---------------------------------------------
 *   S-1 `origin` 豁免不破第二个用户 run 的 409（K3 / D8 / D10）
 *   S-2 流隔离后 19 帧全等（K4 / D2 / D6）
 *   S-3 子 run 深度守卫可拦（D1）
 *
 * 载体的两条硬形态（P0-0「命令能跑 ≠ 断言会红」+ P1-3「执行者 ≠ 判定者」）
 * --------------------------------------------------------------------
 *   ① **缺实现 = 断言失败，不是"无法 import"的崩溃**。
 *      本文件**不**在顶层 `import` 任何 V0.3.1 新增模块（那会以 `ERR_MODULE_NOT_FOUND`
 *      崩在加载期，与"载体自己写坏了"不可分）。所有新增模块一律走 §0 的
 *      {@link loadModule} 守卫式动态导入：缺失 ⇒ 解析结果 `found === false` ⇒
 *      由 `assert.equal(found, true, …)` 以**断言失败**的形式红（exit 1）。
 *   ② **单向断言一律配反向断言**。S-1 双向、S-2 双向（传 `runId` / 不传 `runId`）、
 *      S-3 双向（depth=0 放行 / depth=1 拒绝）。只测一个方向的断言会被"恒真实现"
 *      或"恒假实现"蒙混过关。
 *
 * 调用契约（**本载体声明，实现方须按此接线**）
 * ------------------------------------------
 *   本文件由 QA 在生产实现**之前**落盘，故下列签名是**判据**而非猜测记录。
 *   实现方若采用不同签名 ⇒ 用例保持红 ⇒ **须回报 QA 改判据，不得改断言迁就实现**
 *   （P0-0 步骤 ③：若修复需要放宽断言 ⇒ 回到 ① 重定）。
 *
 *   - `packages/domain/src/runtime/subagent.ts` 导出
 *     `RUN_TRIGGER_SUBAGENT`（= `"subagent"`）、`RUN_ORIGIN_SUBAGENT`（= `"SUBAGENT"`）、
 *     `MAX_SUBAGENT_DEPTH`（缺省 `1`）。
 *   - `guardRunCreation({ db, dialect, tenantId, conversationId, origin, trigger })`
 *     → `{ allowed: boolean }` / `{ conflict: boolean }` / `{ ok: boolean }`，
 *       或被拒时抛 `status === 409` 的 `HttpException`。
 *       **`trigger` 仅标记、不参与放行**（D10）。
 *   - `streamRunFrames({ runId, readAfter, isTerminal, write, … })`
 *     → 只下发归属于 `runId` 的帧。**归属判在行级 `agent_event.run_id` 列**，
 *       不判在帧 payload（架构裁定 §8.5：帧 payload 是投影产物，带不带 `run_id`
 *       取决于通道定义，把门禁建在那上面等于建在偶然事实上）。
 *       ⚠️ `runId` 形参**当前不存在**（`StreamRunFramesOptions` 无此字段），
 *       由 T031-05 增；本载体按《调用契约》先写，T031-05 落地后转绿。
 *   - `SubAgentSpawner`（`apps/api/src/modules/run/subagent-spawner.ts`）具
 *     `spawn` / `spawnChild` / `trySpawn` 之一，单对象入参
 *     `{ db, dialect, tenantId, maxDepth }` / `{ parentRunId, targetAgentId,
 *     targetVersionId, conversationId, task, depth, maxDepth }`。
 *
 * 复跑（G031-4 · S2）
 * ------------------
 *   `cd D:/WBT/WBTimeAI && node --experimental-sqlite --test apps/api/tests/subagent-spike.test.mjs`
 *   退出码：**1** = 载体在、门禁未过；文件不存在 = **2**（判据载体缺失，属"未落地"）。
 */

import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { BUILTIN_TOOLS } from "@wbtime/db";

import { BUILTIN_REGISTRY, registeredToolNames } from "../dist/modules/tool/registry.js";
import { fakeGateway, makeApp, ROOT, TENANT_ID } from "./routes-harness.mjs";
import {
  createAgentWithVersion,
  createConversation,
  seedRun,
  seedWorkspace,
} from "./fixtures/run-fixture.mjs";

// ---------------------------------------------------------------------------
// §0 · 守卫式解析 + 观察面工具（"缺实现 = 断言失败"的机械装置）
// ---------------------------------------------------------------------------

/** 生产实现未落地时，`spawner` / `guard` / `spawnAgentTool` / `domainSubagent` 都不存在。 */
const DOMAIN = Object.freeze({
  runService: "../dist/modules/run/run-service.js",
  coordinator: "../dist/modules/run/coordinator.js",
  sseStream: "../dist/modules/run/sse-stream.js",
  spawner: "../dist/modules/run/subagent-spawner.js",
  delegation: "../dist/modules/run/delegation.js",
  guard: "../dist/modules/run/subagent-guard.js",
  spawnAgentTool: "../dist/modules/tool/builtin/spawn-agent.js",
  // `apps/api/tests/` → `../../../` 才是仓库根（`ROOT` 用的是同一个三跳）。
  domainRuntime: "../../../packages/domain/dist/runtime/index.js",
  domainSubagent: "../../../packages/domain/dist/runtime/subagent.js",
  /**
   * **裸包名**候选：注入引擎只在克隆里放 `contracts / scripts / apps/api / output`，
   * 不放 `packages/` —— 相对路径候选在克隆里会永远解析不到，那会让 V031 反例
   * **永久 UNEVALUABLE**（把判据写成不可判）。裸包名走 `apps/api/node_modules`
   * （克隆里是链接到真树）⇒ 真树与克隆**同源**，两处都能解析。
   */
  domainPackage: "@wbtime/domain",
});

/**
 * 守卫式动态导入。
 *
 * 存在的模块与不存在的模块返回**同一种形状**，区别只在 `found`。
 * 这样"缺实现"永远走断言分支，绝不会以 `ERR_MODULE_NOT_FOUND` 崩在加载期
 * —— 崩在加载期会让"实现没落地"与"载体自己写坏了"不可分（G031-4 的 exit 1/2 语义）。
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

/** 冻结通道表（`contracts/sse/channels.json`），只读一次。 */
const CHANNELS_DOCUMENT = JSON.parse(
  readFileSync(join(ROOT, "contracts", "sse", "channels.json"), "utf8")
);

/**
 * **机器导出**的「帧数据不带 `run_id`」的通道集合。
 *
 * 为什么不用手写名单（架构裁定 §8.5，2026-10-23）：
 *   手写名单会与冻结件**漂移**。冻结件新增一条不带 `run_id` 的通道时，手写名单不变
 *   ⇒ 该通道要么被 D2-a 的「缺键即红」误判成违规，要么（更糟）静默躲过断言。
 *   改为从冻结件的 `projected_fields` 导出 ⇒ 冻结件一变，集合自动变长，该通道自动
 *   从 D2-a 的覆盖里**露出**，由 `0-5` 用例把它顶红 ⇒ 强制重新裁定 D2-a/D2-b 划分。
 *
 * 为什么取 `projected_fields` 而不是 `payload_keys_in_order`：
 *   帧 `data` 是**投影产物**。`message.delta` 就是反例 ——
 *   `payload_keys_in_order` 里有 `content`，而 `projected_fields` 是 `delta`
 *   （`projection.rule = "content -> delta"`）。判据必须落在**帧里实际有什么**上。
 *   （本仓这两列对「是否含 `run_id`」的判定**一致**，19 条逐条核过，见台账 §2。）
 */
const CHANNELS_WITHOUT_RUN_ID = Object.freeze(
  CHANNELS_DOCUMENT.channels
    .filter((channel) => !(channel.projected_fields ?? []).includes("run_id"))
    .map((channel) => channel.channel)
);

/** SSE 响应体 / 帧文本数组 → 帧文本数组。 */
function splitFrames(body) {
  return body
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk !== "" && chunk.startsWith("id:"));
}

/** 帧文本 → `{ seq, event, data }`；`data:` 非 JSON ⇒ `data` 为 `null`。 */
function parseFrame(frame) {
  const seq = /^id: (\d+)$/m.exec(frame);
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
  return {
    seq: seq === null ? null : Number(seq[1]),
    event: event === null ? null : event[1],
    data: parsed,
  };
}

/**
 * 帧 → `run_id` 集合（**D2 的判定仪器**）。
 *
 * ⚠️ D2 已被架构**拆分裁定**（2026-10-23，`02-施工/README.md` §8.5），本仪器按定稿执行：
 *
 *   - **D2-a**（帧数据**带** `run_id` 的 15 条）：「缺键即红」**原样保留** ——
 *     原 D2 写的「若某帧 `data` 中缺 `run_id`，判为立即红（不当作无关帧跳过）」，
 *     在这 15 条上是对的，逐字执行。
 *   - **D2-b**（帧数据**不带** `run_id` 的 4 条：`knowledge.indexed` /
 *     `memory.written` / `approval.requested` / `approval.decided`）：
 *     帧 payload 里**根本没有**这个键（实测 `projected_fields` 无 `run_id`，
 *     且 `projection` 为 `null`，不存在「投影时补上」），逐字执行 D2 会**恒红**。
 *     这 4 条改按**来源行的 `agent_event.run_id` 列**判归属（见 S-2-3）。
 *
 * 裁定的核心依据（原文）：**「把归属判据挂在投影产物上，等于把门禁建在
 * 「哪些通道恰好带这个字段」这个偶然事实上」** —— 归属的唯一可靠载体是行级
 * `agent_event.run_id`（`agent_event.run_id` 是**列**，任何通道的行都有）。
 *
 * 故本仪器的口径：
 *   - 缺 `run_id` 且通道 **不在**机器导出的 4 条集合内 ⇒ `violations` ⇒ 红（D2-a）；
 *   - 缺 `run_id` 且通道 **在**集合内 ⇒ 记入 `declared`，归属**不在此处**判定，
 *     由 S-2-3 在**行级**判定（D2-b）；
 *   - 集合本身由冻结件机器导出，冻结件一变就自动变长并被 `0-5` 顶红 ⇒ 强制重新裁定。
 *
 * @param {string[]} frames
 * @returns {{runIds: Set<string>, declared: string[], violations: string[]}}
 */
function collectRunIds(frames) {
  const runIds = new Set();
  const declared = [];
  const violations = [];
  for (const frame of frames) {
    const parsed = parseFrame(frame);
    if (parsed.data === null) {
      violations.push(`帧 ${parsed.seq ?? "?"} 的 data 不是 JSON：${frame.replace(/\n/g, "\\n")}`);
      continue;
    }
    if (Object.hasOwn(parsed.data, "run_id")) {
      runIds.add(parsed.data.run_id);
      continue;
    }
    if (parsed.event !== null && CHANNELS_WITHOUT_RUN_ID.includes(parsed.event)) {
      declared.push(`${parsed.event}#${parsed.seq ?? "?"}`);
      continue;
    }
    violations.push(
      `帧 ${parsed.seq ?? "?"}（event=${parsed.event ?? "?"}）的 data 缺 run_id 键，` +
        `且不属 ${CHANNELS_WITHOUT_RUN_ID.join("/")} 白名单 —— 按 D2 判红`
    );
  }
  return { runIds, declared, violations };
}

/**
 * 把一次"守卫调用"归一成 `{ recognized, conflict }`。
 *
 * `recognized: false` ⇔ 返回值/异常不属于任何已声明形态 ⇒ 调用方必须先断言
 * `recognized === true`。少了这一条，"函数返回了 `undefined`"会被误读成
 * "未冲突" ⇒ **假绿**。
 *
 * @param {unknown} value 返回值或抛出的异常。
 */
function normalizeGuardOutcome(value) {
  if (value === null || value === undefined) {
    return { recognized: false, conflict: false, shape: "undefined" };
  }
  const status = value?.status ?? value?.statusCode;
  if (status === 409 || value?.code === "CONFLICT" || value?.code === "RUN_CONFLICT") {
    return { recognized: true, conflict: true, shape: "409" };
  }
  if (typeof value === "object") {
    for (const key of ["allowed", "ok", "permitted"]) {
      if (typeof value[key] === "boolean") {
        return { recognized: true, conflict: value[key] === false, shape: `${key}=${value[key]}` };
      }
    }
    for (const key of ["conflict", "blocked", "rejected", "exceeded"]) {
      if (typeof value[key] === "boolean") {
        return { recognized: true, conflict: value[key] === true, shape: `${key}=${value[key]}` };
      }
    }
  }
  return { recognized: false, conflict: false, shape: typeof value };
}

/**
 * 调一次守卫并归一。
 *
 * 入参形态按 `fn.length` 判定（`<= 1` ⇒ 单对象；`>= 2` ⇒ 位置入参），
 * 判定结果记进 `shape`，红的时候能看出是按哪种契约调的。
 *
 * @param {Function} fn
 * @param {object} args
 */
async function probeGuard(fn, args) {
  try {
    const raw = fn.length >= 2 ? await fn(args.conversationId, args.origin) : await fn(args);
    return { ...normalizeGuardOutcome(raw), threw: false };
  } catch (error) {
    return { ...normalizeGuardOutcome(error), threw: true };
  }
}

/** 造一条"父 run 在跑"的链（workspace → agent → version → conversation → run）。 */
async function seedRunningChain(fixture, name = "spike-agent") {
  seedWorkspace(fixture);
  const { agentId, versionId } = await createAgentWithVersion(fixture, name);
  const conversationId = await createConversation(fixture, agentId);
  const runId = seedRun(fixture, { agentId, versionId, conversationId, status: "RUNNING" });
  return { agentId, versionId, conversationId, runId };
}

// 顶层一次性解析（不抛错；缺实现只体现在 `found === false`）。
const MODULES = {
  sseStream: await loadModule(DOMAIN.sseStream),
  guardHosts: [await loadModule(DOMAIN.runService), await loadModule(DOMAIN.coordinator)],
  spawner: await loadModule(DOMAIN.spawner),
  delegation: await loadModule(DOMAIN.delegation),
  guard: await loadModule(DOMAIN.guard),
  spawnAgentTool: await loadModule(DOMAIN.spawnAgentTool),
  domainRuntime: await loadModule(DOMAIN.domainRuntime),
  domainSubagent: await loadModule(DOMAIN.domainSubagent),
  domainPackage: await loadModule(DOMAIN.domainPackage),
};

/**
 * 常量宿主：取**第一个真的导出** `RUN_ORIGIN_SUBAGENT` 的候选。
 *
 * 顺序有讲究：裸包名 `@wbtime/domain` 在最前，因为它在真树与注入克隆里**同源**
 * （都经 `apps/api/node_modules` 解析）；两个相对路径候选只在真树里成立。
 * 三个都没有 ⇒ 落到最后一个候选（其 `found === false`）⇒ 断言红。
 */
const RUNTIME_CANDIDATES = [
  MODULES.domainPackage,
  MODULES.domainSubagent,
  MODULES.domainRuntime,
];
const RUNTIME =
  RUNTIME_CANDIDATES.find(
    (entry) => entry.found && entry.module.RUN_ORIGIN_SUBAGENT !== undefined
  ) ?? RUNTIME_CANDIDATES[RUNTIME_CANDIDATES.length - 1];

const GUARD_FN = pickExport(MODULES.guardHosts, ["guardRunCreation", "guard_run_creation"]);
const STREAM_FN = pickExport([MODULES.sseStream], ["streamRunFrames", "stream_run"]);
const SPAWNER = pickExport([MODULES.spawner], ["SubAgentSpawner"]);
const DEPTH_FN = pickExport([MODULES.guard, MODULES.spawner], [
  "assertDepthAllowed",
  "checkDepth",
  "guardDepth",
  "isDepthAllowed",
]);

/**
 * D7 的派生单入口（`delegation.ts::delegateSpawn`）。
 *
 * 为什么 D7 必须走这条链而不是 `SubAgentSpawner.spawn()` / `makeDelegationPort()`：
 * 后两者只**建行 + 写双源**，不启动子 run 的 driver ⇒ 子 run 事件流里没有
 * `agent.started`。而 **D7④ 要求「子 run 首帧 `type == "agent.started"`」**，
 * 只有带 `gateway` 的 `delegateSpawn` 才会经 `RunDriver.start` 真驱动子 run
 * （`delegation.ts` 3b 路径），首帧才是 `agent.started`。用只建行的路径去验 ④
 * 会把判据写成恒假 —— 那是判据缺陷，不是实现缺陷。
 */
const DELEGATE_SPAWN_FN = pickExport([MODULES.delegation], ["delegateSpawn", "delegate_spawn"]);

/** D7 子 run 的驱动脚本：一句话说完即终态（不需要工具调用，D7 只看流形状与双源）。 */
const D7_CHILD_SCRIPT = Object.freeze([{ type: "text_delta", text: "D7：子 run 收到任务并完成" }]);

// ---------------------------------------------------------------------------
// §0 · 仪器自证（先证明"尺子"是准的，再拿它去量实现）
// ---------------------------------------------------------------------------

test("0-1 · 仪器自证：帧解析器能还原 seq / event / data", () => {
  const [frame] = splitFrames('id: 7\nevent: tool.started\ndata: {"run_id":"r-1"}\n\n');
  const parsed = parseFrame(frame);
  assert.equal(parsed.seq, 7);
  assert.equal(parsed.event, "tool.started");
  assert.deepEqual(parsed.data, { run_id: "r-1" });
});

test("0-2 · 仪器自证：缺 run_id 且不在白名单 ⇒ 进 violations（不当无关帧跳过）", () => {
  const body =
    'id: 1\nevent: tool.started\ndata: {"run_id":"parent"}\n\n' +
    'id: 2\nevent: brand.new.channel\ndata: {"foo":1}\n\n';
  const { runIds, violations } = collectRunIds(splitFrames(body));
  assert.deepEqual([...runIds], ["parent"]);
  assert.equal(violations.length, 1, "未知通道缺 run_id 必须判红，不得当作无关帧静默丢掉（D2）");
  assert.match(violations[0], /brand\.new\.channel/);
});

test("0-3 · 仪器自证：白名单 4 条缺 run_id 走 declared，不算违规", () => {
  const body = CHANNELS_WITHOUT_RUN_ID.map(
    (channel, index) => `id: ${index + 1}\nevent: ${channel}\ndata: {"x":1}\n\n`
  ).join("");
  const { declared, violations } = collectRunIds(splitFrames(body));
  assert.deepEqual(violations, []);
  assert.equal(declared.length, 4, "4 条冻结通道结构上无 run_id，显式登记而非静默跳过");
});

test("0-4 · 仪器自证：守卫结果归一化对 undefined 判 unrecognized（防假绿）", () => {
  assert.deepEqual(normalizeGuardOutcome(undefined), {
    recognized: false,
    conflict: false,
    shape: "undefined",
  });
  assert.deepEqual(normalizeGuardOutcome({ allowed: false }), {
    recognized: true,
    conflict: true,
    shape: "allowed=false",
  });
  assert.deepEqual(normalizeGuardOutcome({ conflict: true }), {
    recognized: true,
    conflict: true,
    shape: "conflict=true",
  });
});

// ---------------------------------------------------------------------------
// §1 · S-1 · origin 豁免不破第二个用户 run 的 409（K3 / D8 / D10）
// ---------------------------------------------------------------------------

test("0-5 · 仪器自证：无 run_id 通道集合由**冻结件机器导出**（不手写名单）", () => {
  assert.equal(CHANNELS_DOCUMENT.channels.length, 19, "冻结件必须仍是 19 条通道");
  assert.deepEqual(
    [...CHANNELS_WITHOUT_RUN_ID].sort(),
    ["approval.decided", "approval.requested", "knowledge.indexed", "memory.written"],
    "集合变化 ⇒ 冻结件新增/减少了不带 run_id 的通道 ⇒ D2-a/D2-b 划分须重新裁定（架构裁定 §8.5）。"
    + "这条**故意写成硬断言**：让变化以红的形式露头，而不是静默漂移"
  );
  // 反向：`projected_fields` 与 `payload_keys_in_order` 对「是否含 run_id」必须一致。
  // 两列一旦分叉，说明冻结件出现了「payload 有、帧里没有」的通道 —— 那是 D2-a/D2-b
  // 划分失效的先兆，必须以红的形式露头。
  const diverged = CHANNELS_DOCUMENT.channels.filter(
    (channel) =>
      (channel.projected_fields ?? []).includes("run_id") !==
      (channel.payload_keys_in_order ?? []).includes("run_id")
  );
  assert.deepEqual(
    diverged.map((channel) => channel.channel),
    [],
    "projected_fields 与 payload_keys_in_order 对 run_id 的判定分叉 ⇒ D2-a/D2-b 划分失效"
  );
});

test("S-1-1 · 判据载体：origin/trigger 常量与 guardRunCreation 就位", () => {
  assert.equal(
    RUNTIME.found,
    true,
    `packages/domain/src/runtime/subagent.ts 必须导出 RUN_TRIGGER_SUBAGENT / RUN_ORIGIN_SUBAGENT / MAX_SUBAGENT_DEPTH；` +
      `实测缺失：${RUNTIME_CANDIDATES.map((m) => m.reason || `${m.spec} 无 RUN_ORIGIN_SUBAGENT`).join(" | ")}`
  );
  assert.equal(
    GUARD_FN.found,
    true,
    `run-service.ts / coordinator.ts 必须导出 guardRunCreation（显式 origin 形参）；实测：${GUARD_FN.tried.join(" | ")}`
  );
  assert.equal(typeof GUARD_FN.value, "function", `guardRunCreation 必须是函数，实测 ${typeof GUARD_FN.value}`);
});

test("S-1-2 · 常量取值：trigger='subagent' / origin='SUBAGENT' / max_depth 缺省 1", () => {
  assert.equal(RUNTIME.found, true, `前置：常量未就位（${RUNTIME.reason}）`);
  const runtime = RUNTIME.module;
  assert.equal(runtime.RUN_TRIGGER_SUBAGENT, "subagent", "零 DDL 方案的标记值须与计划 §1② 一致");
  assert.equal(runtime.RUN_ORIGIN_SUBAGENT, "SUBAGENT", "origin 应用层枚举大写，与 trigger 区分");
  assert.equal(
    runtime.MAX_SUBAGENT_DEPTH ?? runtime.DEFAULT_MAX_SUBAGENT_DEPTH,
    1,
    "max_subagent_depth 缺省 1（单层委派，D1）"
  );
});

test("S-1-3 · 父 run 在跑时 origin=SUBAGENT **不** 409，第二个用户 run **仍** 409（双向）", async () => {
  assert.equal(GUARD_FN.found, true, `前置：guardRunCreation 未就位（${GUARD_FN.tried.join(" | ")}）`);
  assert.equal(RUNTIME.found, true, `前置：常量未就位（${RUNTIME.reason}）`);

  const fixture = await makeApp({ username: "spike-s1" });
  try {
    const { conversationId } = await seedRunningChain(fixture);
    const base = {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      conversationId,
    };

    // 正向：子 run 走应用层豁免入口 ⇒ 不冲突。
    const exemption = await probeGuard(GUARD_FN.value, {
      ...base,
      origin: RUNTIME.module.RUN_ORIGIN_SUBAGENT,
      trigger: "subagent",
    });
    assert.equal(exemption.recognized, true, "守卫必须返回/抛出已声明形态的结果，否则无法判定（防假绿）");
    assert.equal(
      exemption.conflict,
      false,
      `origin=SUBAGENT 的子 run 不得被 max_runs_per_conversation 挡下（实测 ${exemption.shape}）`
    );

    // 反向：第二个用户主动 run ⇒ 仍 409（防顺手放宽并发闸）。
    const secondUser = await probeGuard(GUARD_FN.value, {
      ...base,
      origin: "USER",
      trigger: "user",
    });
    assert.equal(secondUser.recognized, true, "守卫必须返回/抛出已声明形态的结果，否则无法判定（防假绿）");
    assert.equal(
      secondUser.conflict,
      true,
      `第二个用户主动 run 必须仍是 409（防顺手放宽 max_runs_per_conversation；实测 ${secondUser.shape}）`
    );
  } finally {
    await fixture.close();
  }
});

test("S-1-4 · 反注入：origin 非 SUBAGENT 时 trigger='subagent' **不得**获得豁免（D10 核心）", async () => {
  assert.equal(GUARD_FN.found, true, `前置：guardRunCreation 未就位（${GUARD_FN.tried.join(" | ")}）`);

  const fixture = await makeApp({ username: "spike-s1-inject" });
  try {
    const { conversationId } = await seedRunningChain(fixture);
    const forged = await probeGuard(GUARD_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      conversationId,
      origin: "USER", // 客户端伪造不了 origin；这是"裸 trigger 判据"唯一的旁路
      trigger: "subagent",
    });
    assert.equal(forged.recognized, true, "守卫必须返回/抛出已声明形态的结果，否则无法判定（防假绿）");
    assert.equal(
      forged.conflict,
      true,
      "豁免判据若写成裸 trigger=='subagent'（不校验 origin）⇒ 本条必红（D10 反例① / K7①）"
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// §2 · S-2 · 流隔离 + 19 帧全等（K4 / D2 / D6）
// ---------------------------------------------------------------------------

test("S-2-1 · 判据载体：stream_run 就位且接受单对象入参", () => {
  assert.equal(
    STREAM_FN.found,
    true,
    `apps/api/src/modules/run/sse-stream.ts 必须导出 streamRunFrames；实测：${STREAM_FN.tried.join(" | ")}`
  );
  assert.equal(typeof STREAM_FN.value, "function", `streamRunFrames 必须是函数，实测 ${typeof STREAM_FN.value}`);
});

/**
 * **D2-a** · 帧数据**带** `run_id` 的 15 条通道（架构裁定 §8.5）。
 *
 * 观察面：下发帧的 `data.run_id` 集合 == `{父 run_id}`，**缺键即红**（D2 原文语义保留）。
 *
 * ✅ 关于「传 `runId` 与不传的输出必须不同」这条**反向**断言（原待办，2026-10-23 销项）：
 *   它原先**写不出来** —— `StreamRunFramesOptions` 里没有 `runId` 形参，归属靠
 *   `routes/runs.ts` 的闭包隐式保证 ⇒ 按裁定移出载体、登记为 **T031-05 待办断言**
 *   （台账 §5 风险表 R-10）。
 *   **T031-05 已把 `runId` 形参落地**（`apps/api/src/modules/run/sse-stream.ts:119`
 *   `readonly runId?: string`，行级过滤在 `selectStreamableRows`），故本条反向断言
 *   **已补回本用例末尾**（见下方「传 `runId` 与不传的输出必须不同」）。
 *   ⚠️ 上面那段「接口还没有 `runId` 形参」的描述已被现状推翻，保留在此仅为**变更留痕**，
 *   不得再作为「断言写不出来」的依据。
 */
test("S-2-2 · D2-a：带 run_id 的 15 条通道，跨 run 行不得汇入父流（缺键即红）", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  const PARENT = "pppppppp-0000-4000-8000-0000000000p1";
  const CHILD = "cccccccc-0000-4000-8000-0000000000c1";
  /** 父 2 帧（seq 1、2）+ 子 2 帧（seq 3、4）：不隔离时 4 帧全下发。 */
  const rows = [
    { run_id: PARENT, seq: 1, type: "agent.thinking", payload: { run_id: PARENT, iteration: 1 } },
    { run_id: PARENT, seq: 2, type: "agent.thinking", payload: { run_id: PARENT, iteration: 2 } },
    { run_id: CHILD, seq: 3, type: "agent.thinking", payload: { run_id: CHILD, iteration: 1 } },
    { run_id: CHILD, seq: 4, type: "agent.thinking", payload: { run_id: CHILD, iteration: 2 } },
  ];

  const emitted = [];
  await STREAM_FN.value({
    readAfter: async () => rows,
    isTerminal: async () => true,
    afterSeq: 0,
    pollIntervalMs: 0,
    maxPolls: 1,
    runId: PARENT,
    write: (frame) => emitted.push(frame.toString()),
  });

  assert.equal(emitted.length, 2, "父 run 只有 2 帧；子 run 的 2 帧必须被归属过滤掉");

  const collected = collectRunIds(emitted);
  assert.deepEqual(collected.violations, [], "不应有任何违规帧（缺 run_id 即红，D2-a）");
  assert.deepEqual([...collected.runIds], [PARENT], "父流的 data.run_id 集合必须全等于 {父 run_id}（D2-a）");

  // ── 反向断言（T031-05 待办销项）：同一组行，**传 `runId` 与不传的输出必须不同** ──
  // 没有这一条，上面对 `emitted`（2 帧）的断言可能被"过滤根本没生效、只是恰好只发 2 帧"
  // 蒙混过去。不传 `runId` ⇒ 归属过滤关闭 ⇒ 4 行全下发（seq 1,2,3,4 连续）。
  const emittedNoFilter = [];
  await STREAM_FN.value({
    readAfter: async () => rows,
    isTerminal: async () => true,
    afterSeq: 0,
    pollIntervalMs: 0,
    maxPolls: 1,
    // 刻意**不传** runId
    write: (frame) => emittedNoFilter.push(frame.toString()),
  });

  assert.equal(
    emittedNoFilter.length,
    4,
    "反向前提：不传 runId ⇒ 归属过滤关闭 ⇒ 4 行全下发（若这里不是 4，说明本用例的行集构造有问题）",
  );
  assert.notDeepEqual(
    emittedNoFilter,
    emitted,
    "传 runId 与不传的输出必须不同 —— 相同说明 runId 形参没被真正消费（归属过滤是摆设）",
  );
  const collectedNoFilter = collectRunIds(emittedNoFilter);
  assert.deepEqual(
    [...collectedNoFilter.runIds].sort(),
    [PARENT, CHILD].sort(),
    "反向：不传 runId ⇒ 子 run 的 run_id 必然出现在流里（这正是 D2 要防的形态）",
  );
});

/**
 * **D2-b 的载体实现** —— 帧数据**不带** `run_id` 的 4 条通道。
 *
 * ✅ **状态登记（2026-10-23，team-lead 最终裁定）**：D2-b 由 P2 待定**升级为必做附加判据**，
 *   架构师已落盘五要素（docs `a066566`，`02-施工/README.md` §8.5）——
 *   正向（4 条按来源行 `agent_event.run_id` 列断言 == 父）+ **反向不可省**（子 run
 *   同通道事件不得出现在父流）+ 白名单机器导出 + 落点 T031-05 单元层；
 *   计数口径照 S3 先例（**不叫 D11、不改「D1–D10 十条」计数**，闭版一并自证）。
 *   **本条就是 D2-b 的载体实现**，不是"超出定稿的额外覆盖"。
 *
 * 保留依据（与裁定同向，计划 §1④ 原文）：
 *   「**父流只含父 run 帧，此为门禁而非实现细节**」+ K4（`yielded_seq` 单全局水位
 *   会让子 run 的 `seq` 污染父流）+ K5b（隔离失守即**静默崩溃**）。
 *   D2 封闭白名单只守帧内容；这 4 条的帧里没有 `run_id`，内容级断言对它们**天然失明**
 *   ⇒ 若行级过滤只对"带 run_id 的通道"生效，D2 照样绿，但子 run 的
 *   `approval.requested` 已经混进父流了。本用例就是堵这个洞。
 *
 * 做法（帧里看不出归属 ⇒ 用可区分的 payload 指纹分辨帧来自哪一行）：
 *   - 观察面：同行不同 `run_id` ⇒ 只有父 run 的行能产出帧；
 *   - **反向**：构造一条**子 run** 的同通道事件 ⇒ 父流不得出现该帧。
 *
 * 落点同 D2-a：必须在 `streamRunFrames` **单元层**（注入 `readAfter` 喂跨 run 行），
 * **不得只在 HTTP 层** —— HTTP 层喂不进跨 run 行（仓储已按 `run_id` 过滤），
 * 在那里断言「去掉归属过滤」这个反例**不会红**。
 */
test("S-2-3 · D2-b：不带 run_id 的 4 条通道，按来源行 agent_event.run_id 判归属（反向）", async () => {
  assert.equal(STREAM_FN.found, true, `前置：streamRunFrames 未就位（${STREAM_FN.tried.join(" | ")}）`);

  const PARENT = "pppppppp-0000-4000-8000-0000000000p1";
  const CHILD = "cccccccc-0000-4000-8000-0000000000c1";
  // `approval.requested` 是 4 条之一：`projected_fields` 无 run_id，`projection` 为 null。
  assert.ok(
    CHANNELS_WITHOUT_RUN_ID.includes("approval.requested"),
    "approval.requested 必须仍是「帧数据不带 run_id」的通道；否则 D2-a/D2-b 划分须重新裁定"
  );

  const rows = [
    {
      run_id: PARENT,
      seq: 1,
      type: "approval.requested",
      payload: { approval_id: "parent-approval", subject_type: "tool", subject_ref: "x", requested_by: "u" },
    },
    {
      run_id: CHILD,
      seq: 2,
      type: "approval.requested",
      payload: { approval_id: "child-approval", subject_type: "tool", subject_ref: "y", requested_by: "u" },
    },
  ];

  const emitted = [];
  await STREAM_FN.value({
    readAfter: async () => rows,
    isTerminal: async () => true,
    afterSeq: 0,
    pollIntervalMs: 0,
    maxPolls: 1,
    runId: PARENT,
    write: (frame) => emitted.push(frame.toString()),
  });

  // 帧里没有 run_id ⇒ 用 payload 指纹分辨帧来自哪一行。
  const approvalIds = emitted.map((frame) => parseFrame(frame).data?.approval_id);
  assert.deepEqual(
    approvalIds,
    ["parent-approval"],
    "D2-b：帧不带 run_id 时，归属由**来源行的 agent_event.run_id 列**决定；"
      + "子 run 的同通道事件不得汇入父流"
  );

  // 反向断言：子 run 那行**不得**产出任何帧（只测"父的在"会被"全都下发"蒙混）。
  assert.equal(
    approvalIds.includes("child-approval"),
    false,
    "D2-b 反向：子 run 的 approval.requested 必须被行级过滤掉"
  );

  // ── 反向断言（T031-05 待办销项）：同一组行，**传 `runId` 与不传的输出必须不同** ──
  // 这 4 条通道帧里没有 `run_id`，唯一能分辨归属的就是来源行的 `agent_event.run_id` 列。
  // 若不传 `runId` 的输出与传了的一样 ⇒ 说明行级过滤根本没被消费（D2-b 形同虚设）。
  const emittedNoFilter = [];
  await STREAM_FN.value({
    readAfter: async () => rows,
    isTerminal: async () => true,
    afterSeq: 0,
    pollIntervalMs: 0,
    maxPolls: 1,
    // 刻意**不传** runId
    write: (frame) => emittedNoFilter.push(frame.toString()),
  });

  const approvalIdsNoFilter = emittedNoFilter.map((frame) => parseFrame(frame).data?.approval_id);
  assert.deepEqual(
    approvalIdsNoFilter,
    ["parent-approval", "child-approval"],
    "反向前提：不传 runId ⇒ 子 run 的同通道帧必然进流（这正是 D2-b 要防的静默崩溃形态）",
  );
  assert.notDeepEqual(
    approvalIdsNoFilter,
    approvalIds,
    "传 runId 与不传的输出必须不同 —— 相同说明 runId 形参没被真正消费，D2-b 恒真",
  );
});

test("S-2-4 · 19 条冻结通道 golden 帧 sha256 与 channels.json 全等（D6）", () => {
  const document = CHANNELS_DOCUMENT;
  assert.equal(document.channels.length, 19, "冻结件必须仍是 19 条通道");
  assert.equal(document.meta.count, 19);
  assert.equal(document.meta.golden_file_count, 19);

  const mismatches = [];
  for (const channel of document.channels) {
    const bytes = readFileSync(join(ROOT, "contracts", "sse", channel.golden));
    const actual = createHash("sha256").update(bytes).digest("hex");
    if (actual !== channel.golden_sha256 || actual !== channel.frame.sha256) {
      mismatches.push(`${channel.channel}: 实测 ${actual} / 登记 ${channel.golden_sha256}`);
    }
  }
  assert.deepEqual(mismatches, [], "19 条 golden 帧字节不得变化（D6）");
});

// ---------------------------------------------------------------------------
// §3 · S-3 · 子 run 深度守卫可拦（D1）
// ---------------------------------------------------------------------------

test("S-3-1 · 判据载体：spawn_agent 工具与 SubAgentSpawner 就位", () => {
  assert.equal(
    SPAWNER.found,
    true,
    `apps/api/src/modules/run/subagent-spawner.ts 必须导出 SubAgentSpawner；实测：${SPAWNER.tried.join(" | ")}`
  );
  assert.equal(
    registeredToolNames().includes("spawn_agent"),
    true,
    `第 6 个内置工具 spawn_agent 必须进可执行注册表；实测 ${registeredToolNames().join(",")}`
  );
  assert.equal(BUILTIN_REGISTRY.has("spawn_agent"), true, "注册表须含 spawn_agent");
  assert.equal(
    BUILTIN_TOOLS.some((spec) => spec.name === "spawn_agent"),
    true,
    "packages/db 的 BUILTIN_TOOLS（input_schema 唯一真源）必须含 spawn_agent —— 单边加会立刻红"
  );
});

test("S-3-2 · 深度守卫：depth=0/max=1 放行，depth=1/max=1 必拒（双向）", () => {
  assert.equal(
    DEPTH_FN.found,
    true,
    `subagent-guard.ts / subagent-spawner.ts 必须导出深度守卫函数；实测：${DEPTH_FN.tried.join(" | ")}`
  );

  const atChild = normalizeGuardOutcome(DEPTH_FN.value({ depth: 1, maxDepth: 1 }));
  assert.equal(atChild.recognized, true, "深度守卫必须返回已声明形态的结果（防假绿）");
  assert.equal(
    atChild.conflict,
    true,
    "max_subagent_depth=1 时子 run 内再派生必须被拒（D1 ④：子 run 行数 == 0）"
  );

  const atRoot = normalizeGuardOutcome(DEPTH_FN.value({ depth: 0, maxDepth: 1 }));
  assert.equal(atRoot.recognized, true, "深度守卫必须返回已声明形态的结果（防假绿）");
  assert.equal(
    atRoot.conflict,
    false,
    "父 run（depth=0）必须仍能派生 —— 只测'拒绝'会被'一律拒绝'的假实现蒙混过关"
  );
});

test("S-3-3 · 拒绝的观察面：tool_call=failed + agent_event(subagent.rejected/DEPTH_EXCEEDED) + 子 run 行数 0", async () => {
  assert.equal(SPAWNER.found, true, `前置：SubAgentSpawner 未就位（${SPAWNER.tried.join(" | ")}）`);

  const fixture = await makeApp({ username: "spike-s3" });
  try {
    const chain = await seedRunningChain(fixture, "spike-parent");
    const methodNames = ["spawn", "spawnChild", "trySpawn"];
    const surface = SPAWNER.value.prototype ?? SPAWNER.value;
    const methodName = methodNames.find((name) => typeof surface[name] === "function");
    assert.ok(
      methodName !== undefined,
      `SubAgentSpawner 必须具 ${methodNames.join("/")} 之一；实测键 ${Object.getOwnPropertyNames(surface).join(",")}`
    );

    const spawner = new SPAWNER.value({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      maxDepth: 1,
    });
    await spawner[methodName]({
      parentRunId: chain.runId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "子任务（depth=1，必须被拒）",
      depth: 1,
      maxDepth: 1,
    });

    const raw = fixture.raw;

    // 观察面 ④：`agent_run` 中 trigger == "subagent" 的行数 == 0。
    assert.equal(
      raw.prepare("select count(*) as n from agent_run where trigger = 'subagent'").get().n,
      0,
      "深度超限 ⇒ 一个子 run 都不许落库（D1 ④）"
    );

    // 观察面 ②：`agent_event` 有 subagent.rejected 且 payload.reason == DEPTH_EXCEEDED。
    const rejected = raw
      .prepare("select payload from agent_event where type = 'subagent.rejected'")
      .all();
    assert.equal(
      rejected.length >= 1,
      true,
      "agent_event 必须落一条 subagent.rejected（只记日志不落库 ⇒ 本条红，D7 反例）"
    );
    const reasons = rejected.map((row) => JSON.parse(row.payload ?? "{}").reason);
    assert.ok(
      reasons.includes("DEPTH_EXCEEDED"),
      `subagent.rejected 的 payload.reason 必须是 DEPTH_EXCEEDED；实测 ${JSON.stringify(reasons)}`
    );

    // 观察面 ①：父 run 内该次 tool_call.status == "FAILED"（**非 HTTP**）。
    //
    // ⚠️ 词表取值必须用**冻结大写** `FAILED`，不能用计划 D1 ① 原文的小写 "failed"：
    //   `tool_call.status` 的值域是冻结词表 `TOOL_CALL_STATUSES`
    //   （`packages/domain/src/runtime/tool-call-state.ts`，与 db 侧逐字同源，
    //   由 `db-domain-constants.test.mjs` P-3 钉死）＝
    //   `PENDING / RUNNING / SUCCESS / FAILED / DENIED / CANCELLED / UNKNOWN`，
    //   且 `tool-call-repo.ts:141` 会**拒绝**词表外的值 —— 小写 "failed" 根本写不进库。
    //   计划 D1 ① 的小写是行文不精确，不是另一套词表（已上报架构，待回写）。
    assert.equal(
      raw
        .prepare(
          "select count(*) as n from tool_call where run_id = ? and tool_name = 'spawn_agent' and status = 'FAILED'"
        )
        .get(chain.runId).n >= 1,
      true,
      "父 run 内这次 spawn_agent 的 tool_call.status 必须是 FAILED（D1 ①：内置工具不产生 4xx；"
        + "取值须用冻结词表 TOOL_CALL_STATUSES 的大写 FAILED，小写 'failed' 不是合法值）"
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// §S-3-4…S-3-7 · D7 委派可回放（**双源一致**）
//
// 判据原文（计划 §3-D7 逐字）：
//   ① 父侧：父 run 的 `tool_call` 行中存在 `tool_name == "spawn_agent"` 且
//      `output.child_run_id` 非空；
//   ② 子侧：子 run 事件流存在 `subagent.started` 且 `payload.parent_run_id == 父 run_id`；
//   ③ **一致性**：①与②读出的 id **互为对方**（**双向集合相等**）；
//   ④ 子 run 事件序列 `seq` **严格单调**、**首帧 `type == "agent.started"`**。
//
// 为什么必须走 `delegateSpawn({gateway})` 而不是 `spawn()` / `makeDelegationPort()`：
//   后两者只建行 + 写双源，**不启动子 run 的 driver** ⇒ 子流首帧是 `subagent.started`，
//   永远拿不到 `agent.started` ⇒ D7④ 会被写成恒假（判据缺陷，不是实现缺陷）。
//   带 `gateway` 的 `delegateSpawn` 走 `RunDriver.start` 真驱动子 run，首帧才是
//   `agent.started`（`delegation.ts` 3b 路径）。故本段统一用真链。
//
// 反例形态（`S-3-R`）：**改的是观察面行、不是源码**。理由两条 ——
//   ⓐ 改源码取红证需要 clone + 重新 build（重工具链），且注入用例集
//     （`scripts/inject_cases.py`）属门禁脚本，按 §9 纪律「scripts/ 改动先报后改」本任务不得擅改；
//   ⓑ D7 的被测对象**本来就是库里的两行**（`tool_call.output.child_run_id` 与
//     `agent_event(subagent.started).payload.parent_run_id`），删/改这两行正是
//     「只写父侧」「只写子侧」「删 subagent.started」「首帧不是 agent.started」的**等价形态**。
//   故用 SQL 制造等价残缺面，断言必须抛错 —— 证明判据非恒真。该局限已如实登记。
// ---------------------------------------------------------------------------

/** 某 run 的 `spawn_agent` 工具调用行（按插入序）。 */
function d7SpawnToolCalls(fixture, runId) {
  return fixture.raw
    .prepare("select * from tool_call where run_id = ? and tool_name = 'spawn_agent' order by rowid asc")
    .all(runId);
}

/** 某 run 的事件流（`seq` 升序；`payload` 已解析）。 */
function d7EventsOf(fixture, runId) {
  return fixture.raw
    .prepare("select type, payload, seq from agent_event where run_id = ? order by seq asc")
    .all(runId)
    .map((row) => ({ type: row.type, payload: JSON.parse(row.payload ?? "{}"), seq: row.seq }));
}

/**
 * 把 D7 的四个观察面一次性读成纯数据（供断言函数与反例共用）。
 *
 * @param {object} fixture `makeApp` 夹具。
 * @param {string} parentRunId 父 run。
 * @param {string} childRunId 子 run。
 * @returns {object} 四类事实。
 */
function d7Facts(fixture, parentRunId, childRunId) {
  const parentChildIds = d7SpawnToolCalls(fixture, parentRunId)
    .map((row) => {
      try {
        const parsed = JSON.parse(row.output ?? "null");
        return parsed !== null && typeof parsed === "object" ? parsed.child_run_id : undefined;
      } catch {
        return undefined;
      }
    })
    .filter((value) => typeof value === "string" && value.length > 0);

  const childEvents = childRunId === "" ? [] : d7EventsOf(fixture, childRunId);
  const started = childEvents.filter((event) => event.type === "subagent.started");
  const childParentIds = started
    .map((event) => event.payload.parent_run_id)
    .filter((value) => typeof value === "string" && value.length > 0);

  return {
    parentRunId,
    childRunId,
    parentChildIds,
    childParentIds,
    childEvents,
    firstEventType: childEvents.length === 0 ? null : childEvents[0].type,
    seqs: childEvents.map((event) => event.seq),
  };
}

/** D7① 父侧：`spawn_agent` 行的 `output.child_run_id` 非空且指向本子 run。 */
function assertD7ParentSide(facts) {
  assert.equal(
    facts.parentChildIds.length >= 1,
    true,
    `D7① 父侧：父 run 的 spawn_agent 行必须带非空 output.child_run_id；实测 ${JSON.stringify(facts.parentChildIds)}`
  );
  assert.equal(
    facts.parentChildIds.includes(facts.childRunId),
    true,
    `D7① 父侧：output.child_run_id 必须指向本次子 run（${facts.childRunId}）；实测 ${JSON.stringify(facts.parentChildIds)}`
  );
}

/** D7② 子侧：子流 `subagent.started.payload.parent_run_id == 父 run_id`。 */
function assertD7ChildSide(facts) {
  assert.equal(
    facts.childParentIds.length >= 1,
    true,
    `D7② 子侧：子 run 事件流必须含 subagent.started 且带非空 payload.parent_run_id；实测 ${JSON.stringify(facts.childParentIds)}`
  );
  assert.equal(
    facts.childParentIds.includes(facts.parentRunId),
    true,
    `D7② 子侧：payload.parent_run_id 必须 == 父 run（${facts.parentRunId}）；实测 ${JSON.stringify(facts.childParentIds)}`
  );
}

/**
 * D7③ **互为对方**（双向集合相等）。
 *
 * 恒真防护：写成「子指向父的唯一值 == 父」「父指向子的唯一值 == 子」，而不是两条
 * 各自独立的"存在性"断言 —— 只写父侧或只写子侧，本条必红。
 */
function assertD7Mutual(facts) {
  assert.deepEqual(
    [...new Set(facts.childParentIds)].sort(),
    [facts.parentRunId].sort(),
    `D7③ 子→父必须唯一且等于父 run（实测 ${JSON.stringify(facts.childParentIds)}）`
  );
  assert.deepEqual(
    [...new Set(facts.parentChildIds)].sort(),
    [facts.childRunId].sort(),
    `D7③ 父→子必须唯一且等于本子 run（实测 ${JSON.stringify(facts.parentChildIds)}）`
  );
}

/** D7④ 子 run 流形状：`seq` 从 1 起步长 1 严格单调；首帧 `agent.started`（**主语 = CHILD**）。 */
function assertD7ChildStream(facts) {
  assert.ok(facts.seqs.length >= 1, "D7④ 子 run 事件流不得为空（主语 = 子 run，不是父 run）");
  assert.deepEqual(
    facts.seqs,
    facts.seqs.map((_, index) => index + 1),
    `D7④ 子 run 的 seq 必须从 1 起、步长 1、严格单调；实测 ${JSON.stringify(facts.seqs)}`
  );
  assert.equal(
    facts.firstEventType,
    "agent.started",
    `D7④ 子 run **首帧必须 agent.started**（实测首帧 ${facts.firstEventType}）—— 首帧是 subagent.started ` +
      "说明子 run 只建行未启动驱动（那是夹具缺陷，不是实现缺陷）"
  );
}

/**
 * 造一套 D7 世界：真 sqlite + 真 `delegateSpawn`（带 fake 网关，子 run 真驱动）。
 *
 * @param {string} username 夹具用户名（隔离用）。
 * @returns {Promise<{fixture: object, parentRunId: string, childRunId: string, outcome: object, facts: object}>}
 */
async function makeD7World(username) {
  const fixture = await makeApp({ username });
  const chain = await seedRunningChain(fixture, "d7-parent");
  const outcome = await DELEGATE_SPAWN_FN.value({
    db: fixture.connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
    parentRunId: chain.runId,
    targetAgentId: chain.agentId,
    targetVersionId: chain.versionId,
    conversationId: chain.conversationId,
    task: "D7：统计昨天的日志条数（只读）",
    depth: 0,
    maxDepth: 1,
    gateway: fakeGateway(D7_CHILD_SCRIPT),
    settleTimeoutMs: 5000,
  });
  const childRunId = typeof outcome?.childRunId === "string" ? outcome.childRunId : "";
  return {
    fixture,
    parentRunId: chain.runId,
    childRunId,
    outcome,
    facts: d7Facts(fixture, chain.runId, childRunId),
  };
}

test("S-3-4 · D7① 父侧还原源：`spawn_agent` 行 output.child_run_id 非空且指向本子 run", async () => {
  assert.equal(
    DELEGATE_SPAWN_FN.found,
    true,
    `前置：delegation.ts 必须导出 delegateSpawn；实测 ${DELEGATE_SPAWN_FN.tried.join(" | ")}`
  );
  const world = await makeD7World("spike-d7-1");
  try {
    assert.equal(
      world.outcome?.accepted,
      true,
      `D7 前提：depth=0 且预算充足 ⇒ 派生必须 accepted；实测 ${JSON.stringify(world.outcome)}`
    );
    assertD7ParentSide(world.facts);
    process.stdout.write(`  [D7①] child_run_id=${world.childRunId} · 父侧取值 ${JSON.stringify(world.facts.parentChildIds)}\n`);
  } finally {
    await world.fixture.close();
  }
});

test("S-3-5 · D7② 子侧还原源：子流 `subagent.started.payload.parent_run_id` == 父 run", async () => {
  assert.equal(DELEGATE_SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${DELEGATE_SPAWN_FN.tried.join(" | ")}）`);
  const world = await makeD7World("spike-d7-2");
  try {
    assert.equal(world.outcome?.accepted, true, `D7 前提：派生必须 accepted；实测 ${JSON.stringify(world.outcome)}`);
    assertD7ChildSide(world.facts);
    process.stdout.write(`  [D7②] 子侧取值 ${JSON.stringify(world.facts.childParentIds)}（父 ${world.parentRunId}）\n`);
  } finally {
    await world.fixture.close();
  }
});

test("S-3-6 · D7③ 双源**互为对方**（双向集合相等；只写单侧必红）", async () => {
  assert.equal(DELEGATE_SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${DELEGATE_SPAWN_FN.tried.join(" | ")}）`);
  const world = await makeD7World("spike-d7-3");
  try {
    assert.equal(world.outcome?.accepted, true, `D7 前提：派生必须 accepted；实测 ${JSON.stringify(world.outcome)}`);
    assertD7Mutual(world.facts);
    process.stdout.write(
      `  [D7③] 父→子 ${JSON.stringify([...new Set(world.facts.parentChildIds)])} ⇄ 子→父 ` +
        `${JSON.stringify([...new Set(world.facts.childParentIds)])}\n`
    );
  } finally {
    await world.fixture.close();
  }
});

test("S-3-7 · D7④ 子 run 流形状（**主语锁 CHILD**）：seq 严格单调 + 首帧 agent.started", async () => {
  assert.equal(DELEGATE_SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${DELEGATE_SPAWN_FN.tried.join(" | ")}）`);
  const world = await makeD7World("spike-d7-4");
  try {
    assert.equal(world.outcome?.accepted, true, `D7 前提：派生必须 accepted；实测 ${JSON.stringify(world.outcome)}`);
    assertD7ChildStream(world.facts);
    process.stdout.write(
      `  [D7④] 子 run seq=${JSON.stringify(world.facts.seqs)} · 首帧=${world.facts.firstEventType}（主语 = 子 run）\n`
    );
  } finally {
    await world.fixture.close();
  }
});

test("S-3-R · D7 反例红证：三种「观察面残缺」等价形态 ⇒ 四条断言必须各自抛错", async () => {
  assert.equal(DELEGATE_SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${DELEGATE_SPAWN_FN.tried.join(" | ")}）`);
  const world = await makeD7World("spike-d7-r");
  const { fixture } = world;
  try {
    assert.equal(world.outcome?.accepted, true, `反例前提：派生必须 accepted；实测 ${JSON.stringify(world.outcome)}`);
    const { parentRunId, childRunId } = world;

    // 基线：四条全绿（先证明这一套事实是"好实现"）。
    assertD7ParentSide(world.facts);
    assertD7ChildSide(world.facts);
    assertD7Mutual(world.facts);
    assertD7ChildStream(world.facts);

    // 反例 a · 删掉子侧 `subagent.started`（等价于「只写父侧」）⇒ ②③ 必红。
    fixture.raw
      .prepare("delete from agent_event where run_id = ? and type = 'subagent.started'")
      .run(childRunId);
    const noChildSide = d7Facts(fixture, parentRunId, childRunId);
    assert.throws(() => assertD7ChildSide(noChildSide), /D7②/, "反例 a：删掉子侧 subagent.started 后 D7② 竟然仍绿（判据恒真）");
    assert.throws(() => assertD7Mutual(noChildSide), /D7③/, "反例 a：删掉子侧后 D7③ 竟然仍绿（判据恒真）");

    // 反例 b · 抹掉父侧 `output.child_run_id`（等价于「只写子侧」）⇒ ①③ 必红。
    fixture.raw
      .prepare("update tool_call set output = null where run_id = ? and tool_name = 'spawn_agent'")
      .run(parentRunId);
    const noParentSide = d7Facts(fixture, parentRunId, childRunId);
    assert.throws(() => assertD7ParentSide(noParentSide), /D7①/, "反例 b：抹掉父侧 child_run_id 后 D7① 竟然仍绿（判据恒真）");
    assert.throws(() => assertD7Mutual(noParentSide), /D7③/, "反例 b：抹掉父侧后 D7③ 竟然仍绿（判据恒真）");

    // 反例 c · 把子流首帧改成非 `agent.started` ⇒ ④ 必红。
    fixture.raw
      .prepare("update agent_event set type = 'agent.thinking' where run_id = ? and seq = (select min(seq) from agent_event where run_id = ?)")
      .run(childRunId, childRunId);
    const badFirstFrame = d7Facts(fixture, parentRunId, childRunId);
    assert.throws(
      () => assertD7ChildStream(badFirstFrame),
      /D7④/,
      "反例 c：子流首帧被改成 agent.thinking 后 D7④ 竟然仍绿（判据恒真）"
    );
    process.stdout.write(
      "  [D7·反例] a 删子侧 subagent.started ⇒ D7②/D7③ 红 · b 抹父侧 child_run_id ⇒ D7①/D7③ 红 · " +
        "c 子流首帧改型 ⇒ D7④ 红（三条均为等价观察面残缺，未改源码）\n"
    );
  } finally {
    await fixture.close();
  }
});
