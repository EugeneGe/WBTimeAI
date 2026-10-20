/**
 * 扩展点签名引用的**领域类型名义占位**（Domain type references）。
 *
 * 为什么是占位而不是结构
 * ----------------------
 * 本包（V0.1.0）只交 9 个扩展点的 **interface 声明**：签名比对只用到这些类型的
 * **名字**（`write(event: AuditEvent): void`），不需要它们的字段。真正的结构
 * 归 `@wbtime/domain` / `@wbtime/model`（T1-05 起逐版落地）。这里若手抄字段，
 * 就会造出第二真相源 —— 正是 E-3 要杀的漂移。故只声明**名义标记**：
 *
 * - 每个名字都带**旧线出处**（文件:行），可逐条回溯；
 * - `scripts/check_extension_point_signatures.py` 断言三件事：
 *   ① 9 个 interface 签名里引用到的类型 **必须**在此声明（缺声明 ⇒ 红）；
 *   ② 此处声明的每一个名字 **必须**是旧线扩展点模块从 `wbtime_ai_domain` /
 *      `wbtime_ai_model` 真实 import 的名字（凭空新增 ⇒ 红）；
 *   ③ 两个集合**都不得为空**（空集 ⇒ `INVALID(EMPTY)`，防哑真 K-11）。
 *
 * 迁移路径（已登记为遗留，不是设计决定）
 * --------------------------------------
 * `@wbtime/domain` 落地后，本文件逐行改成 `export type { X } from "@wbtime/domain";`
 * 即可 —— 一行一个类型，语义不变，门禁的「引用集 == 声明集」仍然成立。
 *
 * 🔴 本文件**不含任何运行面**：无 loader / 无注册 / 无签名校验（归 V0.7.0）。
 */

/** 名义标记：编译期只用于阻止结构互替；运行时不存在。**/
export interface DomainRef<Name extends string> {
  readonly __domainType: Name;
}

// -- 上下文 / 主体（wbtime_ai_domain.plugin） ---------------------------------

/** 扩展点调用上下文（8 点统一 `ctx` 形参）。旧线：`wbtime_ai_domain/plugin.py:57`。 */
export interface ExtensionContext extends DomainRef<"ExtensionContext"> {}

/** 已认证主体（`auth_provider.authenticate` 输出）。旧线：`wbtime_ai_domain/plugin.py:76`。 */
export interface Principal extends DomainRef<"Principal"> {}

/** 认证凭证（`auth_provider.authenticate` 输入）。旧线：`wbtime_ai_domain/plugin.py:87`。 */
export interface AuthCredential extends DomainRef<"AuthCredential"> {}

// -- 策略引擎 -----------------------------------------------------------------

/** 策略评估请求（`policy_engine.evaluate` / `explain` 输入）。旧线：`plugin.py:109`。 */
export interface PolicyRequest extends DomainRef<"PolicyRequest"> {}

/** 策略裁决（`policy_engine.evaluate` 输出）。旧线：`plugin.py:119`。 */
export interface PolicyDecision extends DomainRef<"PolicyDecision"> {}

/** 策略裁决解释（`policy_engine.explain` 输出）。旧线：`plugin.py:128`。 */
export interface PolicyExplanation extends DomainRef<"PolicyExplanation"> {}

// -- 审计 ---------------------------------------------------------------------

/**
 * 审计事件（`audit_sink.write` 输入）。
 * 旧线：`AuditEvent = AuditLog` 别名（`plugin.py:140`），实体见 `entities/audit.py:19`。
 */
export interface AuditEvent extends DomainRef<"AuditEvent"> {}

/** 审计落点健康状态（`audit_sink.health` 输出）。旧线：`plugin.py:144`。 */
export interface SinkHealth extends DomainRef<"SinkHealth"> {}

// -- 密钥 / 加密 --------------------------------------------------------------

/** 密钥轮换结果（`secret_provider.rotate` 输出）。旧线：`plugin.py:156`。 */
export interface RotationResult extends DomainRef<"RotationResult"> {}

// -- 模型 ---------------------------------------------------------------------

/** 模型引用（`model_gateway.route` 输出 / 候选）。旧线：`plugin.py:169`。 */
export interface ModelRef extends DomainRef<"ModelRef"> {}

/** Provider 装配配置（`model_provider.create` 输入）。旧线：`plugin.py:177`。 */
export interface ProviderConfig extends DomainRef<"ProviderConfig"> {}

/** Provider 能力枚举（`model_provider.capabilities` 输出元素）。旧线：`plugin.py:186`（StrEnum）。 */
export interface ModelCapability extends DomainRef<"ModelCapability"> {}

/** 聊天消息（`model_gateway.route` 输入）。旧线：`wbtime_ai_model/types.py:14`。 */
export interface ChatMessage extends DomainRef<"ChatMessage"> {}

/** 聊天结果（`model_gateway.on_result` 入参的成功侧）。旧线：`wbtime_ai_model/types.py:31`。 */
export interface ChatResult extends DomainRef<"ChatResult"> {}

/** 模型 Provider（`model_provider.create` 输出）。旧线：`wbtime_ai_model/provider.py:17`（Protocol）。 */
export interface ModelProvider extends DomainRef<"ModelProvider"> {}

// -- 连接器 -------------------------------------------------------------------

/** Connector 动作声明（`connector.actions` 输出元素）。旧线：`plugin.py:201`。 */
export interface ConnectorActionSpec extends DomainRef<"ConnectorActionSpec"> {}

/** 授权参数（`connector.authorize` 输入）。旧线：`plugin.py:211`。 */
export interface AuthorizeParams extends DomainRef<"AuthorizeParams"> {}

/** 凭证引用（`connector.authorize` 输出，**不含明文**）。旧线：`plugin.py:219`。 */
export interface CredentialRef extends DomainRef<"CredentialRef"> {}

/** 动作执行结果（`connector.execute` 输出）。旧线：`plugin.py:226`。 */
export interface ConnectorResult extends DomainRef<"ConnectorResult"> {}

/** Connector 健康状态（`connector.health` 输出）。旧线：`plugin.py:235`。 */
export interface ConnectorHealth extends DomainRef<"ConnectorHealth"> {}

// -- 外部 Agent 执行器 --------------------------------------------------------

/** 执行提交请求（`agent_executor.submit` 输入）。旧线：`plugin.py:247`。 */
export interface AgentExecutionRequest extends DomainRef<"AgentExecutionRequest"> {}

/** 执行句柄（`agent_executor.submit` 输出）。旧线：`plugin.py:272`。 */
export interface AgentExecutionHandle extends DomainRef<"AgentExecutionHandle"> {}

/** 执行事件（`agent_executor.stream_events` 产出）。旧线：`plugin.py:304`。 */
export interface AgentExecutionEvent extends DomainRef<"AgentExecutionEvent"> {}

/** 执行结果快照（`agent_executor.poll` / `cancel` 输出）。旧线：`plugin.py:326`。 */
export interface AgentExecutionResult extends DomainRef<"AgentExecutionResult"> {}

/** 执行器可用性（`agent_executor.health` 输出）。旧线：`plugin.py:351`。 */
export interface AgentExecutorHealth extends DomainRef<"AgentExecutorHealth"> {}

// -- 前端扩展 -----------------------------------------------------------------

/** UI 插槽声明（`ui_extension.slots` 输出元素）。旧线：`plugin.py:363`。 */
export interface UISlot extends DomainRef<"UISlot"> {}
