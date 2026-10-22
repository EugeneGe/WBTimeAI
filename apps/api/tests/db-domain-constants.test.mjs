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
// 依赖方向是 db → domain **没有**这条边，反过来也不该有：db 不 import domain（否则
// 数据层被域层绑死），domain 更不能 import db（域层零 ORM 是铁律 R1）。只有
// `apps/api` 同时依赖两者（`package.json` 的 dependencies 里 `@wbtime/db` 与
// `@wbtime/domain` 都在）—— 所以一致性断言只能落在这一层，且**不制造**新的依赖边。
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
  TOOL_CALL_STATUSES as DB_TOOL_CALL_STATUSES,
} from "@wbtime/db/repositories";
import { RUN_STATUSES, TOOL_CALL_STATUSES as DOMAIN_TOOL_CALL_STATUSES } from "@wbtime/domain";

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
