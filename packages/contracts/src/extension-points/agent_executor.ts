/**
 * ExtensionPoint ⑨ `agent_executor`（外部 Agent 执行器 / CLI Adapter）—— interface 声明（纯类型）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/agent_executor.py:42`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/agent_executor.py:46-83`（`AgentExecutor` Protocol）
 *
 * 生命周期（核心侧调用序，冻结）：`submit` →（`stream_events` 增量消费 | `poll` 轮询）
 * → 终态 `poll`；任意进行中阶段可 `cancel`。`cancel` 对已终态执行**幂等**（返回当前快照）。
 *
 * 🔴 三条硬边界（本契约只声明接口，不实现策略）：
 *   1. **沙箱**：`submit` 必然拉起外部子进程，`workspace_path` 须落在 Sandbox 授权范围内；
 *   2. **出网**：外部 CLI 的任何出网须走 `EgressPolicy`；
 *   3. **凭据**：`metadata` / 事件载荷**不得含明文凭证**（C-07）。
 * 🔴 成员名沿用旧线 snake_case；本文件**不含**任何运行面。
 */

import type {
  AgentExecutionEvent,
  AgentExecutionHandle,
  AgentExecutionRequest,
  AgentExecutionResult,
  AgentExecutorHealth,
  ExtensionContext,
} from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const AGENT_EXECUTOR_VERSION = "agent_executor/v1";

/** 外部 Agent 执行器扩展点（核心 Runtime ↔ 外部 CLI Adapter 的**唯一**契约）。 */
export interface AgentExecutor {
  /** 执行器唯一标识（如 `codex` / `claude-code`）。 */
  id(): string;
  /** 是否承接给定外部 Agent 标识（用于多 Adapter 共存时选路）。 */
  supports(agent_ref: string): boolean;
  /** 提交一次执行并立即返回句柄（**不阻塞**至终态）。 */
  submit(request: AgentExecutionRequest, ctx: ExtensionContext): AgentExecutionHandle;
  /** 查询当前状态 / 终态快照（幂等，可任意次调用）。 */
  poll(execution_id: string, ctx: ExtensionContext): AgentExecutionResult;
  /** 请求取消，返回取消后的快照；对已终态执行幂等。 */
  cancel(execution_id: string, ctx: ExtensionContext): AgentExecutionResult;
  /** 增量产出执行事件（`sequence` 单调递增，从 0 起）。旧线 `Iterator[...]` ⇒ TS `IterableIterator[...]`。 */
  stream_events(execution_id: string, ctx: ExtensionContext): IterableIterator<AgentExecutionEvent>;
  /** 报告执行器可用性（外部 CLI 是否安装 / 版本是否兼容）。 */
  health(): AgentExecutorHealth;
}
