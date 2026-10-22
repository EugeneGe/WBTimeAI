/** T3-13 · S1 `input`（run 创建前；§7 矩阵第 1 行）。允许：ALLOW/DENY/REDACT/REQUIRE_APPROVAL。 */
import type { SafetyStage } from "@wbtime/domain";
import type { SafetyGate, SafetyVerdict } from "../gate.js";

const STAGE: SafetyStage = "input";
export async function evaluateInput(
  gate: SafetyGate,
  input: { content: string; requestId: string; runId?: string | null; conversationId?: string | null }
): Promise<SafetyVerdict> {
  return gate.evaluate({ stage: STAGE, content: input.content, requestId: input.requestId, ...(input.runId === undefined ? {} : { runId: input.runId }), ...(input.conversationId === undefined ? {} : { conversationId: input.conversationId }) });
}
