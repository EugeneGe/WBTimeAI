// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.sqlite.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：tool · 表数 4

import { foreignKey, index, integer, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as agentNS from "./agent.js";
import * as conversationNS from "./conversation.js";
import * as identityNS from "./identity.js";

export const tool = sqliteTable("tool", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }),
  organization_id: text("organization_id", { length: 36 }),
  name: text("name", { length: 100 }).notNull(),
  display_name: text("display_name", { length: 255 }).notNull(),
  description: text("description"),
  category: text("category", { length: 100 }).notNull(),
  source: text("source", { length: 50 }).notNull(),
  input_schema: text("input_schema", { mode: "json" }),
  output_schema: text("output_schema", { mode: "json" }),
  requires_sandbox: integer("requires_sandbox", { mode: "boolean" }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  tool_ref: text("tool_ref", { mode: "json" }),
}, (t): ExtraConfig => ({
    ix_tool_name: index("ix_tool_name").on(t.name),
    ix_tool_organization_id: index("ix_tool_organization_id").on(t.organization_id),
    ix_tool_tenant_id: index("ix_tool_tenant_id").on(t.tenant_id),
    fk_tool_0: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_tool_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
  })
);

export const tool_version = sqliteTable("tool_version", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tool_id: text("tool_id", { length: 36 }).notNull(),
  version: text("version", { length: 50 }).notNull(),
  spec: text("spec", { mode: "json" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_tool_version_tool_id: index("ix_tool_version_tool_id").on(t.tool_id),
    fk_tool_version_0: foreignKey({ columns: [t.tool_id], foreignColumns: [tool.id] }),
  })
);

export const tool_call = sqliteTable("tool_call", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  run_id: text("run_id", { length: 36 }).notNull(),
  tool_id: text("tool_id", { length: 36 }),
  tool_name: text("tool_name", { length: 255 }).notNull(),
  tool_type: text("tool_type", { length: 30 }).notNull(),
  tool_ref: text("tool_ref", { mode: "json" }),
  attempt: integer("attempt").notNull(),
  trace_id: text("trace_id", { length: 64 }),
  span_id: text("span_id", { length: 64 }),
  input: text("input", { mode: "json" }),
  output: text("output", { mode: "json" }),
  status: text("status", { length: 50 }).notNull(),
  duration_ms: integer("duration_ms"),
  sandbox_session_id: text("sandbox_session_id", { length: 36 }),
  error: text("error"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_tool_call_run_id: index("ix_tool_call_run_id").on(t.run_id),
    ix_tool_call_sandbox_session_id: index("ix_tool_call_sandbox_session_id").on(t.sandbox_session_id),
    ix_tool_call_status: index("ix_tool_call_status").on(t.status),
    ix_tool_call_tool_id: index("ix_tool_call_tool_id").on(t.tool_id),
    fk_tool_call_0: foreignKey({ columns: [t.run_id], foreignColumns: [agentNS.agent_run.id] }),
    fk_tool_call_1: foreignKey({ columns: [t.sandbox_session_id], foreignColumns: [conversationNS.sandbox_session.id] }),
    fk_tool_call_2: foreignKey({ columns: [t.tool_id], foreignColumns: [tool.id] }),
  })
);

export const tool_permission = sqliteTable("tool_permission", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  agent_id: text("agent_id", { length: 36 }),
  agent_version_id: text("agent_version_id", { length: 36 }),
  tool_id: text("tool_id", { length: 36 }).notNull(),
  action: text("action", { length: 50 }).notNull(),
  effect: text("effect", { length: 20 }).notNull(),
  scope: text("scope", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_tool_permission_agent_id: index("ix_tool_permission_agent_id").on(t.agent_id),
    ix_tool_permission_agent_version_id: index("ix_tool_permission_agent_version_id").on(t.agent_version_id),
    ix_tool_permission_tenant_id: index("ix_tool_permission_tenant_id").on(t.tenant_id),
    ix_tool_permission_tool_id: index("ix_tool_permission_tool_id").on(t.tool_id),
    uq_tool_permission_agent_tool_action: unique("uq_tool_permission_agent_tool_action").on(t.agent_id, t.tool_id, t.action),
    fk_tool_permission_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agentNS.agent.id] }),
    fk_tool_permission_1: foreignKey({ columns: [t.agent_version_id], foreignColumns: [agentNS.agent_version.id] }),
    fk_tool_permission_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_tool_permission_3: foreignKey({ columns: [t.tool_id], foreignColumns: [tool.id] }),
  })
);
