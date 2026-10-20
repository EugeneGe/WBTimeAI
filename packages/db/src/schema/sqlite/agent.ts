// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.sqlite.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：agent · 表数 7

import { foreignKey, index, integer, numeric, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as conversationNS from "./conversation.js";
import * as identityNS from "./identity.js";
import * as knowledgeNS from "./knowledge.js";
import * as skillNS from "./skill.js";
import * as taskNS from "./task.js";
import * as toolNS from "./tool.js";

export const agent = sqliteTable("agent", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  description: text("description"),
  type: text("type", { length: 50 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  current_version_id: text("current_version_id", { length: 36 }),
  created_by: text("created_by", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_agent_created_by: index("ix_agent_created_by").on(t.created_by),
    ix_agent_current_version_id: index("ix_agent_current_version_id").on(t.current_version_id),
    ix_agent_organization_id: index("ix_agent_organization_id").on(t.organization_id),
    ix_agent_tenant_id: index("ix_agent_tenant_id").on(t.tenant_id),
    ix_agent_workspace_id: index("ix_agent_workspace_id").on(t.workspace_id),
    fk_agent_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_agent_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_agent_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_agent_3: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
    fk_agent_current_version_id: foreignKey({ name: "fk_agent_current_version_id", columns: [t.current_version_id], foreignColumns: [agent_version.id] }),
  })
);

export const agent_version = sqliteTable("agent_version", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  agent_id: text("agent_id", { length: 36 }).notNull(),
  version: text("version", { length: 50 }).notNull(),
  system_prompt: text("system_prompt").notNull(),
  model_config: text("model_config", { mode: "json" }).notNull(),
  runtime_config: text("runtime_config", { mode: "json" }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  created_by: text("created_by", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_agent_version_agent_id: index("ix_agent_version_agent_id").on(t.agent_id),
    ix_agent_version_created_by: index("ix_agent_version_created_by").on(t.created_by),
    fk_agent_version_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agent.id] }),
    fk_agent_version_1: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
  })
);

export const agent_event = sqliteTable("agent_event", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  run_id: text("run_id", { length: 36 }).notNull(),
  seq: integer("seq").notNull(),
  type: text("type", { length: 100 }).notNull(),
  payload: text("payload", { mode: "json" }),
  trace_id: text("trace_id", { length: 64 }),
  span_id: text("span_id", { length: 64 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_agent_event_run_id: index("ix_agent_event_run_id").on(t.run_id),
    ix_agent_event_seq: index("ix_agent_event_seq").on(t.seq),
    fk_agent_event_0: foreignKey({ columns: [t.run_id], foreignColumns: [agent_run.id] }),
  })
);

export const agent_run = sqliteTable("agent_run", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  agent_id: text("agent_id", { length: 36 }).notNull(),
  agent_version_id: text("agent_version_id", { length: 36 }).notNull(),
  conversation_id: text("conversation_id", { length: 36 }).notNull(),
  user_id: text("user_id", { length: 36 }),
  task_id: text("task_id", { length: 36 }),
  trigger: text("trigger", { length: 50 }).notNull(),
  run_mode: text("run_mode", { length: 20 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  trace_id: text("trace_id", { length: 64 }),
  span_id: text("span_id", { length: 64 }),
  last_heartbeat_at: text("last_heartbeat_at"),
  idempotency_key: text("idempotency_key", { length: 255 }),
  started_at: text("started_at"),
  completed_at: text("completed_at"),
  duration_ms: integer("duration_ms"),
  token_usage: text("token_usage", { mode: "json" }),
  success: integer("success", { mode: "boolean" }),
  error_type: text("error_type", { length: 100 }),
  tool_error_count: integer("tool_error_count").notNull(),
  cost: numeric("cost"),
  cost_currency: text("cost_currency", { length: 10 }),
  cost_price_version: text("cost_price_version", { length: 50 }),
  cost_estimated: integer("cost_estimated", { mode: "boolean" }).notNull(),
  cost_breakdown: text("cost_breakdown", { mode: "json" }),
  cost_status: text("cost_status", { length: 20 }).notNull(),
  error: text("error"),
}, (t): ExtraConfig => ({
    ix_agent_run_agent_id: index("ix_agent_run_agent_id").on(t.agent_id),
    ix_agent_run_agent_version_id: index("ix_agent_run_agent_version_id").on(t.agent_version_id),
    ix_agent_run_conversation_id: index("ix_agent_run_conversation_id").on(t.conversation_id),
    ix_agent_run_status: index("ix_agent_run_status").on(t.status),
    ix_agent_run_task_id: index("ix_agent_run_task_id").on(t.task_id),
    ix_agent_run_tenant_id: index("ix_agent_run_tenant_id").on(t.tenant_id),
    ix_agent_run_trace_id: index("ix_agent_run_trace_id").on(t.trace_id),
    ix_agent_run_user_id: index("ix_agent_run_user_id").on(t.user_id),
    uq_agent_run_tenant_idempotency_key: uniqueIndex("uq_agent_run_tenant_idempotency_key").on(t.tenant_id, t.idempotency_key),
    fk_agent_run_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agent.id] }),
    fk_agent_run_1: foreignKey({ columns: [t.agent_version_id], foreignColumns: [agent_version.id] }),
    fk_agent_run_2: foreignKey({ columns: [t.conversation_id], foreignColumns: [conversationNS.conversation.id] }),
    fk_agent_run_3: foreignKey({ columns: [t.task_id], foreignColumns: [taskNS.task.id] }),
    fk_agent_run_4: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_agent_run_5: foreignKey({ columns: [t.user_id], foreignColumns: [identityNS.user.id] }),
  })
);

export const agent_skill = sqliteTable("agent_skill", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  agent_version_id: text("agent_version_id", { length: 36 }).notNull(),
  skill_id: text("skill_id", { length: 36 }).notNull(),
  enabled: integer("enabled", { mode: "boolean" }).notNull(),
  config: text("config", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_agent_skill_agent_version_id: index("ix_agent_skill_agent_version_id").on(t.agent_version_id),
    ix_agent_skill_skill_id: index("ix_agent_skill_skill_id").on(t.skill_id),
    ix_agent_skill_tenant_id: index("ix_agent_skill_tenant_id").on(t.tenant_id),
    uq_agent_skill_version_skill: unique("uq_agent_skill_version_skill").on(t.agent_version_id, t.skill_id),
    fk_agent_skill_0: foreignKey({ columns: [t.agent_version_id], foreignColumns: [agent_version.id] }),
    fk_agent_skill_1: foreignKey({ columns: [t.skill_id], foreignColumns: [skillNS.skill.id] }),
    fk_agent_skill_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
  })
);

export const agent_tool = sqliteTable("agent_tool", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  agent_version_id: text("agent_version_id", { length: 36 }).notNull(),
  tool_id: text("tool_id", { length: 36 }).notNull(),
  enabled: integer("enabled", { mode: "boolean" }).notNull(),
  permission_scope: text("permission_scope", { mode: "json" }),
}, (t): ExtraConfig => ({
    ix_agent_tool_agent_version_id: index("ix_agent_tool_agent_version_id").on(t.agent_version_id),
    ix_agent_tool_tenant_id: index("ix_agent_tool_tenant_id").on(t.tenant_id),
    ix_agent_tool_tool_id: index("ix_agent_tool_tool_id").on(t.tool_id),
    uq_agent_tool_version_tool: unique("uq_agent_tool_version_tool").on(t.agent_version_id, t.tool_id),
    fk_agent_tool_0: foreignKey({ columns: [t.agent_version_id], foreignColumns: [agent_version.id] }),
    fk_agent_tool_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_agent_tool_2: foreignKey({ columns: [t.tool_id], foreignColumns: [toolNS.tool.id] }),
  })
);

export const agent_knowledge = sqliteTable("agent_knowledge", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  agent_version_id: text("agent_version_id", { length: 36 }).notNull(),
  knowledge_base_id: text("knowledge_base_id", { length: 36 }).notNull(),
  enabled: integer("enabled", { mode: "boolean" }).notNull(),
  config: text("config", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_agent_knowledge_agent_version_id: index("ix_agent_knowledge_agent_version_id").on(t.agent_version_id),
    ix_agent_knowledge_knowledge_base_id: index("ix_agent_knowledge_knowledge_base_id").on(t.knowledge_base_id),
    ix_agent_knowledge_tenant_id: index("ix_agent_knowledge_tenant_id").on(t.tenant_id),
    uq_agent_knowledge_version_kb: unique("uq_agent_knowledge_version_kb").on(t.agent_version_id, t.knowledge_base_id),
    fk_agent_knowledge_0: foreignKey({ columns: [t.agent_version_id], foreignColumns: [agent_version.id] }),
    fk_agent_knowledge_1: foreignKey({ columns: [t.knowledge_base_id], foreignColumns: [knowledgeNS.knowledge_base.id] }),
    fk_agent_knowledge_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
  })
);
