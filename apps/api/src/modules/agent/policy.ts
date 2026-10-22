/**
 * T3-05 · 策略配置载体（**R3-13 §11-9** 的服务层落点）。
 *
 * harness 只来自 **Agent 版本配置**：`agent_version.runtime_config.harness`
 * （JSONB 开放对象，零契约变更），缺省 `general`；请求级覆盖**本版不存在**
 * （`RunRequest` 只有 4 个字段，没有 harness/strategy 载体 —— 登记为契约缺口，归 1.1）。
 *
 * 三条硬口径（R3-13 裁定 ②③⑤，逐字执行）：
 *   ① 允许白名单 = `["general"]`（`coding` 未实现，不在白名单）；
 *   ② 非法值（**含 `"coding"`**）⇒ 422 `VALIDATION_ERROR` + `data.reason_code =
 *      'harness_unsupported'` —— **绝不静默回落 default**（静默回落 = 对外声称
 *      跑的是 general，实际配置写的是别的；反例 CE-T5-1 钉死这条）；
 *   ③ 路由成功 ⇒ 落 `audit_log` 一行：`action='agent.harness_routed'`、
 *      `resource_type='agent_run'`、`metadata.route_reason`（零 DDL、不新增事件类型）。
 *      ⚠️ T3-05 的 run op **不创建 run**（执行归 T3-08）⇒ 本版 `run_id` /
 *      `resource_id` 恒 `null`；T3-08 承接执行后应把 `<run_id>` 补进这两列
 *      （R3-13 ⑤ 的原意），登记为 T3-08 的接线项。
 *
 * 审计写入的落点说明：`audit_log` 是租户直挂表（有 `tenant_id`），按分层应走
 * `packages/db` 仓储；但 T3-05 文件域**不含** db 新仓（只有 agent-repo 常量对齐），
 * 故写入经 `DrizzleDatabase` 结构端口 + `@wbtime/db/schema` 的双档表对象在本模块完成
 * （apps/api 对 drizzle 的依赖与 `orm-only-in-repositories` 规则的管辖范围见
 * `.dependency-cruiser.cjs`：该规则只辖 `packages/**`）。登记为偏差，T3-08/后续
 * 若把 audit 写入收编成 db 仓储，本模块改为调用该仓储。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import { instantLiteral, type DrizzleDatabase, type SqlDialect } from "@wbtime/db";
// 双档表对象：`@wbtime/db` 的 `./schema` 出口把 PG / SQLite 两棵树并列导出
//（`* as pg` / `* as sqlite`）—— 经 resolveTable 按方言取，避免方言串味。
import { pg as schemaPg, sqlite as schemaSqlite } from "@wbtime/db/schema";

import { authError } from "../auth/errors.js";

/** `audit_log` 的 drizzle 表对象（结构端口用的 `Table` 形状，由方言决定）。 */
const pgAuditLog = schemaPg.audit_log;
const sqliteAuditLog = schemaSqlite.audit_log;

/** R3-13 ②：本版 harness 白名单（**恰一值**；`coding` 未实现）。 */
export const HARNESS_SUPPORTED = ["general"] as const;

/** 缺省 harness（R3-13 ①：`runtime_config.harness` 缺省 `general`）。 */
export const HARNESS_DEFAULT = "general";

/** `data.reason_code`：harness 值不在白名单（含 `coding`）。 */
export const REASON_HARNESS_UNSUPPORTED = "harness_unsupported";

/** `data.reason_code`：run_mode 不是 INLINE（R3-06）。 */
export const REASON_RUN_MODE_UNSUPPORTED = "run_mode_unsupported";

/** `audit_log.action`：harness 路由成功（R3-13 ⑤ 逐字）。 */
export const AUDIT_ACTION_HARNESS_ROUTED = "agent.harness_routed";

/**
 * 从版本 `runtime_config` 里路由 harness。
 *
 * @param runtimeConfig 版本的 `runtime_config`（JSONB 开放对象；行缺列时为 `{}`）。
 * @returns 路由结果：`harness`（恒白名单内）+ `route_reason`（`default` / `configured`）。
 * @throws {HttpException} 422 `VALIDATION_ERROR` + `reason_code='harness_unsupported'`
 *   —— 白名单外的**任何**值（含 `"coding"`），绝不静默回落。
 */
export function routeHarness(runtimeConfig: Record<string, unknown>): {
  readonly harness: string;
  readonly routeReason: string;
} {
  const configured = runtimeConfig.harness;
  if (configured === undefined || configured === null) {
    // 缺省路径：R3-13 ①「缺省 general」—— 这是**约定值**，不是对非法值的兜底。
    return { harness: HARNESS_DEFAULT, routeReason: "default" };
  }
  if (typeof configured !== "string" || !(HARNESS_SUPPORTED as readonly string[]).includes(configured)) {
    // R3-13 ③：不静默回落。message 把实测值带出来（值来自租户自己的配置，非敏感）。
    throw authError(
      ERROR_CODES.VALIDATION_ERROR,
      `runtime_config.harness 不受支持（实测 ${JSON.stringify(configured)}）；本版白名单：${HARNESS_SUPPORTED.join(" | ")}`,
      { reason_code: REASON_HARNESS_UNSUPPORTED, harness: configured, supported: HARNESS_SUPPORTED },
    );
  }
  return { harness: configured, routeReason: "configured" };
}

/**
 * 断言 `run_mode` 是 INLINE（**R3-06**：本版只支持同步内联执行）。
 *
 * @throws {HttpException} 422 `VALIDATION_ERROR` + `reason_code='run_mode_unsupported'`。
 */
export function assertInlineRunMode(runMode: string): void {
  if (runMode !== "INLINE") {
    throw authError(
      ERROR_CODES.VALIDATION_ERROR,
      `run_mode 仅支持 INLINE（实测 ${JSON.stringify(runMode)}）`,
      { reason_code: REASON_RUN_MODE_UNSUPPORTED, run_mode: runMode },
    );
  }
}

/** 写一行 harness 路由审计的入参（见文件头注 ③ 与 T3-08 接线项说明）。 */
export interface HarnessAuditInput {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
  readonly tenantId: string;
  /** 触发用户（可空：系统触发；`audit_log.user_id` 可空）。 */
  readonly userId: string | null;
  readonly agentId: string;
  /**
   * 关联 run id。T3-05 恒 `null`（run op 不创建 run，执行归 T3-08）；T3-08 承接后
   * 必须把真实 run id 传进来（R3-13 ⑤：`resource_id=<run_id>`）。
   */
  readonly runId: string | null;
  /** 路由结果（`routeHarness` 的返回值原样传入）。 */
  readonly routed: { readonly harness: string; readonly routeReason: string };
  /** 本次请求 id（`audit_log.request_id` NOT NULL；取 Fastify `request.id`）。 */
  readonly requestId: string;
  /** 时钟（测试注入；缺省真实时钟）。 */
  readonly now?: Date;
}

/**
 * 落一行 `agent.harness_routed` 审计（R3-13 ⑤）。
 *
 * 写失败**不吞**：审计是可回查性的底线（R3-13 依据 ③），写不进去就该让请求失败，
 * 而不是"路由成功但查无此事"。
 */
export async function writeHarnessAudit(input: HarnessAuditInput): Promise<void> {
  // 双档取表：不用 resolveTable（apps/api 侧的 drizzle Table 泛型与 db 内部推导
  // 不一致会撞 never），直接按方言二选一 —— 两档表对象同名（表名字面量被
  // `schemas-run-v0019` 同款纪律钉住），选错只会在 SQL 层报"表不存在"。
  const table = input.dialect === "sqlite" ? sqliteAuditLog : pgAuditLog;
  const now = instantLiteral(input.dialect, input.now ?? new Date());
  const values: Record<string, unknown> = {
    id: randomUUID(),
    tenant_id: input.tenantId,
    organization_id: null,
    workspace_id: null,
    user_id: input.userId,
    agent_id: input.agentId,
    run_id: input.runId,
    tool_call_id: null,
    action: AUDIT_ACTION_HARNESS_ROUTED,
    resource_type: "agent_run",
    // T3-05：run 未创建 ⇒ 恒 null（R3-13 ⑤ 的 `<run_id>` 由 T3-08 接线补齐）。
    resource_id: input.runId,
    outcome: "success",
    duration_ms: null,
    token_usage: null,
    cost: null,
    request_id: input.requestId,
    trace_id: null,
    ip: null,
    metadata: { route_reason: input.routed.routeReason, harness: input.routed.harness },
    extensions: null,
    // created_at：SQLite 档显式给文本（列有 default，但双档显式更可核）。
    created_at: now,
  };
  // `DrizzleDatabase` 是结构端口（`insert(...args: never[])` ⇒ 返回 unknown）——
  // 与各仓储同款断言：恢复"insert(table)"的**方法调用形状**（保持 `this` 绑定到
  // drizzle 实例，抽出来再调会丢 `session`），只放宽入参/返回的类型。
  const insertable = input.db as unknown as {
    insert(table: unknown): { values(row: Record<string, unknown>): PromiseLike<unknown> };
  };
  await insertable.insert(table).values(values);
}
