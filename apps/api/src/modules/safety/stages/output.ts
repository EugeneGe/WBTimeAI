/**
 * T3-13 · S7 `output`（Commit turn 之前 + 流式期分档；§7.2 三档共用终态兜底）。
 *
 * `incident` / `deliveredUnits` 承接 §16 反例 #17（①′）：流式期（S6 已下发片段后）
 * 终态复核命中 ⇒ 审计记 `incident=true` + `delivered_units>0`（谎称"未泄露"必红）。
 */
import type { SafetyStage } from "@wbtime/domain";
import type { SafetyGate, SafetyVerdict } from "../gate.js";

const STAGE: SafetyStage = "output";
export async function evaluateOutput(
  gate: SafetyGate,
  input: {
    content: string;
    requestId: string;
    runId?: string | null;
    conversationId?: string | null;
    incident?: boolean;
    deliveredUnits?: number;
  }
): Promise<SafetyVerdict> {
  return gate.evaluate({
    stage: STAGE,
    content: input.content,
    requestId: input.requestId,
    ...(input.runId === undefined ? {} : { runId: input.runId }),
    ...(input.conversationId === undefined ? {} : { conversationId: input.conversationId }),
    ...(input.incident === undefined ? {} : { incident: input.incident }),
    ...(input.deliveredUnits === undefined ? {} : { deliveredUnits: input.deliveredUnits }),
  });
}
