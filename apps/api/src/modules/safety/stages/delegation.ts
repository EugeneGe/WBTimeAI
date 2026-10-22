/** V0.3.1 · T031-02 · S3 `delegation` 挂点（`SafetyStage` 值域 R3-17 预留，本版首装）。 */
import type { SafetyStage } from "@wbtime/domain";
import type { SafetyGate, SafetyVerdict } from "../gate.js";

const STAGE: SafetyStage = "delegation";

/**
 * S3 · 子 Agent 派发挂点：子任务文本 / 白名单 / 深度 / 预算在**派生之前**过闸。
 *
 * 与既有六 stage 同构（`gate.evaluate` 的 stage 写死在本函数，调用点只表达语义 ——
 * 见 `hooks.ts` 的门面设计说明）。拒绝走**拒绝型 tool result**（调用方折算，
 * 不抛异常、不产生 4xx），拒绝事件落 `subagent.rejected` 且 `payload.stage = "delegation"`。
 */
export async function evaluateDelegation(
  gate: SafetyGate,
  input: {
    readonly content: string;
    readonly requestId: string;
    readonly runId?: string | null;
    readonly conversationId?: string | null;
  }
): Promise<SafetyVerdict> {
  return gate.evaluate({
    stage: STAGE,
    content: input.content,
    requestId: input.requestId,
    ...(input.runId === undefined ? {} : { runId: input.runId }),
    ...(input.conversationId === undefined ? {} : { conversationId: input.conversationId }),
  });
}
