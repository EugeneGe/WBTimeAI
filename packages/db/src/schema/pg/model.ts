// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.pg.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：model · 表数 4

import { foreignKey, index, integer, jsonb, pgTable, text, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import * as identityNS from "./identity.js";

export const credential = pgTable("credential", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  provider: varchar("provider", { length: 100 }).notNull(),
  key_type: varchar("key_type", { length: 50 }).notNull(),
  encrypted_value: text("encrypted_value").notNull(),
  name: varchar("name", { length: 150 }),
  status: varchar("status", { length: 20 }).notNull(),
  last_used_at: timestamp("last_used_at", { withTimezone: true }),
  metadata: jsonb("metadata").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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

export const model_provider = pgTable("model_provider", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  name: varchar("name", { length: 255 }).notNull(),
  type: varchar("type", { length: 50 }).notNull(),
  endpoint: varchar("endpoint", { length: 512 }),
  credential_id: uuid("credential_id"),
  status: varchar("status", { length: 50 }).notNull(),
  config: jsonb("config"),
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

export const model_provider_credential = pgTable("model_provider_credential", {
  id: uuid("id").notNull().primaryKey(),
  provider_id: uuid("provider_id").notNull(),
  credential_id: uuid("credential_id").notNull(),
  weight: integer("weight").notNull(),
  status: varchar("status", { length: 20 }).notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_model_provider_credential_credential_id: index("ix_model_provider_credential_credential_id").on(t.credential_id),
    ix_model_provider_credential_provider_id: index("ix_model_provider_credential_provider_id").on(t.provider_id),
    uq_model_provider_credential: unique("uq_model_provider_credential").on(t.provider_id, t.credential_id),
    fk_model_provider_credential_0: foreignKey({ columns: [t.credential_id], foreignColumns: [credential.id] }),
    fk_model_provider_credential_1: foreignKey({ columns: [t.provider_id], foreignColumns: [model_provider.id] }),
  })
);

export const model = pgTable("model", {
  id: uuid("id").notNull().primaryKey(),
  provider_id: uuid("provider_id").notNull(),
  name: varchar("name", { length: 255 }).notNull(),
  type: varchar("type", { length: 50 }).notNull(),
  context_window: integer("context_window"),
  capabilities: jsonb("capabilities"),
  status: varchar("status", { length: 50 }).notNull(),
}, (t): ExtraConfig => ({
    ix_model_provider_id: index("ix_model_provider_id").on(t.provider_id),
    fk_model_0: foreignKey({ columns: [t.provider_id], foreignColumns: [model_provider.id] }),
  })
);
