// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.pg.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：workflow · 表数 6

import { foreignKey, index, integer, jsonb, pgTable, text, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import * as agentNS from "./agent.js";
import * as conversationNS from "./conversation.js";
import * as identityNS from "./identity.js";
import * as taskNS from "./task.js";
import * as toolNS from "./tool.js";

export const workflow = pgTable("workflow", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  name: varchar("name", { length: 255 }).notNull(),
  description: text("description"),
  status: varchar("status", { length: 50 }).notNull(),
  current_version_id: uuid("current_version_id"),
  created_by: uuid("created_by").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workflow_created_by: index("ix_workflow_created_by").on(t.created_by),
    ix_workflow_current_version_id: index("ix_workflow_current_version_id").on(t.current_version_id),
    ix_workflow_organization_id: index("ix_workflow_organization_id").on(t.organization_id),
    ix_workflow_tenant_id: index("ix_workflow_tenant_id").on(t.tenant_id),
    uq_workflow_tenant_name: unique("uq_workflow_tenant_name").on(t.tenant_id, t.name),
    fk_workflow_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_workflow_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_workflow_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_workflow_3: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
    fk_workflow_current_version_id: foreignKey({ name: "fk_workflow_current_version_id", columns: [t.current_version_id], foreignColumns: [workflow_version.id] }),
  })
);

export const workflow_version = pgTable("workflow_version", {
  id: uuid("id").notNull().primaryKey(),
  workflow_id: uuid("workflow_id").notNull(),
  version: varchar("version", { length: 50 }).notNull(),
  definition: jsonb("definition").notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  created_by: uuid("created_by").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workflow_version_created_by: index("ix_workflow_version_created_by").on(t.created_by),
    ix_workflow_version_workflow_id: index("ix_workflow_version_workflow_id").on(t.workflow_id),
    uq_workflow_version_workflow_version: unique("uq_workflow_version_workflow_version").on(t.workflow_id, t.version),
    fk_workflow_version_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_workflow_version_1: foreignKey({ columns: [t.workflow_id], foreignColumns: [workflow.id] }),
  })
);

export const workflow_node = pgTable("workflow_node", {
  id: uuid("id").notNull().primaryKey(),
  workflow_version_id: uuid("workflow_version_id").notNull(),
  node_key: varchar("node_key", { length: 255 }).notNull(),
  type: varchar("type", { length: 50 }).notNull(),
  config: jsonb("config").notNull(),
  position: jsonb("position").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workflow_node_workflow_version_id: index("ix_workflow_node_workflow_version_id").on(t.workflow_version_id),
    uq_workflow_node_version_node_key: unique("uq_workflow_node_version_node_key").on(t.workflow_version_id, t.node_key),
    fk_workflow_node_0: foreignKey({ columns: [t.workflow_version_id], foreignColumns: [workflow_version.id] }),
  })
);

export const workflow_edge = pgTable("workflow_edge", {
  id: uuid("id").notNull().primaryKey(),
  workflow_version_id: uuid("workflow_version_id").notNull(),
  from_node_key: varchar("from_node_key", { length: 255 }).notNull(),
  to_node_key: varchar("to_node_key", { length: 255 }).notNull(),
  condition: text("condition"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workflow_edge_workflow_version_id: index("ix_workflow_edge_workflow_version_id").on(t.workflow_version_id),
    uq_workflow_edge_version_from_to: unique("uq_workflow_edge_version_from_to").on(t.workflow_version_id, t.from_node_key, t.to_node_key),
    fk_workflow_edge_0: foreignKey({ columns: [t.workflow_version_id], foreignColumns: [workflow_version.id] }),
  })
);

export const workflow_run = pgTable("workflow_run", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  workflow_version_id: uuid("workflow_version_id").notNull(),
  trigger: varchar("trigger", { length: 50 }).notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  task_id: uuid("task_id"),
  input: jsonb("input"),
  output: jsonb("output"),
  started_at: timestamp("started_at", { withTimezone: true }),
  completed_at: timestamp("completed_at", { withTimezone: true }),
  error: text("error"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workflow_run_status: index("ix_workflow_run_status").on(t.status),
    ix_workflow_run_task_id: index("ix_workflow_run_task_id").on(t.task_id),
    ix_workflow_run_tenant_id: index("ix_workflow_run_tenant_id").on(t.tenant_id),
    ix_workflow_run_workflow_version_id: index("ix_workflow_run_workflow_version_id").on(t.workflow_version_id),
    fk_workflow_run_0: foreignKey({ columns: [t.task_id], foreignColumns: [taskNS.task.id] }),
    fk_workflow_run_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_workflow_run_2: foreignKey({ columns: [t.workflow_version_id], foreignColumns: [workflow_version.id] }),
  })
);

export const workflow_node_run = pgTable("workflow_node_run", {
  id: uuid("id").notNull().primaryKey(),
  workflow_run_id: uuid("workflow_run_id").notNull(),
  node_key: varchar("node_key", { length: 255 }).notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  attempt: integer("attempt").notNull(),
  agent_run_id: uuid("agent_run_id"),
  tool_call_id: uuid("tool_call_id"),
  approval_id: uuid("approval_id"),
  input: jsonb("input"),
  output: jsonb("output"),
  started_at: timestamp("started_at", { withTimezone: true }),
  completed_at: timestamp("completed_at", { withTimezone: true }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workflow_node_run_agent_run_id: index("ix_workflow_node_run_agent_run_id").on(t.agent_run_id),
    ix_workflow_node_run_approval_id: index("ix_workflow_node_run_approval_id").on(t.approval_id),
    ix_workflow_node_run_workflow_run_id: index("ix_workflow_node_run_workflow_run_id").on(t.workflow_run_id),
    uq_workflow_node_run_run_key_attempt: unique("uq_workflow_node_run_run_key_attempt").on(t.workflow_run_id, t.node_key, t.attempt),
    fk_workflow_node_run_0: foreignKey({ columns: [t.agent_run_id], foreignColumns: [agentNS.agent_run.id] }),
    fk_workflow_node_run_1: foreignKey({ columns: [t.approval_id], foreignColumns: [conversationNS.approval.id] }),
    fk_workflow_node_run_2: foreignKey({ columns: [t.tool_call_id], foreignColumns: [toolNS.tool_call.id] }),
    fk_workflow_node_run_3: foreignKey({ columns: [t.workflow_run_id], foreignColumns: [workflow_run.id] }),
  })
);
