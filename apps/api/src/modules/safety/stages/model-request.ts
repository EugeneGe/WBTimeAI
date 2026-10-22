/**
 * T3-13 · S4 `model_request`（**只落 DENY 分支**，R3-17 ②：不落语义、不改路由）。
 * 阶段允许动作 = ALLOW/DENY（无 REDACT）⇒ 任何命中都折 DENY。
 */
import type { SafetyStage } from "@wbtime/domain";
import type { SafetyGate, SafetyVerdict } from "../gate.js";

const STAGE: SafetyStage = "model_request";
export async function evaluateModelRequest(
  gate: SafetyGate,
  input: { content: string; requestId: string; runId?: string | null }
): Promise<SafetyVerdict> {
  return gate.evaluate({ stage: STAGE, content: input.content, requestId: input.requestId, ...(input.runId === undefined ? {} : { runId: input.runId }) });
}
