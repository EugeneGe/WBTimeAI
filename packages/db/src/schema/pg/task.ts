// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.pg.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：task · 表数 4

import { boolean, foreignKey, index, integer, jsonb, pgTable, text, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as identityNS from "./identity.js";

export const project = pgTable("project", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id").notNull(),
  name: varchar("name", { length: 255 }).notNull(),
  description: varchar("description", { length: 1024 }),
  repo_url: varchar("repo_url", { length: 2048 }),
  default_branch: varchar("default_branch", { length: 255 }),
  settings: jsonb("settings"),
  created_by: uuid("created_by"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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

export const task = pgTable("task", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  type: varchar("type", { length: 100 }).notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  priority: integer("priority").notNull(),
  execution_mode: varchar("execution_mode", { length: 20 }).notNull(),
  payload: jsonb("payload"),
  result: jsonb("result"),
  idempotency_key: varchar("idempotency_key", { length: 255 }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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

export const task_execution = pgTable("task_execution", {
  id: uuid("id").notNull().primaryKey(),
  task_id: uuid("task_id").notNull(),
  attempt: integer("attempt").notNull(),
  worker_id: varchar("worker_id", { length: 128 }),
  status: varchar("status", { length: 50 }).notNull(),
  started_at: timestamp("started_at", { withTimezone: true }),
  finished_at: timestamp("finished_at", { withTimezone: true }),
  duration_ms: integer("duration_ms"),
  error: text("error"),
  project_id: uuid("project_id"),
  checkout_ref: varchar("checkout_ref", { length: 128 }),
  base_commit: varchar("base_commit", { length: 64 }),
  result_commit: varchar("result_commit", { length: 64 }),
  environment_digest: varchar("environment_digest", { length: 64 }),
  artifact_refs: jsonb("artifact_refs"),
  heartbeat_at: timestamp("heartbeat_at", { withTimezone: true }),
  lease_expires_at: timestamp("lease_expires_at", { withTimezone: true }),
}, (t): ExtraConfig => ({
    ix_task_execution_project_started: index("ix_task_execution_project_started").on(t.project_id, t.started_at),
    ix_task_execution_task_id: index("ix_task_execution_task_id").on(t.task_id),
    uq_task_execution_checkout_ref: uniqueIndex("uq_task_execution_checkout_ref").on(t.checkout_ref).where(sql`checkout_ref IS NOT NULL`),
    uq_task_execution_task_attempt: unique("uq_task_execution_task_attempt").on(t.task_id, t.attempt),
    fk_task_execution_0: foreignKey({ columns: [t.task_id], foreignColumns: [task.id] }),
    fk_task_execution_project_id: foreignKey({ name: "fk_task_execution_project_id", columns: [t.project_id], foreignColumns: [project.id] }),
  })
);

export const schedule = pgTable("schedule", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  name: varchar("name", { length: 255 }).notNull(),
  target_type: varchar("target_type", { length: 30 }).notNull(),
  target_id: uuid("target_id").notNull(),
  trigger: varchar("trigger", { length: 20 }).notNull(),
  cron: varchar("cron", { length: 255 }),
  event_type: varchar("event_type", { length: 100 }),
  payload: jsonb("payload"),
  enabled: boolean("enabled").notNull(),
  last_run_at: timestamp("last_run_at", { withTimezone: true }),
  next_run_at: timestamp("next_run_at", { withTimezone: true }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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
