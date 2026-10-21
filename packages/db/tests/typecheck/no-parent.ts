/**
 * T3-03 夹具 · **必须编译失败**（R3-22 影响判据 ③：子表仓储不暴露无父参的查询）。
 *
 * 与 `naked-id.ts` 同一个套路：这个文件是**反例**不是示例。它故意
 *   ① 用裸 `string` 当父引用去构造 `AgentEventRepo`；
 *   ② 少传父引用（`new AgentEventRepo(db, scope)`）。
 * 两条都必须在**类型层**过不去 —— 子表（`agent_event` / `tool_call` / `message`）
 * 没有 `tenant_id`，租户归属**全靠父引用的 scope**；一旦允许裸 id 或省略父引用，
 * "按 run 查事件"就会退化成"按 id 查任意租户的事件"。
 *
 * 判据（`run.mjs` 执行并断言）：
 *   * `tsc --noEmit -p tests/typecheck/tsconfig.no-parent.json` 的 **exit code != 0**；
 *   * 输出必须点名 `no-parent.ts` 且提到 `ScopedRef`（错在**父引用的品牌**上）；
 *   * `error TS` 恰好 **2** 条（一条裸 id、一条缺参；多一条说明判据被别的问题污染）。
 *
 * 若哪天这里能编译通过，说明 R3-22 的父引用强制被削弱（例如给父 ref 加了
 * `string` 重载，或给了默认值）—— 那时本夹具会红，而红得正确。
 */

import { AgentEventRepo, Scope } from "../../src/repositories/index.js";
import type { DrizzleDatabase } from "../../src/repositories/index.js";

// 只为了构造一个真实类型的仓储实例；`undefined` 转型不会引入额外诊断。
const db = undefined as unknown as DrizzleDatabase;
const scope = new Scope("tenant-a");

/** 反例一：裸 id 当父引用。 */
export function violatesBareParentId(): void {
  // 本文件**不出现**任何抑制指令（ts-ignore / ts-expect-error）：一旦抑制，
  // 判据就变成"自证清白"——反例会"通过"，而真正该红的错误被藏起来。
  void new AgentEventRepo(db, scope, "aaaa0000-0000-4000-8000-000000000051"); // ← 必须报 TS2345
}

/** 反例二：缺父引用（父是必填形参，无默认值）。 */
export function violatesMissingParent(): void {
  void new AgentEventRepo(db, scope); // ← 必须报 TS2554（参数个数不足）
}

/** 正向对照：父引用由 `Scope#ref()` 产出时可以正常通过（证明报错来自品牌/必填，不是别的）。 */
export function allowedPath(): AgentEventRepo {
  return new AgentEventRepo(db, scope, scope.ref("aaaa0000-0000-4000-8000-000000000051"));
}
