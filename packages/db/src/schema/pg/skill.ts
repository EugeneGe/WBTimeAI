// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.pg.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：skill · 表数 4

import { foreignKey, index, integer, json, jsonb, pgTable, text, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import * as identityNS from "./identity.js";

export const skill = pgTable("skill", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  name: varchar("name", { length: 255 }).notNull(),
  display_name: varchar("display_name", { length: 255 }).notNull(),
  description: text("description"),
  category: varchar("category", { length: 100 }).notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  current_version_id: uuid("current_version_id"),
  created_by: uuid("created_by").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
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

export const skill_version = pgTable("skill_version", {
  id: uuid("id").notNull().primaryKey(),
  skill_id: uuid("skill_id").notNull(),
  version: varchar("version", { length: 50 }).notNull(),
  instructions: text("instructions").notNull(),
  manifest: jsonb("manifest").notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  created_by: uuid("created_by").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_skill_version_created_by: index("ix_skill_version_created_by").on(t.created_by),
    ix_skill_version_skill_id: index("ix_skill_version_skill_id").on(t.skill_id),
    uq_skill_version_skill_version: unique("uq_skill_version_skill_version").on(t.skill_id, t.version),
    fk_skill_version_0: foreignKey({ columns: [t.created_by], foreignColumns: [identityNS.user.id] }),
    fk_skill_version_1: foreignKey({ columns: [t.skill_id], foreignColumns: [skill.id] }),
  })
);

export const skill_resource = pgTable("skill_resource", {
  id: uuid("id").notNull().primaryKey(),
  skill_version_id: uuid("skill_version_id").notNull(),
  path: varchar("path", { length: 1024 }).notNull(),
  kind: varchar("kind", { length: 50 }).notNull(),
  storage_key: varchar("storage_key", { length: 1024 }),
  checksum: varchar("checksum", { length: 128 }),
  size: integer("size"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_skill_resource_skill_version_id: index("ix_skill_resource_skill_version_id").on(t.skill_version_id),
    fk_skill_resource_0: foreignKey({ columns: [t.skill_version_id], foreignColumns: [skill_version.id] }),
  })
);

export const plugin = pgTable("plugin", {
  id: uuid("id").notNull().primaryKey(),
  name: varchar("name", { length: 150 }).notNull(),
  version: varchar("version", { length: 50 }).notNull(),
  kind: varchar("kind", { length: 50 }).notNull(),
  entry_point: varchar("entry_point", { length: 255 }),
  permissions: json("permissions").notNull(),
  manifest: json("manifest").notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  installed_at: timestamp("installed_at", { withTimezone: true }).notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_plugin_name: uniqueIndex("ix_plugin_name").on(t.name),
  })
);
