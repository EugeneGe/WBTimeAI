// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.pg.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：agent · 表数 7

import { boolean, foreignKey, index, integer, jsonb, numeric, pgTable, text, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import * as conversationNS from "./conversation.js";
import * as identityNS from "./identity.js";
import * as knowledgeNS from "./knowledge.js";
import * as skillNS from "./skill.js";
import * as taskNS from "./task.js";
import * as toolNS from "./tool.js";

export const agent = pgTable("agent", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  name: varchar("name", { length: 255 }).notNull(),
  description: text("description"),
  type: varchar("type", { length: 50 }).notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  current_version_id: uuid("current_version_id"),
  created_by: uuid("created_by").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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

export const agent_version = pgTable("agent_version", {
  id: uuid("id").notNull().primaryKey(),
  agent_id: uuid("agent_id").notNull(),
  version: varchar("version", { length: 50 }).notNull(),
  system_prompt: text("system_prompt").notNull(),
  model_config: jsonb("model_config").notNull(),
  runtime_config: jsonb("runtime_config").notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  created_by: uuid("created_by").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_agent_version_agent_id: index("ix_agent_version_agent_id").on(t.agent_id),
    ix_agent_version_created_by: index("ix_agent_version_created_by").on(t.created_by),
    fk_agent_version_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agent.id] }),
    fk_agent_version_1: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
  })
);

export const agent_event = pgTable("agent_event", {
  id: uuid("id").notNull().primaryKey(),
  run_id: uuid("run_id").notNull(),
  seq: integer("seq").notNull(),
  type: varchar("type", { length: 100 }).notNull(),
  payload: jsonb("payload"),
  trace_id: varchar("trace_id", { length: 64 }),
  span_id: varchar("span_id", { length: 64 }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_agent_event_run_id: index("ix_agent_event_run_id").on(t.run_id),
    ix_agent_event_seq: index("ix_agent_event_seq").on(t.seq),
    fk_agent_event_0: foreignKey({ columns: [t.run_id], foreignColumns: [agent_run.id] }),
  })
);

export const agent_run = pgTable("agent_run", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  agent_id: uuid("agent_id").notNull(),
  agent_version_id: uuid("agent_version_id").notNull(),
  conversation_id: uuid("conversation_id").notNull(),
  user_id: uuid("user_id"),
  task_id: uuid("task_id"),
  trigger: varchar("trigger", { length: 50 }).notNull(),
  run_mode: varchar("run_mode", { length: 20 }).notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  trace_id: varchar("trace_id", { length: 64 }),
  span_id: varchar("span_id", { length: 64 }),
  last_heartbeat_at: timestamp("last_heartbeat_at", { withTimezone: true }),
  idempotency_key: varchar("idempotency_key", { length: 255 }),
  started_at: timestamp("started_at", { withTimezone: true }),
  completed_at: timestamp("completed_at", { withTimezone: true }),
  duration_ms: integer("duration_ms"),
  token_usage: jsonb("token_usage"),
  success: boolean("success"),
  error_type: varchar("error_type", { length: 100 }),
  tool_error_count: integer("tool_error_count").notNull(),
  cost: numeric("cost", { precision: 18, scale: 6 }),
  cost_currency: varchar("cost_currency", { length: 10 }),
  cost_price_version: varchar("cost_price_version", { length: 50 }),
  cost_estimated: boolean("cost_estimated").notNull(),
  cost_breakdown: jsonb("cost_breakdown"),
  cost_status: varchar("cost_status", { length: 20 }).notNull(),
  error: text("error"),
  stop_reason: varchar("stop_reason", { length: 50 }),
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

export const agent_skill = pgTable("agent_skill", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  agent_version_id: uuid("agent_version_id").notNull(),
  skill_id: uuid("skill_id").notNull(),
  enabled: boolean("enabled").notNull(),
  config: jsonb("config"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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

export const agent_tool = pgTable("agent_tool", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  agent_version_id: uuid("agent_version_id").notNull(),
  tool_id: uuid("tool_id").notNull(),
  enabled: boolean("enabled").notNull(),
  permission_scope: jsonb("permission_scope"),
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

export const agent_knowledge = pgTable("agent_knowledge", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  agent_version_id: uuid("agent_version_id").notNull(),
  knowledge_base_id: uuid("knowledge_base_id").notNull(),
  enabled: boolean("enabled").notNull(),
  config: jsonb("config"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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
