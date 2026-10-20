/**
 * ExtensionPoint ⑦ `connector`（外部系统连接器）—— interface 声明（纯类型，无 loader）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/connector.py:22`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/connector.py:26-49`（`Connector` Protocol）
 *
 * 🔴 出网一律走 `EgressPolicy`（旧线 §2.18）—— 本契约只声明动作与执行接口，不含策略实现。
 * 🔴 成员名沿用旧线 snake_case；本文件**不含**任何运行面。
 */

import type {
  AuthorizeParams,
  ConnectorActionSpec,
  ConnectorHealth,
  ConnectorResult,
  CredentialRef,
  ExtensionContext,
} from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const CONNECTOR_VERSION = "connector/v1";

/** 外部系统 Connector 扩展点。 */
export interface Connector {
  /** Connector 唯一标识。 */
  id(): string;
  /** 声明可执行动作清单。 */
  actions(): ConnectorActionSpec[];
  /** 授权并返回凭证引用（**不含明文**）。 */
  authorize(params: AuthorizeParams, ctx: ExtensionContext): CredentialRef;
  /** 执行动作（出网须过 `EgressPolicy`）。 */
  execute(action: string, params: Record<string, unknown>, ctx: ExtensionContext): ConnectorResult;
  /** 报告 Connector 健康状态。 */
  health(): ConnectorHealth;
}
