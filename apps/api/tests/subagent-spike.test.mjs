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
 *     → 只下发归属于 `runId` 的帧。
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
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { BUILTIN_TOOLS } from "@wbtime/db";

import { BUILTIN_REGISTRY, registeredToolNames } from "../dist/modules/tool/registry.js";
import { makeApp, ROOT, TENANT_ID } from "./routes-harness.mjs";
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

/** 冻结件里**结构上不带** `run_id` 的 4 条通道（19 项实测，见 {@link collectRunIds}）。 */
const CHANNELS_WITHOUT_RUN_ID = Object.freeze([
  "knowledge.indexed",
  "memory.written",
  "approval.requested",
  "approval.decided",
]);

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
 * ⚠️ 与 D2 原文的一处**必要**口径修正（已上报，见台账「判据假绿风险」第 1 条）：
 * D2 写「若某帧 `data` 中缺 `run_id` 键，判为立即红（不当作"无关帧"跳过）」，
 * 但 19 条冻结通道里有 **4 条结构上就没有 `run_id`** ——
 * `knowledge.indexed` / `memory.written` / `approval.requested` / `approval.decided`
 * （实测 `contracts/sse/channels.json` 的 `payload_keys_in_order`）。逐字执行会让
 * **任何**包含这 4 条的父流恒红，那是**假红**不是判据。
 *
 * 故本仪器取「**显式登记而非静默跳过**」：缺 `run_id` 的帧必须落进 `violations`，
 * 除非其通道**恰在**上面那 4 条白名单里（此时记入 `declared`，白名单本身被钉死）。
 * 新增任何一条不带 `run_id` 的通道 ⇒ 立刻进 `violations` ⇒ 红。
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

test("S-2-2 · 跨 run 行喂给 stream_run ⇒ 下发帧 data.run_id 集合 == {父 run_id}（双向）", async () => {
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
  const shared = {
    readAfter: async () => rows,
    isTerminal: async () => true,
    afterSeq: 0,
    pollIntervalMs: 0,
    maxPolls: 1,
  };

  const scopedFrames = [];
  await STREAM_FN.value({ ...shared, runId: PARENT, write: (frame) => scopedFrames.push(frame.toString()) });

  const unscopedFrames = [];
  await STREAM_FN.value({ ...shared, write: (frame) => unscopedFrames.push(frame.toString()) });

  // 反向断言：传 runId 与不传 runId 的输出**必须不同** —— 相同说明 runId 形参没被消费（假绿）。
  assert.notEqual(
    scopedFrames.length,
    unscopedFrames.length,
    "runId 形参必须被消费：传与不传的下发帧数不得相同（否则是假绿）"
  );
  assert.equal(scopedFrames.length, 2, "父 run 只有 2 帧；子 run 的 2 帧必须被归属过滤掉");

  const collected = collectRunIds(scopedFrames);
  assert.deepEqual(collected.violations, [], "不应有任何违规帧");
  assert.deepEqual([...collected.runIds], [PARENT], "父流的 data.run_id 集合必须全等于 {父 run_id}（D2）");
});

test("S-2-3 · 19 条冻结通道 golden 帧 sha256 与 channels.json 全等（D6）", () => {
  const document = JSON.parse(readFileSync(join(ROOT, "contracts", "sse", "channels.json"), "utf8"));
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

    // 观察面 ①：父 run 内该次 tool_call.status == "failed"（**非 HTTP**）。
    assert.equal(
      raw
        .prepare(
          "select count(*) as n from tool_call where run_id = ? and tool_name = 'spawn_agent' and status = 'failed'"
        )
        .get(chain.runId).n >= 1,
      true,
      "父 run 内这次 spawn_agent 的 tool_call.status 必须是 failed（D1 ①：内置工具不产生 4xx）"
    );
  } finally {
    await fixture.close();
  }
});
