// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.pg.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：audit · 表数 1

import { foreignKey, index, integer, jsonb, numeric, pgTable, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";
import * as toolNS from "./tool.js";

export const audit_log = pgTable("audit_log", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  user_id: uuid("user_id"),
  agent_id: uuid("agent_id"),
  run_id: uuid("run_id"),
  tool_call_id: uuid("tool_call_id"),
  action: varchar("action", { length: 100 }).notNull(),
  resource_type: varchar("resource_type", { length: 100 }),
  resource_id: varchar("resource_id", { length: 255 }),
  outcome: varchar("outcome", { length: 20 }).notNull(),
  duration_ms: integer("duration_ms"),
  token_usage: jsonb("token_usage"),
  cost: numeric("cost", { precision: 18, scale: 6 }),
  request_id: varchar("request_id", { length: 64 }).notNull(),
  trace_id: varchar("trace_id", { length: 64 }),
  ip: varchar("ip", { length: 64 }),
  metadata: jsonb("metadata"),
  extensions: jsonb("extensions"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
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
