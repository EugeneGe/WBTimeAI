/**
 * ExtensionPoint ② `policy_engine`（全局策略引擎）—— interface 声明（纯类型，无 loader）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/policy_engine.py:16`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/policy_engine.py:20-29`（`PolicyEngine` Protocol）
 *
 * 🔴 与 tool 级 PDP/PEP **不是同一抽象**（旧线 F20）：本点是全局策略引擎挂点。
 * 🔴 本文件**不含**任何运行面：无 loader / 无注册 / 无签名校验（归 V0.7.0）。
 */

import type {
  ExtensionContext,
  PolicyDecision,
  PolicyExplanation,
  PolicyRequest,
} from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const POLICY_ENGINE_VERSION = "policy_engine/v1";

/** 全局策略引擎扩展点。 */
export interface PolicyEngine {
  /** 对请求做出裁决（ALLOW / DENY / APPROVAL）。 */
  evaluate(request: PolicyRequest, ctx: ExtensionContext): PolicyDecision;
  /** 给出裁决的规则级解释（可审计）。 */
  explain(request: PolicyRequest, ctx: ExtensionContext): PolicyExplanation;
}
