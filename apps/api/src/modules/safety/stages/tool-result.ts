/** T3-13 · S6 `tool_result`（provenance 恒 untrusted；**先检查后截断**由调用方保证顺序）。 */
import type { SafetyStage } from "@wbtime/domain";
import type { SafetyGate, SafetyVerdict } from "../gate.js";

const STAGE: SafetyStage = "tool_result";
export async function evaluateToolResult(
  gate: SafetyGate,
  input: { content: string; requestId: string; runId?: string | null; toolCallId?: string | null }
): Promise<SafetyVerdict> {
  // provenance 恒 untrusted（§7 矩阵：工具/MCP/子 run 的返回一律不可信）
  return gate.evaluate({ stage: STAGE, content: input.content, provenance: "untrusted", requestId: input.requestId, ...(input.runId === undefined ? {} : { runId: input.runId }), ...(input.toolCallId === undefined ? {} : { toolCallId: input.toolCallId }) });
}
