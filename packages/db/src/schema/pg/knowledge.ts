// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.pg.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：knowledge · 表数 6

import { doublePrecision, foreignKey, index, integer, jsonb, pgTable, text, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { vector1536 } from "./_types.js";
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";
import * as taskNS from "./task.js";

export const knowledge_base = pgTable("knowledge_base", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  name: varchar("name", { length: 255 }).notNull(),
  description: text("description"),
  embedding_model: jsonb("embedding_model").notNull(),
  chunk_config: jsonb("chunk_config").notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  created_by: uuid("created_by").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_knowledge_base_created_by: index("ix_knowledge_base_created_by").on(t.created_by),
    ix_knowledge_base_organization_id: index("ix_knowledge_base_organization_id").on(t.organization_id),
    ix_knowledge_base_tenant_id: index("ix_knowledge_base_tenant_id").on(t.tenant_id),
    ix_knowledge_base_workspace_id: index("ix_knowledge_base_workspace_id").on(t.workspace_id),
    uq_knowledge_base_tenant_name: unique("uq_knowledge_base_tenant_name").on(t.tenant_id, t.name),
    fk_knowledge_base_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_knowledge_base_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_knowledge_base_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_knowledge_base_3: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const document = pgTable("document", {
  id: uuid("id").notNull().primaryKey(),
  knowledge_base_id: uuid("knowledge_base_id").notNull(),
  title: varchar("title", { length: 512 }).notNull(),
  source_type: varchar("source_type", { length: 20 }).notNull(),
  storage_key: varchar("storage_key", { length: 1024 }),
  mime: varchar("mime", { length: 255 }),
  size: integer("size"),
  checksum: varchar("checksum", { length: 128 }),
  status: varchar("status", { length: 50 }).notNull(),
  error: text("error"),
  task_id: uuid("task_id"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_document_knowledge_base_id: index("ix_document_knowledge_base_id").on(t.knowledge_base_id),
    ix_document_status: index("ix_document_status").on(t.status),
    ix_document_task_id: index("ix_document_task_id").on(t.task_id),
    fk_document_0: foreignKey({ columns: [t.knowledge_base_id], foreignColumns: [knowledge_base.id] }),
    fk_document_1: foreignKey({ columns: [t.task_id], foreignColumns: [taskNS.task.id] }),
  })
);

export const document_chunk = pgTable("document_chunk", {
  id: uuid("id").notNull().primaryKey(),
  document_id: uuid("document_id").notNull(),
  ordinal: integer("ordinal").notNull(),
  content: text("content").notNull(),
  token_count: integer("token_count"),
  metadata: jsonb("metadata"),
  embedding_id: uuid("embedding_id"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_document_chunk_document_id: index("ix_document_chunk_document_id").on(t.document_id),
    uq_document_chunk_document_ordinal: unique("uq_document_chunk_document_ordinal").on(t.document_id, t.ordinal),
    fk_document_chunk_0: foreignKey({ columns: [t.document_id], foreignColumns: [document.id] }),
  })
);

export const embedding = pgTable("embedding", {
  id: uuid("id").notNull().primaryKey(),
  chunk_id: uuid("chunk_id").notNull(),
  model: varchar("model", { length: 255 }).notNull(),
  dimensions: integer("dimensions").notNull(),
  vector: vector1536("vector").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_embedding_chunk_id: index("ix_embedding_chunk_id").on(t.chunk_id),
    uq_embedding_chunk_id: unique("uq_embedding_chunk_id").on(t.chunk_id),
    fk_embedding_0: foreignKey({ columns: [t.chunk_id], foreignColumns: [document_chunk.id] }),
  })
);

export const memory = pgTable("memory", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  kind: varchar("kind", { length: 50 }).notNull(),
  scope_type: varchar("scope_type", { length: 50 }).notNull(),
  scope_id: varchar("scope_id", { length: 255 }).notNull(),
  visibility: varchar("visibility", { length: 50 }).notNull(),
  content: text("content").notNull(),
  memory_type: varchar("memory_type", { length: 50 }).notNull(),
  importance: doublePrecision("importance").notNull(),
  confidence: doublePrecision("confidence").notNull(),
  source_run_id: uuid("source_run_id"),
  vector: vector1536("vector"),
  expires_at: timestamp("expires_at", { withTimezone: true }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_memory_expires_at: index("ix_memory_expires_at").on(t.expires_at),
    ix_memory_organization_id: index("ix_memory_organization_id").on(t.organization_id),
    ix_memory_source_run_id: index("ix_memory_source_run_id").on(t.source_run_id),
    ix_memory_tenant_id: index("ix_memory_tenant_id").on(t.tenant_id),
    ix_memory_tenant_scope_kind: index("ix_memory_tenant_scope_kind").on(t.tenant_id, t.scope_type, t.scope_id, t.kind),
    ix_memory_workspace_id: index("ix_memory_workspace_id").on(t.workspace_id),
    fk_memory_0: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_memory_1: foreignKey({ columns: [t.source_run_id], foreignColumns: [agentNS.agent_run.id] }),
    fk_memory_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_memory_3: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const memory_relation = pgTable("memory_relation", {
  id: uuid("id").notNull().primaryKey(),
  from_memory_id: uuid("from_memory_id").notNull(),
  to_memory_id: uuid("to_memory_id").notNull(),
  relation: varchar("relation", { length: 50 }).notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_memory_relation_from_memory_id: index("ix_memory_relation_from_memory_id").on(t.from_memory_id),
    ix_memory_relation_to_memory_id: index("ix_memory_relation_to_memory_id").on(t.to_memory_id),
    uq_memory_relation_from_to_relation: unique("uq_memory_relation_from_to_relation").on(t.from_memory_id, t.to_memory_id, t.relation),
    fk_memory_relation_0: foreignKey({ columns: [t.from_memory_id], foreignColumns: [memory.id] }),
    fk_memory_relation_1: foreignKey({ columns: [t.to_memory_id], foreignColumns: [memory.id] }),
  })
);
