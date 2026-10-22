// T3-03 · P-3 —— 数据库层与域层的**状态值域**一致性断言。
//
// 为什么需要这个文件（QA 第三轮 N-3）
// ----------------------------------
// `agent_run.status` / `tool_call.status` 的值域在仓里**存在两份**，且当前逐项一致：
//   · db 侧：`packages/db/src/repositories/agent-run-repo.ts` 的 `AGENT_RUN_STATUSES`、
//     `tool-call-repo.ts` 的 `TOOL_CALL_STATUSES`（写入/校验时用）；
//   · domain 侧：`packages/domain/src/runtime/run-status.ts` 的 `RUN_STATUSES`、
//     `tool-call-state.ts` 的 `TOOL_CALL_STATUSES`（不变量判定时用）。
// 两份都是 `as const` 数组，谁也不知道对方改过 —— domain 单方面增删一个值，
// 数据层不会红，直到运行时才出现"写进去的状态域层判成未知"。
//
// 为什么落在这里（`apps/api/tests/`）而**不是** `packages/db`
// -------------------------------------------------------
// 依赖方向：domain 不能 import db（域层零 ORM 是铁律 R1）；db → domain 这条边在
// V0.3.0 前**不存在**，自 T3-05 起按**裁决 #1（2026-10-22）对 agent 族开放**：
// `agent-repo` 改 import `@wbtime/domain` 的 agent 词表/状态机（删本地复述，db 的
// `package.json` 已带 `@wbtime/domain` workspace 依赖）——**其余族（run / tool_call
// 等）仍禁**，不得以此为口子扩散。只有 `apps/api` 同时依赖两者（`package.json` 的
// dependencies 里 `@wbtime/db` 与 `@wbtime/domain` 都在）—— 所以一致性断言只能落在
// 这一层，且**不制造**新的依赖边（本文件对照的 run/tool_call 族仍取两侧各自真相源）。
//
// 名字不同**不是**笔误：db 侧叫 `AGENT_RUN_STATUSES`（避免与 agent 的其它状态混淆），
// domain 侧叫 `RUN_STATUSES`（域层只有"run"一个概念）。这里用别名映射，不做重命名 ——
// 改任一包的导出名都会波及既有调用方，而本文件的目的正是让**漂移**被看见。
//
// 反例（改哪边都会红，已实测两种）：
//   · 只从 domain 的 `RUN_STATUSES` 删掉 `"CANCELLED"` ⇒ 第 1 条深比较必红；
//   · 只从 db 的 `TOOL_CALL_STATUSES` 删掉 `"UNKNOWN"` ⇒ 第 2 条深比较必红。
// 顺序也必须一致（两侧都是"契约登记顺序"，不是集合）——`deepEqual` 对数组比顺序，
// 刻意不先 `sort()`：顺序漂移同样是漂移（前端渲染下拉、事件枚举都吃这个顺序）。

import assert from "node:assert/strict";
import test from "node:test";

import {
  AGENT_RUN_STATUSES,
  TERMINAL_AGENT_RUN_STATUSES,
  TERMINAL_TOOL_CALL_STATUSES as DB_TERMINAL_TOOL_CALL_STATUSES,
  TOOL_CALL_STATUSES as DB_TOOL_CALL_STATUSES,
  isTerminalAgentRunStatus,
  isTerminalToolCallStatus,
} from "@wbtime/db/repositories";
import {
  RUN_STATUSES,
  SUSPENDED_RUN_STATUSES,
  TERMINAL_RUN_STATUSES,
  TERMINAL_TOOL_CALL_STATUSES as DOMAIN_TERMINAL_TOOL_CALL_STATUSES,
  TOOL_CALL_STATUSES as DOMAIN_TOOL_CALL_STATUSES,
  isTerminalRunStatus,
  isTerminalToolCallStatus as domainIsTerminalToolCallStatus,
} from "@wbtime/domain";

test("P-3 · `agent_run.status` 值域：db `AGENT_RUN_STATUSES` ≡ domain `RUN_STATUSES`（逐项 + 同序）", () => {
  // 先防空档：两侧都必须非空，否则 `deepEqual([], [])` 会绿得毫无意义。
  assert.ok(AGENT_RUN_STATUSES.length > 0, "db AGENT_RUN_STATUSES 不得为空");
  assert.ok(RUN_STATUSES.length > 0, "domain RUN_STATUSES 不得为空");

  assert.deepEqual(
    [...AGENT_RUN_STATUSES],
    [...RUN_STATUSES],
    "agent_run 状态值域漂移：db 侧与 domain 侧必须逐项同序相等（R3-02 的 7 值口径）",
  );
});

test("P-3 · `tool_call.status` 值域：db `TOOL_CALL_STATUSES` ≡ domain `TOOL_CALL_STATUSES`（逐项 + 同序）", () => {
  assert.ok(DB_TOOL_CALL_STATUSES.length > 0, "db TOOL_CALL_STATUSES 不得为空");
  assert.ok(DOMAIN_TOOL_CALL_STATUSES.length > 0, "domain TOOL_CALL_STATUSES 不得为空");

  assert.deepEqual(
    [...DB_TOOL_CALL_STATUSES],
    [...DOMAIN_TOOL_CALL_STATUSES],
    "tool_call 状态值域漂移：db 侧与 domain 侧必须逐项同序相等（R3-03 的 7 值口径）",
  );
});

// ---------------------------------------------------------------------------
// P-3 扩展（QA 本轮挖出的洞 1）：`TERMINAL_*` 两组终态集合同样是**手写双份**，
// 原 P-3 只断了"全量值域"，终态集合一条都没断。
//
//   工具终态  db `tool-call-repo.ts::TERMINAL_TOOL_CALL_STATUSES`
//             domain `tool-call-state.ts::TERMINAL_TOOL_CALL_STATUSES`（同名）
//   运行终态  db `agent-run-repo.ts::TERMINAL_AGENT_RUN_STATUSES`
//             domain `run-status.ts::TERMINAL_RUN_STATUSES`（**名字不同**，不是笔误：
//             db 侧跟 `AGENT_RUN_STATUSES` 对齐前缀，domain 侧只有 run 一个概念）
//
// 只比数组挡不住"集合对了但判定函数写错"（把 includes 手写成 if 分支时漏一条），
// 所以每组另带两类行为断言：
//   ① 判定函数 == **本侧集合**的成员关系（函数 vs 自己那份集合）；
//   ② 判定函数 == **手写的逐项期望表**（下方两张表，7 个状态全覆盖）。
//      这是第三真源：集合与函数"一起"漂移时，deepEqual 与 ① 都会跟着绿，只有 ② 会红。
// ---------------------------------------------------------------------------

/** 手写逐项期望：tool_call 状态 ⇒ 是否终态（7 值全覆盖，顺序无关）。 */
const EXPECTED_TOOL_CALL_TERMINAL = {
  PENDING: false,
  RUNNING: false,
  SUCCESS: true,
  FAILED: true,
  DENIED: true,
  CANCELLED: true,
  UNKNOWN: true,
};

/** 手写逐项期望：agent_run 状态 ⇒ 是否终态（7 值全覆盖，顺序无关）。 */
const EXPECTED_RUN_TERMINAL = {
  QUEUED: false,
  RUNNING: false,
  WAITING_APPROVAL: false,
  WAITING_INPUT: false,
  SUCCEEDED: true,
  FAILED: true,
  CANCELLED: true,
};

test("P-3 · `tool_call` 终态：db ≡ domain（逐项 + 同序）+ 判定函数逐项行为", () => {
  assert.ok(DB_TERMINAL_TOOL_CALL_STATUSES.length > 0, "db 终态集合不得为空");
  assert.ok(DOMAIN_TERMINAL_TOOL_CALL_STATUSES.length > 0, "domain 终态集合不得为空");

  assert.deepEqual(
    [...DB_TERMINAL_TOOL_CALL_STATUSES],
    [...DOMAIN_TERMINAL_TOOL_CALL_STATUSES],
    "tool_call 终态集合漂移：db 与 domain 必须逐项同序相等（R3-03 / Harness §1-2）",
  );

  // 手写期望必须覆盖**全量状态**：漏一个状态在这里就红（防止"两边一起少一个"）
  assert.deepEqual(
    Object.keys(EXPECTED_TOOL_CALL_TERMINAL).sort(),
    [...DB_TOOL_CALL_STATUSES].sort(),
    "手写终态期望表必须覆盖 tool_call 的全部状态",
  );

  for (const status of DB_TOOL_CALL_STATUSES) {
    const want = EXPECTED_TOOL_CALL_TERMINAL[status];
    assert.equal(typeof want, "boolean", `手写期望漏了状态 ${status}`);
    // ② 手写期望（第三真源）
    assert.equal(isTerminalToolCallStatus(status), want, `db isTerminalToolCallStatus(${status})`);
    assert.equal(
      domainIsTerminalToolCallStatus(status),
      want,
      `domain isTerminalToolCallStatus(${status})`,
    );
    // ① 判定函数 == 本侧集合的成员关系（防"函数与自己那份集合不一致"）
    assert.equal(
      isTerminalToolCallStatus(status),
      DB_TERMINAL_TOOL_CALL_STATUSES.includes(status),
      `db 判定函数与 db 终态集合不一致：${status}`,
    );
    assert.equal(
      domainIsTerminalToolCallStatus(status),
      DOMAIN_TERMINAL_TOOL_CALL_STATUSES.includes(status),
      `domain 判定函数与 domain 终态集合不一致：${status}`,
    );
  }

  // 非成员一律 false（防"判定恒真"这种退化实现）
  for (const bogus of ["", "BOGUS", "success", "PENDING "]) {
    assert.equal(isTerminalToolCallStatus(bogus), false, `db 判定(${JSON.stringify(bogus)}) 必须 false`);
    assert.equal(
      domainIsTerminalToolCallStatus(bogus),
      false,
      `domain 判定(${JSON.stringify(bogus)}) 必须 false`,
    );
  }
});

test("P-3 · `agent_run` 终态：db ≡ domain（逐项 + 同序）+ 判定函数逐项行为", () => {
  assert.ok(TERMINAL_AGENT_RUN_STATUSES.length > 0, "db 运行终态集合不得为空");
  assert.ok(TERMINAL_RUN_STATUSES.length > 0, "domain 运行终态集合不得为空");

  assert.deepEqual(
    [...TERMINAL_AGENT_RUN_STATUSES],
    [...TERMINAL_RUN_STATUSES],
    "agent_run 终态集合漂移：db `TERMINAL_AGENT_RUN_STATUSES` 与 domain `TERMINAL_RUN_STATUSES` 必须逐项同序相等",
  );

  assert.deepEqual(
    Object.keys(EXPECTED_RUN_TERMINAL).sort(),
    [...AGENT_RUN_STATUSES].sort(),
    "手写终态期望表必须覆盖 agent_run 的全部状态",
  );

  for (const status of AGENT_RUN_STATUSES) {
    const want = EXPECTED_RUN_TERMINAL[status];
    assert.equal(typeof want, "boolean", `手写期望漏了状态 ${status}`);
    assert.equal(isTerminalAgentRunStatus(status), want, `db isTerminalAgentRunStatus(${status})`);
    assert.equal(isTerminalRunStatus(status), want, `domain isTerminalRunStatus(${status})`);
    assert.equal(
      isTerminalAgentRunStatus(status),
      TERMINAL_AGENT_RUN_STATUSES.includes(status),
      `db 判定函数与 db 终态集合不一致：${status}`,
    );
    assert.equal(
      isTerminalRunStatus(status),
      TERMINAL_RUN_STATUSES.includes(status),
      `domain 判定函数与 domain 终态集合不一致：${status}`,
    );
  }

  for (const bogus of ["", "BOGUS", "SUCCEEDED ", "success"]) {
    assert.equal(
      isTerminalAgentRunStatus(bogus),
      false,
      `db 判定(${JSON.stringify(bogus)}) 必须 false`,
    );
    assert.equal(isTerminalRunStatus(bogus), false, `domain 判定(${JSON.stringify(bogus)}) 必须 false`);
  }
});

test("P-3 · 事实：domain `SUSPENDED_RUN_STATUSES` 在 db 侧**无对应常量**（不属 P-3 管辖）", () => {
  // 已核（`grep -rn "SUSPENDED" packages/db/src` 为空）：db 侧只有"是否终态"这一个判定，
  // 没有暂停态常量、也没有 `isSuspendedRunStatus`。暂停态是域层不变量（R3-07 的墙钟预算），
  // 数据层不需要它 —— 故**不**在 db 侧凭空造一个来对齐（那只会制造假对称）。
  // 这里只断它自身的两条性质，作为"暂停态与终态不相交"的常驻提示。
  assert.ok(SUSPENDED_RUN_STATUSES.length > 0, "暂停态集合不得为空");
  for (const status of SUSPENDED_RUN_STATUSES) {
    assert.ok(RUN_STATUSES.includes(status), `暂停态 ${status} 必须属于 RUN_STATUSES`);
    assert.equal(isTerminalRunStatus(status), false, `暂停态 ${status} 不得被判成终态`);
    assert.equal(EXPECTED_RUN_TERMINAL[status], false, `手写期望里 ${status} 也不是终态`);
  }
});
