/** T3-13 · S5 `tool_args`（intent 已落盘、Authorize 之前；REDACT 仅限落盘脱敏）。 */
import type { SafetyStage } from "@wbtime/domain";
import type { SafetyGate, SafetyVerdict } from "../gate.js";

const STAGE: SafetyStage = "tool_args";
export async function evaluateToolArgs(
  gate: SafetyGate,
  input: { content: string; requestId: string; runId?: string | null; toolCallId?: string | null }
): Promise<SafetyVerdict> {
  return gate.evaluate({ stage: STAGE, content: input.content, requestId: input.requestId, ...(input.runId === undefined ? {} : { runId: input.runId }), ...(input.toolCallId === undefined ? {} : { toolCallId: input.toolCallId }) });
}
