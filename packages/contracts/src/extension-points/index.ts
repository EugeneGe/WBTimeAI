/**
 * 9 个扩展点统一出口 + **类型级**注册表。
 *
 * 为什么是「类型级」
 * ------------------
 * 旧线 `extension_points/__init__.py:52-63` 的 `SUPPORTED_EXTENSION_POINTS` 是**运行时 dict**，
 * `is_compatible_point()` 是**运行时判定函数**——两者都属**运行面**，按本版禁令
 * （loader / 签名 / 沙箱 / 注册归 V0.7.0）**不在本包声明**。
 *
 * 本文件只提供**类型级**映射（名字 → 版本 → 接口类型），编译期存在、运行时不存在，
 * 因此既不是 loader 也不是注册表实现。V0.7.0 拿到本包后，用它做 ABI 声明即可。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/__init__.py:52-63`（9 点与版本）
 */

import type { AgentExecutor, AGENT_EXECUTOR_VERSION } from "./agent_executor.js";
import type { AuditSink, AUDIT_SINK_VERSION } from "./audit_sink.js";
import type { AuthProvider, AUTH_PROVIDER_VERSION } from "./auth_provider.js";
import type { Connector, CONNECTOR_VERSION } from "./connector.js";
import type { ModelGateway, MODEL_GATEWAY_VERSION } from "./model_gateway.js";
import type { ModelProviderFactory, MODEL_PROVIDER_VERSION } from "./model_provider.js";
import type { PolicyEngine, POLICY_ENGINE_VERSION } from "./policy_engine.js";
import type { SecretProvider, SECRET_PROVIDER_VERSION } from "./secret_provider.js";
import type { UIExtension, UI_EXTENSION_VERSION } from "./ui_extension.js";

// 版本常量是**值**（与旧线 `EXTENSION_POINT_VERSION` 同形），故按值再导出一次，
// 供 V0.7.0 的 loader 侧在需要时读取；它们不含任何行为。
export { AGENT_EXECUTOR_VERSION } from "./agent_executor.js";
export { AUDIT_SINK_VERSION } from "./audit_sink.js";
export { AUTH_PROVIDER_VERSION } from "./auth_provider.js";
export { CONNECTOR_VERSION } from "./connector.js";
export { MODEL_GATEWAY_VERSION } from "./model_gateway.js";
export { MODEL_PROVIDER_VERSION } from "./model_provider.js";
export { POLICY_ENGINE_VERSION } from "./policy_engine.js";
export { SECRET_PROVIDER_VERSION } from "./secret_provider.js";
export { UI_EXTENSION_VERSION } from "./ui_extension.js";

export type { AgentExecutor, AuditSink, AuthProvider, Connector, ModelGateway };
export type { ModelProviderFactory, PolicyEngine, SecretProvider, UIExtension };

/**
 * **类型级**扩展点注册表：名字 → 版本 → 接口类型。
 *
 * 运行时不存在（无对象、无 Map、无函数）——本包 `dist/index.js` 因此只含 9 个字符串常量。
 */
export interface ExtensionPointRegistry {
  readonly auth_provider: {
    readonly version: typeof AUTH_PROVIDER_VERSION;
    readonly api: AuthProvider;
  };
  readonly policy_engine: {
    readonly version: typeof POLICY_ENGINE_VERSION;
    readonly api: PolicyEngine;
  };
  readonly audit_sink: {
    readonly version: typeof AUDIT_SINK_VERSION;
    readonly api: AuditSink;
  };
  readonly secret_provider: {
    readonly version: typeof SECRET_PROVIDER_VERSION;
    readonly api: SecretProvider;
  };
  readonly model_gateway: {
    readonly version: typeof MODEL_GATEWAY_VERSION;
    readonly api: ModelGateway;
  };
  readonly model_provider: {
    readonly version: typeof MODEL_PROVIDER_VERSION;
    readonly api: ModelProviderFactory;
  };
  readonly connector: {
    readonly version: typeof CONNECTOR_VERSION;
    readonly api: Connector;
  };
  readonly ui_extension: {
    readonly version: typeof UI_EXTENSION_VERSION;
    readonly api: UIExtension;
  };
  readonly agent_executor: {
    readonly version: typeof AGENT_EXECUTOR_VERSION;
    readonly api: AgentExecutor;
  };
}

/** 扩展点名字集合（9 个；新增/删除须同步 `ExtensionPointRegistry` 与门禁的注册表）。 */
export type ExtensionPointName = keyof ExtensionPointRegistry;

/** 取某扩展点的版本字面量类型（如 `"audit_sink/v1"`）。 */
export type ExtensionPointVersion<K extends ExtensionPointName> = ExtensionPointRegistry[K]["version"];

/** 取某扩展点的接口类型（如 `AuditSink`）。 */
export type ExtensionPointApi<K extends ExtensionPointName> = ExtensionPointRegistry[K]["api"];

/** 名字 → 版本 的**类型级**映射表（旧线 `SUPPORTED_EXTENSION_POINTS` 的类型面对应物）。 */
export type ExtensionPointVersions = {
  readonly [K in ExtensionPointName]: ExtensionPointVersion<K>;
};
