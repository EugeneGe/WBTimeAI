/**
 * `@wbtime/contracts`（V0.1.0）—— 9 个插件扩展点的 **interface 声明**（纯类型，无 loader）。
 *
 * 范围（路线图 §3.1 M-05 **E-3**）
 * -------------------------------
 * - **做**：9 个扩展点的 interface 声明 + 版本常量 + 领域类型名义占位；
 * - **不做**（归 `V0.7.0`）：loader / 签名信任 / 沙箱装载 / Marketplace / 注册与兼容判定。
 *
 * 本包的**唯一 oracle** 是旧线 Protocol 源码（只读归档 `D:/WBT/WBTimeAI_old`），
 * 由 `scripts/check_extension_point_signatures.py` 断言：
 * 9 点逐一「成员名集合全等 + 签名全等」，其中 `audit_sink` 额外与核心侧
 * `packages/audit/src/wbtime_ai_audit/sink.py` 的 `AuditSink` 三面对齐（E-3）。
 */

export type { DomainRef } from "./domain-refs.js";
export type {
  AgentExecutionEvent,
  AgentExecutionHandle,
  AgentExecutionRequest,
  AgentExecutionResult,
  AgentExecutorHealth,
  AuditEvent,
  AuthCredential,
  AuthorizeParams,
  ChatMessage,
  ChatResult,
  ConnectorActionSpec,
  ConnectorHealth,
  ConnectorResult,
  CredentialRef,
  ExtensionContext,
  ModelCapability,
  ModelProvider,
  ModelRef,
  PolicyDecision,
  PolicyExplanation,
  PolicyRequest,
  Principal,
  ProviderConfig,
  RotationResult,
  SinkHealth,
  UISlot,
} from "./domain-refs.js";

export type {
  ExtensionPointApi,
  ExtensionPointName,
  ExtensionPointRegistry,
  ExtensionPointVersion,
  ExtensionPointVersions,
} from "./extension-points/index.js";
export type {
  AgentExecutor,
  AuditSink,
  AuthProvider,
  Connector,
  ModelGateway,
  ModelProviderFactory,
  PolicyEngine,
  SecretProvider,
  UIExtension,
} from "./extension-points/index.js";

export {
  AGENT_EXECUTOR_VERSION,
  AUDIT_SINK_VERSION,
  AUTH_PROVIDER_VERSION,
  CONNECTOR_VERSION,
  MODEL_GATEWAY_VERSION,
  MODEL_PROVIDER_VERSION,
  POLICY_ENGINE_VERSION,
  SECRET_PROVIDER_VERSION,
  UI_EXTENSION_VERSION,
} from "./extension-points/index.js";
