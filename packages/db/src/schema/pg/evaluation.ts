// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.pg.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：evaluation · 表数 4

import { doublePrecision, foreignKey, index, integer, jsonb, pgTable, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";

export const evaluation_dataset = pgTable("evaluation_dataset", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  name: varchar("name", { length: 255 }).notNull(),
  version: integer("version").notNull(),
  parent_dataset_id: uuid("parent_dataset_id"),
  status: varchar("status", { length: 50 }).notNull(),
  description: varchar("description", { length: 1024 }),
  created_by: uuid("created_by"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_evaluation_dataset_organization_id: index("ix_evaluation_dataset_organization_id").on(t.organization_id),
    ix_evaluation_dataset_tenant_id: index("ix_evaluation_dataset_tenant_id").on(t.tenant_id),
    ix_evaluation_dataset_workspace_id: index("ix_evaluation_dataset_workspace_id").on(t.workspace_id),
    fk_evaluation_dataset_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_evaluation_dataset_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_evaluation_dataset_2: foreignKey({ columns: [t.parent_dataset_id], foreignColumns: [t.id] }),
    fk_evaluation_dataset_3: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_evaluation_dataset_4: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const evaluation_case = pgTable("evaluation_case", {
  id: uuid("id").notNull().primaryKey(),
  dataset_id: uuid("dataset_id").notNull(),
  case_key: varchar("case_key", { length: 255 }).notNull(),
  input: jsonb("input").notNull(),
  expected: jsonb("expected"),
  assertions: jsonb("assertions"),
  tags: jsonb("tags"),
  position: integer("position").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_evaluation_case_dataset_id: index("ix_evaluation_case_dataset_id").on(t.dataset_id),
    uq_evaluation_case_dataset_case_key: unique("uq_evaluation_case_dataset_case_key").on(t.dataset_id, t.case_key),
    fk_evaluation_case_0: foreignKey({ columns: [t.dataset_id], foreignColumns: [evaluation_dataset.id] }),
  })
);

export const evaluation_run = pgTable("evaluation_run", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  dataset_id: uuid("dataset_id").notNull(),
  agent_id: uuid("agent_id").notNull(),
  agent_version_id: uuid("agent_version_id").notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  idempotency_key: varchar("idempotency_key", { length: 255 }),
  started_at: timestamp("started_at", { withTimezone: true }),
  completed_at: timestamp("completed_at", { withTimezone: true }),
  summary: jsonb("summary"),
  created_by: uuid("created_by"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_evaluation_run_agent_id: index("ix_evaluation_run_agent_id").on(t.agent_id),
    ix_evaluation_run_agent_version_id: index("ix_evaluation_run_agent_version_id").on(t.agent_version_id),
    ix_evaluation_run_dataset_id: index("ix_evaluation_run_dataset_id").on(t.dataset_id),
    ix_evaluation_run_organization_id: index("ix_evaluation_run_organization_id").on(t.organization_id),
    ix_evaluation_run_tenant_id: index("ix_evaluation_run_tenant_id").on(t.tenant_id),
    ix_evaluation_run_workspace_id: index("ix_evaluation_run_workspace_id").on(t.workspace_id),
    uq_evaluation_run_idempotency_key: unique("uq_evaluation_run_idempotency_key").on(t.idempotency_key),
    fk_evaluation_run_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agentNS.agent.id] }),
    fk_evaluation_run_1: foreignKey({ columns: [t.agent_version_id], foreignColumns: [agentNS.agent_version.id] }),
    fk_evaluation_run_2: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_evaluation_run_3: foreignKey({ columns: [t.dataset_id], foreignColumns: [evaluation_dataset.id] }),
    fk_evaluation_run_4: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_evaluation_run_5: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_evaluation_run_6: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const evaluation_result = pgTable("evaluation_result", {
  id: uuid("id").notNull().primaryKey(),
  evaluation_run_id: uuid("evaluation_run_id").notNull(),
  case_id: uuid("case_id").notNull(),
  agent_run_id: uuid("agent_run_id"),
  status: varchar("status", { length: 50 }).notNull(),
  score: doublePrecision("score"),
  assertion_results: jsonb("assertion_results"),
  duration_ms: integer("duration_ms"),
  token_usage: jsonb("token_usage"),
  cost: doublePrecision("cost"),
  error_type: varchar("error_type", { length: 50 }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_evaluation_result_agent_run_id: index("ix_evaluation_result_agent_run_id").on(t.agent_run_id),
    ix_evaluation_result_case_id: index("ix_evaluation_result_case_id").on(t.case_id),
    ix_evaluation_result_evaluation_run_id: index("ix_evaluation_result_evaluation_run_id").on(t.evaluation_run_id),
    uq_evaluation_result_run_case: unique("uq_evaluation_result_run_case").on(t.evaluation_run_id, t.case_id),
    fk_evaluation_result_0: foreignKey({ columns: [t.agent_run_id], foreignColumns: [agentNS.agent_run.id] }),
    fk_evaluation_result_1: foreignKey({ columns: [t.case_id], foreignColumns: [evaluation_case.id] }),
    fk_evaluation_result_2: foreignKey({ columns: [t.evaluation_run_id], foreignColumns: [evaluation_run.id] }),
  })
);
