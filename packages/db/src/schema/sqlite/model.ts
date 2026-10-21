// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.sqlite.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：model · 表数 4

import { foreignKey, index, integer, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as identityNS from "./identity.js";

export const credential = sqliteTable("credential", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  provider: text("provider", { length: 100 }).notNull(),
  key_type: text("key_type", { length: 50 }).notNull(),
  encrypted_value: text("encrypted_value").notNull(),
  name: text("name", { length: 150 }),
  status: text("status", { length: 20 }).notNull(),
  last_used_at: text("last_used_at"),
  metadata: text("metadata", { mode: "json" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_credential_name: index("ix_credential_name").on(t.name),
    ix_credential_organization_id: index("ix_credential_organization_id").on(t.organization_id),
    ix_credential_tenant_id: index("ix_credential_tenant_id").on(t.tenant_id),
    ix_credential_workspace_id: index("ix_credential_workspace_id").on(t.workspace_id),
    fk_credential_0: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_credential_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_credential_2: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const model_provider = sqliteTable("model_provider", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  type: text("type", { length: 50 }).notNull(),
  endpoint: text("endpoint", { length: 512 }),
  credential_id: text("credential_id", { length: 36 }),
  status: text("status", { length: 50 }).notNull(),
  config: text("config", { mode: "json" }),
}, (t): ExtraConfig => ({
    ix_model_provider_credential_id: index("ix_model_provider_credential_id").on(t.credential_id),
    ix_model_provider_organization_id: index("ix_model_provider_organization_id").on(t.organization_id),
    ix_model_provider_tenant_id: index("ix_model_provider_tenant_id").on(t.tenant_id),
    ix_model_provider_workspace_id: index("ix_model_provider_workspace_id").on(t.workspace_id),
    fk_model_provider_0: foreignKey({ columns: [t.credential_id], foreignColumns: [credential.id] }),
    fk_model_provider_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_model_provider_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_model_provider_3: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const model_provider_credential = sqliteTable("model_provider_credential", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  provider_id: text("provider_id", { length: 36 }).notNull(),
  credential_id: text("credential_id", { length: 36 }).notNull(),
  weight: integer("weight").notNull(),
  status: text("status", { length: 20 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_model_provider_credential_credential_id: index("ix_model_provider_credential_credential_id").on(t.credential_id),
    ix_model_provider_credential_provider_id: index("ix_model_provider_credential_provider_id").on(t.provider_id),
    uq_model_provider_credential: unique("uq_model_provider_credential").on(t.provider_id, t.credential_id),
    fk_model_provider_credential_0: foreignKey({ columns: [t.credential_id], foreignColumns: [credential.id] }),
    fk_model_provider_credential_1: foreignKey({ columns: [t.provider_id], foreignColumns: [model_provider.id] }),
  })
);

export const model = sqliteTable("model", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  provider_id: text("provider_id", { length: 36 }).notNull(),
  name: text("name", { length: 255 }).notNull(),
  type: text("type", { length: 50 }).notNull(),
  context_window: integer("context_window"),
  capabilities: text("capabilities", { mode: "json" }),
  status: text("status", { length: 50 }).notNull(),
}, (t): ExtraConfig => ({
    ix_model_provider_id: index("ix_model_provider_id").on(t.provider_id),
    fk_model_0: foreignKey({ columns: [t.provider_id], foreignColumns: [model_provider.id] }),
  })
);
