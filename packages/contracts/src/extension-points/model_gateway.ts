/**
 * ExtensionPoint ⑤ `model_gateway`（路由策略）—— interface 声明（纯类型，无 loader）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/model_gateway.py:19`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/model_gateway.py:23-34`（`ModelGateway` Protocol）
 *
 * 在 Router **之上**做策略；与 ⑥ `model_provider` **正交**。
 *
 * 🔴 旧线裁定 §1.3⑤ / F10：请求类型以实测为准取 `ChatMessage`（仓库无 `ChatRequest`）。
 *    失败侧旧线为 `Exception` ⇒ TS `Error`（归一化映射见门禁脚本）。
 * 🔴 本文件**不含**任何运行面。
 */

import type { ChatMessage, ChatResult, ExtensionContext, ModelRef } from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const MODEL_GATEWAY_VERSION = "model_gateway/v1";

/** 模型网关扩展点（在候选之上选路 + 结果回调）。 */
export interface ModelGateway {
  /** 从候选中显式选出一个模型引用。 */
  route(request: ChatMessage, candidates: ModelRef[], ctx: ExtensionContext): ModelRef;
  /** 结果回调（成功或异常），用于观测 / 计数 / 熔断。 */
  on_result(ref: ModelRef, result: ChatResult | Error): void;
}
