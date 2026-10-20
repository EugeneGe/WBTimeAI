// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.sqlite.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：knowledge · 表数 6

import { foreignKey, index, integer, real, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";
import * as taskNS from "./task.js";

export const knowledge_base = sqliteTable("knowledge_base", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  description: text("description"),
  embedding_model: text("embedding_model", { mode: "json" }).notNull(),
  chunk_config: text("chunk_config", { mode: "json" }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  created_by: text("created_by", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const document = sqliteTable("document", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  knowledge_base_id: text("knowledge_base_id", { length: 36 }).notNull(),
  title: text("title", { length: 512 }).notNull(),
  source_type: text("source_type", { length: 20 }).notNull(),
  storage_key: text("storage_key", { length: 1024 }),
  mime: text("mime", { length: 255 }),
  size: integer("size"),
  checksum: text("checksum", { length: 128 }),
  status: text("status", { length: 50 }).notNull(),
  error: text("error"),
  task_id: text("task_id", { length: 36 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_document_knowledge_base_id: index("ix_document_knowledge_base_id").on(t.knowledge_base_id),
    ix_document_status: index("ix_document_status").on(t.status),
    ix_document_task_id: index("ix_document_task_id").on(t.task_id),
    fk_document_0: foreignKey({ columns: [t.knowledge_base_id], foreignColumns: [knowledge_base.id] }),
    fk_document_1: foreignKey({ columns: [t.task_id], foreignColumns: [taskNS.task.id] }),
  })
);

export const document_chunk = sqliteTable("document_chunk", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  document_id: text("document_id", { length: 36 }).notNull(),
  ordinal: integer("ordinal").notNull(),
  content: text("content").notNull(),
  token_count: integer("token_count"),
  metadata: text("metadata", { mode: "json" }),
  embedding_id: text("embedding_id", { length: 36 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_document_chunk_document_id: index("ix_document_chunk_document_id").on(t.document_id),
    uq_document_chunk_document_ordinal: unique("uq_document_chunk_document_ordinal").on(t.document_id, t.ordinal),
    fk_document_chunk_0: foreignKey({ columns: [t.document_id], foreignColumns: [document.id] }),
  })
);

export const embedding = sqliteTable("embedding", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  chunk_id: text("chunk_id", { length: 36 }).notNull(),
  model: text("model", { length: 255 }).notNull(),
  dimensions: integer("dimensions").notNull(),
  vector: text("vector", { mode: "json" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_embedding_chunk_id: index("ix_embedding_chunk_id").on(t.chunk_id),
    uq_embedding_chunk_id: unique("uq_embedding_chunk_id").on(t.chunk_id),
    fk_embedding_0: foreignKey({ columns: [t.chunk_id], foreignColumns: [document_chunk.id] }),
  })
);

export const memory = sqliteTable("memory", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  kind: text("kind", { length: 50 }).notNull(),
  scope_type: text("scope_type", { length: 50 }).notNull(),
  scope_id: text("scope_id", { length: 255 }).notNull(),
  visibility: text("visibility", { length: 50 }).notNull(),
  content: text("content").notNull(),
  memory_type: text("memory_type", { length: 50 }).notNull(),
  importance: real("importance").notNull(),
  confidence: real("confidence").notNull(),
  source_run_id: text("source_run_id", { length: 36 }),
  vector: text("vector", { mode: "json" }),
  expires_at: text("expires_at"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const memory_relation = sqliteTable("memory_relation", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  from_memory_id: text("from_memory_id", { length: 36 }).notNull(),
  to_memory_id: text("to_memory_id", { length: 36 }).notNull(),
  relation: text("relation", { length: 50 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_memory_relation_from_memory_id: index("ix_memory_relation_from_memory_id").on(t.from_memory_id),
    ix_memory_relation_to_memory_id: index("ix_memory_relation_to_memory_id").on(t.to_memory_id),
    uq_memory_relation_from_to_relation: unique("uq_memory_relation_from_to_relation").on(t.from_memory_id, t.to_memory_id, t.relation),
    fk_memory_relation_0: foreignKey({ columns: [t.from_memory_id], foreignColumns: [memory.id] }),
    fk_memory_relation_1: foreignKey({ columns: [t.to_memory_id], foreignColumns: [memory.id] }),
  })
);
