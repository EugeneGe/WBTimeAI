// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.sqlite.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：workflow · 表数 6

import { foreignKey, index, integer, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as agentNS from "./agent.js";
import * as conversationNS from "./conversation.js";
import * as identityNS from "./identity.js";
import * as taskNS from "./task.js";
import * as toolNS from "./tool.js";

export const workflow = sqliteTable("workflow", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  description: text("description"),
  status: text("status", { length: 50 }).notNull(),
  current_version_id: text("current_version_id", { length: 36 }),
  created_by: text("created_by", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const workflow_version = sqliteTable("workflow_version", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  workflow_id: text("workflow_id", { length: 36 }).notNull(),
  version: text("version", { length: 50 }).notNull(),
  definition: text("definition", { mode: "json" }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  created_by: text("created_by", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_workflow_version_created_by: index("ix_workflow_version_created_by").on(t.created_by),
    ix_workflow_version_workflow_id: index("ix_workflow_version_workflow_id").on(t.workflow_id),
    uq_workflow_version_workflow_version: unique("uq_workflow_version_workflow_version").on(t.workflow_id, t.version),
    fk_workflow_version_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_workflow_version_1: foreignKey({ columns: [t.workflow_id], foreignColumns: [workflow.id] }),
  })
);

export const workflow_node = sqliteTable("workflow_node", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  workflow_version_id: text("workflow_version_id", { length: 36 }).notNull(),
  node_key: text("node_key", { length: 255 }).notNull(),
  type: text("type", { length: 50 }).notNull(),
  config: text("config", { mode: "json" }).notNull(),
  position: text("position", { mode: "json" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_workflow_node_workflow_version_id: index("ix_workflow_node_workflow_version_id").on(t.workflow_version_id),
    uq_workflow_node_version_node_key: unique("uq_workflow_node_version_node_key").on(t.workflow_version_id, t.node_key),
    fk_workflow_node_0: foreignKey({ columns: [t.workflow_version_id], foreignColumns: [workflow_version.id] }),
  })
);

export const workflow_edge = sqliteTable("workflow_edge", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  workflow_version_id: text("workflow_version_id", { length: 36 }).notNull(),
  from_node_key: text("from_node_key", { length: 255 }).notNull(),
  to_node_key: text("to_node_key", { length: 255 }).notNull(),
  condition: text("condition"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_workflow_edge_workflow_version_id: index("ix_workflow_edge_workflow_version_id").on(t.workflow_version_id),
    uq_workflow_edge_version_from_to: unique("uq_workflow_edge_version_from_to").on(t.workflow_version_id, t.from_node_key, t.to_node_key),
    fk_workflow_edge_0: foreignKey({ columns: [t.workflow_version_id], foreignColumns: [workflow_version.id] }),
  })
);

export const workflow_run = sqliteTable("workflow_run", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  workflow_version_id: text("workflow_version_id", { length: 36 }).notNull(),
  trigger: text("trigger", { length: 50 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  task_id: text("task_id", { length: 36 }),
  input: text("input", { mode: "json" }),
  output: text("output", { mode: "json" }),
  started_at: text("started_at"),
  completed_at: text("completed_at"),
  error: text("error"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const workflow_node_run = sqliteTable("workflow_node_run", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  workflow_run_id: text("workflow_run_id", { length: 36 }).notNull(),
  node_key: text("node_key", { length: 255 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  attempt: integer("attempt").notNull(),
  agent_run_id: text("agent_run_id", { length: 36 }),
  tool_call_id: text("tool_call_id", { length: 36 }),
  approval_id: text("approval_id", { length: 36 }),
  input: text("input", { mode: "json" }),
  output: text("output", { mode: "json" }),
  started_at: text("started_at"),
  completed_at: text("completed_at"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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
