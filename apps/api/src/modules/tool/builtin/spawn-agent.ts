/**
 * V0.3.1 · G031-SPK · 第 6 个内置工具 `spawn_agent`（**最小骨架**）。
 *
 * 职责边界（与 py 线 `spawn_agent` 对齐的"形"，不是 T031-03 的完整"实"）：
 *   - 入参校验（与 `packages/db::BUILTIN_TOOLS` 的 `inputSchema.required` 同源：
 *     `target_agent_id` / `task` 必填非空）；
 *   - 把执行**委托**给 {@link SpawnAgentDelegation}（run 装配侧用 `SubAgentSpawner`
 *     适配的端口）—— 工具本身**不自建执行通道**（计划 §1① 的硬规则）；
 *   - 端口未装配 ⇒ `INTERNAL_ERROR` 拒绝，**不静默降级**（假装成功比失败更糟）。
 *
 * 为什么端口是注入的：`ToolContext` 里没有 run 身份（parentRunId / conversationId /
 * depth），工具层不该自己去查 —— 那些由 run 装配侧在构造 `ToolContext` 时绑定
 * （接线归 T031-03 / T031-04；spike 阶段不装配，故工具对模型可用但一调即拒）。
 */

import { SPAWN_AGENT_TOOL_NAME } from "@wbtime/domain";

import type { BuiltinTool, ToolContext, ToolOutcome } from "../registry.js";
import type { SpawnChildOutcome } from "../../run/subagent-spawner.js";

/** 工具层交给委派端口的入参（工具只认识模型给的东西，run 侧身份由端口绑定补齐）。 */
export interface SpawnAgentPortInput {
  readonly targetAgentId: string;
  readonly task: string;
  /** 预算提示（T031-02 的预算下拨消费；spike 阶段只透传）。 */
  readonly budgetHint?: number;
}

/**
 * 委派端口（`ToolContext.delegation`）。
 *
 * 装配侧的适配形态（T031-03/T031-04 落地）：
 *   `spawn: (input) => spawner.spawn({ parentRunId, conversationId, targetVersionId,
 *   targetAgentId: input.targetAgentId, task: input.task, depth: ctxDepth, ... })`
 */
export interface SpawnAgentDelegation {
  readonly spawn: (input: SpawnAgentPortInput) => Promise<SpawnChildOutcome>;
}

/** 第 6 个内置工具（注册进 `BUILTIN_REGISTRY`；schema 真源在 `packages/db::BUILTIN_TOOLS`）。 */
export const spawnAgentTool: BuiltinTool = {
  name: SPAWN_AGENT_TOOL_NAME,
  requiresSandbox: false,

  async execute(
    args: Readonly<Record<string, unknown>>,
    context: ToolContext
  ): Promise<ToolOutcome> {
    const startedAt = Date.now();

    // 输入校验：与 `BUILTIN_TOOLS` 的 `inputSchema`（required + minLength:1）逐字同源。
    const targetAgentId = args.target_agent_id;
    if (typeof targetAgentId !== "string" || targetAgentId.length === 0) {
      return {
        ok: false,
        error: "target_agent_id 必须是非空字符串",
        errorCode: "VALIDATION_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }
    const task = args.task;
    if (typeof task !== "string" || task.length === 0) {
      return {
        ok: false,
        error: "task 必须是非空字符串",
        errorCode: "VALIDATION_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }
    const budgetHint = args.budget_hint;
    if (budgetHint !== undefined && (typeof budgetHint !== "number" || !Number.isInteger(budgetHint) || budgetHint < 1)) {
      return {
        ok: false,
        error: `budget_hint 必须是正整数（实测 ${JSON.stringify(budgetHint)}）`,
        errorCode: "VALIDATION_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    const delegation = context.delegation;
    if (delegation === undefined) {
      return {
        ok: false,
        error:
          "spawn_agent 需要 ToolContext.delegation（委派端口未装配：接线归 T031-03/T031-04，" +
          "G031-SPK 阶段刻意不装配，工具可被解析但一调即拒）",
        errorCode: "INTERNAL_ERROR",
        durationMs: Date.now() - startedAt,
      };
    }

    // 唯一执行出口 = 委派端口（工具不自建通道；深度/并发/预算闸都在 spawner 里）。
    const outcome = await delegation.spawn({
      targetAgentId,
      task,
      ...(budgetHint === undefined ? {} : { budgetHint }),
    });

    if (outcome.accepted) {
      return {
        ok: true,
        output: { child_run_id: outcome.childRunId },
        durationMs: Date.now() - startedAt,
      };
    }
    return {
      ok: false,
      // 上限类拒绝（深度/并发）走 PERMISSION_DENIED（策略拒绝，非系统故障）；
      // 父不可见是装配/生命周期异常 ⇒ INTERNAL_ERROR。
      errorCode: outcome.reason === "PARENT_NOT_VISIBLE" ? "INTERNAL_ERROR" : "PERMISSION_DENIED",
      error: `spawn_agent 被拒：${outcome.reason}`,
      durationMs: Date.now() - startedAt,
    };
  },
};
