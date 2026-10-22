/** T3-13 · S2 `context`（上下文拼装后、模型调用前；**按 provenance 逐段判定**）。 */
import type { SafetyStage } from "@wbtime/domain";
import type { Provenance } from "@wbtime/security";
import type { SafetyGate, SafetyVerdict } from "../gate.js";

const STAGE: SafetyStage = "context";
export async function evaluateContext(
  gate: SafetyGate,
  input: { content: string; provenance: Provenance; requestId: string; runId?: string | null }
): Promise<SafetyVerdict> {
  return gate.evaluate({ stage: STAGE, content: input.content, provenance: input.provenance, requestId: input.requestId, ...(input.runId === undefined ? {} : { runId: input.runId }) });
}
