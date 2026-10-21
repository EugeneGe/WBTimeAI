// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.sqlite.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：task · 表数 4

import { foreignKey, index, integer, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as identityNS from "./identity.js";

export const project = sqliteTable("project", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }).notNull(),
  name: text("name", { length: 255 }).notNull(),
  description: text("description", { length: 1024 }),
  repo_url: text("repo_url", { length: 2048 }),
  default_branch: text("default_branch", { length: 255 }),
  settings: text("settings", { mode: "json" }),
  created_by: text("created_by", { length: 36 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_project_organization_id: index("ix_project_organization_id").on(t.organization_id),
    ix_project_tenant_id: index("ix_project_tenant_id").on(t.tenant_id),
    ix_project_workspace_id: index("ix_project_workspace_id").on(t.workspace_id),
    fk_project_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_project_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_project_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_project_3: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const task = sqliteTable("task", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  type: text("type", { length: 100 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  priority: integer("priority").notNull(),
  execution_mode: text("execution_mode", { length: 20 }).notNull(),
  payload: text("payload", { mode: "json" }),
  result: text("result", { mode: "json" }),
  idempotency_key: text("idempotency_key", { length: 255 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_task_organization_id: index("ix_task_organization_id").on(t.organization_id),
    ix_task_status: index("ix_task_status").on(t.status),
    ix_task_tenant_id: index("ix_task_tenant_id").on(t.tenant_id),
    ix_task_workspace_id: index("ix_task_workspace_id").on(t.workspace_id),
    uq_task_idempotency_key: uniqueIndex("uq_task_idempotency_key").on(t.idempotency_key),
    fk_task_0: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_task_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_task_2: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const task_execution = sqliteTable("task_execution", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  task_id: text("task_id", { length: 36 }).notNull(),
  attempt: integer("attempt").notNull(),
  worker_id: text("worker_id", { length: 128 }),
  status: text("status", { length: 50 }).notNull(),
  started_at: text("started_at"),
  finished_at: text("finished_at"),
  duration_ms: integer("duration_ms"),
  error: text("error"),
  project_id: text("project_id", { length: 36 }),
  checkout_ref: text("checkout_ref", { length: 128 }),
  base_commit: text("base_commit", { length: 64 }),
  result_commit: text("result_commit", { length: 64 }),
  environment_digest: text("environment_digest", { length: 64 }),
  artifact_refs: text("artifact_refs", { mode: "json" }),
  heartbeat_at: text("heartbeat_at"),
  lease_expires_at: text("lease_expires_at"),
}, (t): ExtraConfig => ({
    ix_task_execution_project_started: index("ix_task_execution_project_started").on(t.project_id, t.started_at),
    ix_task_execution_task_id: index("ix_task_execution_task_id").on(t.task_id),
    uq_task_execution_checkout_ref: uniqueIndex("uq_task_execution_checkout_ref").on(t.checkout_ref).where(sql`checkout_ref IS NOT NULL`),
    uq_task_execution_task_attempt: unique("uq_task_execution_task_attempt").on(t.task_id, t.attempt),
    fk_task_execution_0: foreignKey({ columns: [t.task_id], foreignColumns: [task.id] }),
    fk_task_execution_project_id: foreignKey({ name: "fk_task_execution_project_id", columns: [t.project_id], foreignColumns: [project.id] }),
  })
);

export const schedule = sqliteTable("schedule", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  target_type: text("target_type", { length: 30 }).notNull(),
  target_id: text("target_id", { length: 36 }).notNull(),
  trigger: text("trigger", { length: 20 }).notNull(),
  cron: text("cron", { length: 255 }),
  event_type: text("event_type", { length: 100 }),
  payload: text("payload", { mode: "json" }),
  enabled: integer("enabled", { mode: "boolean" }).notNull(),
  last_run_at: text("last_run_at"),
  next_run_at: text("next_run_at"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_schedule_next_run_at: index("ix_schedule_next_run_at").on(t.next_run_at),
    ix_schedule_organization_id: index("ix_schedule_organization_id").on(t.organization_id),
    ix_schedule_tenant_id: index("ix_schedule_tenant_id").on(t.tenant_id),
    ix_schedule_workspace_id: index("ix_schedule_workspace_id").on(t.workspace_id),
    uq_schedule_target_name: unique("uq_schedule_target_name").on(t.tenant_id, t.target_type, t.target_id, t.name),
    fk_schedule_0: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_schedule_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_schedule_2: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);
