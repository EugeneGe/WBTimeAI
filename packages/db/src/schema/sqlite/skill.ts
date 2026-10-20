// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.sqlite.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：skill · 表数 4

import { foreignKey, index, integer, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as identityNS from "./identity.js";

export const skill = sqliteTable("skill", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  display_name: text("display_name", { length: 255 }).notNull(),
  description: text("description"),
  category: text("category", { length: 100 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  current_version_id: text("current_version_id", { length: 36 }),
  created_by: text("created_by", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_skill_created_by: index("ix_skill_created_by").on(t.created_by),
    ix_skill_current_version_id: index("ix_skill_current_version_id").on(t.current_version_id),
    ix_skill_organization_id: index("ix_skill_organization_id").on(t.organization_id),
    ix_skill_tenant_id: index("ix_skill_tenant_id").on(t.tenant_id),
    uq_skill_tenant_name: unique("uq_skill_tenant_name").on(t.tenant_id, t.name),
    fk_skill_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_skill_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_skill_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_skill_current_version_id: foreignKey({ name: "fk_skill_current_version_id", columns: [t.current_version_id], foreignColumns: [skill_version.id] }),
  })
);

export const skill_version = sqliteTable("skill_version", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  skill_id: text("skill_id", { length: 36 }).notNull(),
  version: text("version", { length: 50 }).notNull(),
  instructions: text("instructions").notNull(),
  manifest: text("manifest", { mode: "json" }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  created_by: text("created_by", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_skill_version_created_by: index("ix_skill_version_created_by").on(t.created_by),
    ix_skill_version_skill_id: index("ix_skill_version_skill_id").on(t.skill_id),
    uq_skill_version_skill_version: unique("uq_skill_version_skill_version").on(t.skill_id, t.version),
    fk_skill_version_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_skill_version_1: foreignKey({ columns: [t.skill_id], foreignColumns: [skill.id] }),
  })
);

export const skill_resource = sqliteTable("skill_resource", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  skill_version_id: text("skill_version_id", { length: 36 }).notNull(),
  path: text("path", { length: 1024 }).notNull(),
  kind: text("kind", { length: 50 }).notNull(),
  storage_key: text("storage_key", { length: 1024 }),
  checksum: text("checksum", { length: 128 }),
  size: integer("size"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_skill_resource_skill_version_id: index("ix_skill_resource_skill_version_id").on(t.skill_version_id),
    fk_skill_resource_0: foreignKey({ columns: [t.skill_version_id], foreignColumns: [skill_version.id] }),
  })
);

export const plugin = sqliteTable("plugin", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  name: text("name", { length: 150 }).notNull(),
  version: text("version", { length: 50 }).notNull(),
  kind: text("kind", { length: 50 }).notNull(),
  entry_point: text("entry_point", { length: 255 }),
  permissions: text("permissions", { mode: "json" }).notNull(),
  manifest: text("manifest", { mode: "json" }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  installed_at: text("installed_at").notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_plugin_name: uniqueIndex("ix_plugin_name").on(t.name),
  })
);
