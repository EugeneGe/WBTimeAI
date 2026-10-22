// @wbtime/domain · Agent / AgentVersion 状态枚举与状态机（T3-05 · 裁决 #1 落点）。
//
// ⚠️ 取值来源声明（**三方一致**，逐条给证据）：
//   - 冻结契约：`agent.status` / `agent_version.status` / `agent.type` 列均为
//     `VARCHAR(50) NOT NULL`，**无 CHECK 约束、无 PG enum**（DDL 冻结，零 DDL 红线）
//     ⇒ 值域不是契约给出的，取自下方 py 线 oracle；
//   - py 线 oracle：`WBTimeAI_old/packages/domain/src/wbtime_ai_domain/constants.py`
//     `:40-44`（AGENT_TYPE_*）/ `:47-49`（AGENT_STATUS_*）/ `:52-54`（AGENT_VERSION_STATUS_*）；
//   - 契约 default：`AgentResponse.status` default `"DRAFT"`、`AgentVersionResponse.status`
//     default `"PUBLISHED"`、`CreateAgentRequest.type` default `"PRIMARY"`；
//   - 前端 DTO：`apps/web/src/types/phase1.ts:18` `AgentStatus = "DRAFT" | "ACTIVE" | "ARCHIVED"`。
//   ⇒ 若后续版本裁定值域变化，须同步改此处并在施工记录登记。
//
// 状态机（`AGENT_STATUS_TRANSITIONS`，方向 = from → 允许的 to）的证据：
//   - `DRAFT → ACTIVE`：py `agent_service.publish_version` 发布即置
//     `agent.status = AGENT_STATUS_ACTIVE`（`agent_service.py:128`）—— 发布路径实证；
//   - `ARCHIVED → ACTIVE`：同一行 py 代码是**无条件**置 ACTIVE（不判当前状态）⇒
//     归档 agent 再发布即复活 —— 同一行实证；
//   - `DRAFT → ARCHIVED` / `ACTIVE → ARCHIVED`：py `PUT /agents` 直接赋值不校验
//     （`commands/agent.py:91-92`），本层按词表语义收紧为"弃置/下线走归档"
//     （T3-03 §15.5 偏差 #2，T3-05 裁决保留）；
//   - **没有任何迁移指向 `DRAFT`**（py 线不存在"撤回草稿"路径）。
//
// 本文件是**唯一真相源**：`packages/db` 的 `agent-repo.ts` 从这里 import（T3-03 §15.5
// 偏差 #1 的裁决落地：db 侧不再复述）。分层：零 ORM、零 Web（R1）。

import { DOMAIN_ERROR_CODES, DomainError } from "../errors.js";

/** agent 生命周期值域（py constants.py:47-49 顺序，逐项同序）。 */
export const AGENT_STATUSES = ["DRAFT", "ACTIVE", "ARCHIVED"] as const;

export type AgentStatus = (typeof AGENT_STATUSES)[number];

/** agent 生命周期：草稿（创建即此态；契约 `AgentResponse.status` default）。 */
export const AGENT_STATUS_DRAFT: AgentStatus = "DRAFT";
/** agent 生命周期：启用（发布路径实证：py `publish_version` 置 ACTIVE）。 */
export const AGENT_STATUS_ACTIVE: AgentStatus = "ACTIVE";
/** agent 生命周期：归档（弃置/下线；无迁移出自它指向 DRAFT 的路径）。 */
export const AGENT_STATUS_ARCHIVED: AgentStatus = "ARCHIVED";

/** agent 版本状态值域（py constants.py:52-54 顺序，逐项同序）。 */
export const AGENT_VERSION_STATUSES = ["DRAFT", "PUBLISHED", "DEPRECATED"] as const;

export type AgentVersionStatus = (typeof AGENT_VERSION_STATUSES)[number];

/** 版本状态：已发布（契约 `AgentVersionResponse.status` default；发布即冻结）。 */
export const AGENT_VERSION_STATUS_PUBLISHED: AgentVersionStatus = "PUBLISHED";
/** 版本状态：已废弃（py 词表第三值；本版无迁移入口 —— 没有对应端点）。 */
export const AGENT_VERSION_STATUS_DEPRECATED: AgentVersionStatus = "DEPRECATED";
/** 版本状态：草稿（py 词表成员；本版**没有**产生 DRAFT 版本的入口 —— 契约唯一
 * 创建路径 `POST /agents/{id}/publish` 恒产 PUBLISHED）。 */
export const AGENT_VERSION_STATUS_DRAFT: AgentVersionStatus = "DRAFT";

/** agent 类型值域（py constants.py:40-44 顺序，逐项同序）。 */
export const AGENT_TYPES = [
  "PRIMARY",
  "SUB_AGENT",
  "WORKFLOW_AGENT",
  "SCHEDULED_AGENT",
  "EVENT_AGENT",
] as const;

export type AgentType = (typeof AGENT_TYPES)[number];

/** agent 类型：主 Agent（契约 `CreateAgentRequest.type` / `AgentResponse.type` default）。 */
export const AGENT_TYPE_PRIMARY: AgentType = "PRIMARY";

/**
 * agent 状态迁移矩阵（**方向 = from → 允许的 to**；证据见文件头注）。
 *
 * 键集合必须恰好等于 {@link AGENT_STATUSES}（少一个状态 = 矩阵对它沉默）；
 * 值集合 ⊆ {@link AGENT_STATUSES}。CAS 语义见 `packages/db` 的 `AgentRepo.transition`
 * （把矩阵反查成"目标状态的合法来源集合"，一条 `UPDATE ... WHERE status IN (...)` 打出去）。
 */
export const AGENT_STATUS_TRANSITIONS: Readonly<
  Record<AgentStatus, readonly AgentStatus[]>
> = Object.freeze({
  [AGENT_STATUS_DRAFT]: Object.freeze([AGENT_STATUS_ACTIVE, AGENT_STATUS_ARCHIVED] as const),
  [AGENT_STATUS_ACTIVE]: Object.freeze([AGENT_STATUS_ARCHIVED] as const),
  [AGENT_STATUS_ARCHIVED]: Object.freeze([AGENT_STATUS_ACTIVE] as const),
});

/** 是否 agent 生命周期值。 */
export function isAgentStatus(status: string): status is AgentStatus {
  return (AGENT_STATUSES as readonly string[]).includes(status);
}

/** 是否 agent 版本状态值。 */
export function isAgentVersionStatus(status: string): status is AgentVersionStatus {
  return (AGENT_VERSION_STATUSES as readonly string[]).includes(status);
}

/** 是否 agent 类型值。 */
export function isAgentType(type: string): type is AgentType {
  return (AGENT_TYPES as readonly string[]).includes(type);
}

/** `from → to` 是否合法迁移（矩阵查表；from 不在矩阵里 ⇒ false）。 */
export function canAgentTransition(from: string, to: string): boolean {
  return (AGENT_STATUS_TRANSITIONS[from as AgentStatus] ?? []).includes(to as AgentStatus);
}

/** 反查：哪些状态可以迁移到 `to`（CAS 需要"目标状态的合法来源集合"）。 */
export function agentTransitionSources(to: string): readonly AgentStatus[] {
  const froms: AgentStatus[] = [];
  for (const [from, tos] of Object.entries(AGENT_STATUS_TRANSITIONS)) {
    if ((tos as readonly string[]).includes(to)) froms.push(from as AgentStatus);
  }
  return froms;
}

/** 断言 `from → to` 是合法迁移，否则抛 DomainError（VALIDATION_ERROR）。 */
export function assertAgentTransition(from: AgentStatus, to: AgentStatus): void {
  if (!canAgentTransition(from, to)) {
    throw new DomainError(`非法 agent 状态迁移：${from} → ${to}`, DOMAIN_ERROR_CODES.VALIDATION_ERROR, {
      from,
      to,
    });
  }
}
