// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.sqlite.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：evaluation · 表数 4

import { foreignKey, index, integer, real, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";

export const evaluation_dataset = sqliteTable("evaluation_dataset", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  version: integer("version").notNull(),
  parent_dataset_id: text("parent_dataset_id", { length: 36 }),
  status: text("status", { length: 50 }).notNull(),
  description: text("description", { length: 1024 }),
  created_by: text("created_by", { length: 36 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const evaluation_case = sqliteTable("evaluation_case", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  dataset_id: text("dataset_id", { length: 36 }).notNull(),
  case_key: text("case_key", { length: 255 }).notNull(),
  input: text("input", { mode: "json" }).notNull(),
  expected: text("expected", { mode: "json" }),
  assertions: text("assertions", { mode: "json" }),
  tags: text("tags", { mode: "json" }),
  position: integer("position").notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_evaluation_case_dataset_id: index("ix_evaluation_case_dataset_id").on(t.dataset_id),
    uq_evaluation_case_dataset_case_key: unique("uq_evaluation_case_dataset_case_key").on(t.dataset_id, t.case_key),
    fk_evaluation_case_0: foreignKey({ columns: [t.dataset_id], foreignColumns: [evaluation_dataset.id] }),
  })
);

export const evaluation_run = sqliteTable("evaluation_run", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  dataset_id: text("dataset_id", { length: 36 }).notNull(),
  agent_id: text("agent_id", { length: 36 }).notNull(),
  agent_version_id: text("agent_version_id", { length: 36 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  idempotency_key: text("idempotency_key", { length: 255 }),
  started_at: text("started_at"),
  completed_at: text("completed_at"),
  summary: text("summary", { mode: "json" }),
  created_by: text("created_by", { length: 36 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const evaluation_result = sqliteTable("evaluation_result", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  evaluation_run_id: text("evaluation_run_id", { length: 36 }).notNull(),
  case_id: text("case_id", { length: 36 }).notNull(),
  agent_run_id: text("agent_run_id", { length: 36 }),
  status: text("status", { length: 50 }).notNull(),
  score: real("score"),
  assertion_results: text("assertion_results", { mode: "json" }),
  duration_ms: integer("duration_ms"),
  token_usage: text("token_usage", { mode: "json" }),
  cost: real("cost"),
  error_type: text("error_type", { length: 50 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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
