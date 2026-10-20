// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.sqlite.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：audit · 表数 1

import { foreignKey, index, integer, numeric, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";
import * as toolNS from "./tool.js";

export const audit_log = sqliteTable("audit_log", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  user_id: text("user_id", { length: 36 }),
  agent_id: text("agent_id", { length: 36 }),
  run_id: text("run_id", { length: 36 }),
  tool_call_id: text("tool_call_id", { length: 36 }),
  action: text("action", { length: 100 }).notNull(),
  resource_type: text("resource_type", { length: 100 }),
  resource_id: text("resource_id", { length: 255 }),
  outcome: text("outcome", { length: 20 }).notNull(),
  duration_ms: integer("duration_ms"),
  token_usage: text("token_usage", { mode: "json" }),
  cost: numeric("cost"),
  request_id: text("request_id", { length: 64 }).notNull(),
  trace_id: text("trace_id", { length: 64 }),
  ip: text("ip", { length: 64 }),
  metadata: text("metadata", { mode: "json" }),
  extensions: text("extensions", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_audit_log_action: index("ix_audit_log_action").on(t.action),
    ix_audit_log_request_id: index("ix_audit_log_request_id").on(t.request_id),
    ix_audit_log_run_id: index("ix_audit_log_run_id").on(t.run_id),
    ix_audit_log_tenant_id: index("ix_audit_log_tenant_id").on(t.tenant_id),
    fk_audit_log_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agentNS.agent.id] }),
    fk_audit_log_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_audit_log_2: foreignKey({ columns: [t.run_id], foreignColumns: [agentNS.agent_run.id] }),
    fk_audit_log_3: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_audit_log_4: foreignKey({ columns: [t.tool_call_id], foreignColumns: [toolNS.tool_call.id] }),
    fk_audit_log_5: foreignKey({ columns: [t.user_id], foreignColumns: [identityNS.user.id] }),
    fk_audit_log_6: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);
