/**
 * T3-09 · Harness 策略接口（Harness §4 / §5：**共享内核 · 双策略**）。
 *
 * 这个接口只回答一个问题：**本轮结束后，还要不要再来一轮？**
 *
 * 为什么策略要独立成一个接口
 * ------------------------
 *   `GeneralHarness`（ReAct：模型据观察决定）与 `CodingHarness`（结构化步骤，主动管理）
 *   的**区别只在"下一步做什么"**，循环内核（九步时序、预算、事件、取消）完全共享。
 *   把"要不要继续"抽出来，两种策略就能复用同一个 `AgentLoop` 而不必复制运行时
 *   —— 这正是 Harness §5 的原则「共享 Runtime，独立 Harness 策略」。
 *
 * 策略**不拥有**什么（范围红线的接口化）
 * ----------------------------------
 *   策略不碰 DB、不碰权限、不碰沙箱、不碰预算账本。它只拿到一个**只读视图**
 *   （`HarnessContext`），返回一个**决策**（`HarnessDecision`）。
 *   所以 `general.ts` 里不可能出现"顺手执行了个工具"这种越界 —— 它没有执行器。
 *
 * 本卡只实现 `GeneralHarness`
 * -------------------------
 *   卡面范围红线明确"不实现 `CodingHarness`"。接口留着是为了让 V0.3.0 之后新增策略
 *   不需要改内核 —— 但**接口的存在不等于第二个实现已落地**，别把"接口扩展点"读成
 *   "功能已支持"。
 */

import type { ModelMessage, ModelToolCall, StopReason } from "@wbtime/domain";

import type { StopVerdict } from "../stop-conditions.js";

/** 策略能看到的东西（**只读**；没有执行器、没有 DB、没有账本写口）。 */
export interface HarnessContext {
  /** 当前是第几轮（从 1 开始）。 */
  readonly turn: number;
  /** 本轮模型产出的 assistant 消息（含它请求的工具调用）。 */
  readonly assistant: ModelMessage;
  /** 本轮模型请求的工具调用（可能为空）。 */
  readonly pendingToolCalls: readonly ModelToolCall[];
  /** 停止判定（策略可以用它提前收尾，也可以无视 —— 但它无权推翻 `stop=true`）。 */
  readonly stopVerdict: StopVerdict;
}

/** 策略决策：继续，或停下并给出理由。 */
export type HarnessDecision =
  | { readonly kind: "continue" }
  | {
      readonly kind: "stop";
      /** 契约 11 值之一；必须是**本场景**合法的那个（`model_finish` / `tool_failed` / …）。 */
      readonly stopReason: StopReason;
      /** 该 stop_reason 该配哪个终态（策略给建议，最终由 loop 按 R3-04 矩阵校验）。 */
      readonly terminalStatus: "SUCCEEDED" | "FAILED" | "CANCELLED";
      readonly detail: string;
    };

/** Harness 策略。 */
export interface HarnessStrategy {
  /** 策略名（写进内部事件，便于回放时区分）。 */
  readonly name: string;
  /**
   * 本轮结束后的决策。
   *
   * ⚠️ 实现**不得**读取 `stopVerdict.stop === true` 却返回 `continue`
   * —— `AgentLoop` 会在调用策略之前先用停止判定短路，策略拿到的
   * `stopVerdict.stop` 恒为 `false`（保留该字段只是让策略能读到 `source` 之类的元信息）。
   */
  decide(context: HarnessContext): HarnessDecision;
}
