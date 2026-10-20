/**
 * ExtensionPoint ⑥ `model_provider`（模型 Provider 注册）—— interface 声明（纯类型，无 loader）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/model_provider.py:19`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/model_provider.py:23-36`（`ModelProviderFactory` Protocol）
 *
 * 与 ⑤ `model_gateway` **正交**：本点**注册 Provider 实现**，⑤ 在 Router 之上做策略。
 *
 * ⚠️ 旧线同文件另有模块级函数 `register_provider_factory(registry, factory, config)`
 *    （`model_provider.py:39-53`）——它把产物注册进 `ModelRegistry`，属**运行面**，
 *    按本版禁令（loader / 注册归 V0.7.0）**不在本文件声明**；其引用的 `ModelRegistry`
 *    也因此不进 `domain-refs.ts`。
 * 🔴 成员名沿用旧线 snake_case；本文件**不含**任何运行面。
 */

import type { ModelCapability, ModelProvider, ProviderConfig } from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const MODEL_PROVIDER_VERSION = "model_provider/v1";

/** 模型 Provider 工厂扩展点。 */
export interface ModelProviderFactory {
  /** Provider 类型标识（如 `openai` / `gateway` / …）。 */
  provider_type(): string;
  /** 按配置创建 `ModelProvider` 实例。 */
  create(config: ProviderConfig): ModelProvider;
  /** 声明该 Provider 支持的能力。 */
  capabilities(): ModelCapability[];
}
