// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.pg.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：identity · 表数 14

import { boolean, foreignKey, index, jsonb, pgTable, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;

export const tenant = pgTable("tenant", {
  id: uuid("id").notNull().primaryKey(),
  name: varchar("name", { length: 255 }).notNull(),
  slug: varchar("slug", { length: 255 }).notNull(),
  is_active: boolean("is_active").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_tenant_slug: uniqueIndex("ix_tenant_slug").on(t.slug),
  })
);

export const organization = pgTable("organization", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  name: varchar("name", { length: 255 }).notNull(),
  slug: varchar("slug", { length: 255 }).notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_organization_slug: index("ix_organization_slug").on(t.slug),
    ix_organization_tenant_id: index("ix_organization_tenant_id").on(t.tenant_id),
    fk_organization_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const workspace = pgTable("workspace", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  owner_id: uuid("owner_id").notNull(),
  name: varchar("name", { length: 255 }).notNull(),
  workspace_type: varchar("workspace_type", { length: 50 }).notNull(),
  settings: jsonb("settings"),
  config: jsonb("config"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workspace_organization_id: index("ix_workspace_organization_id").on(t.organization_id),
    ix_workspace_owner_id: index("ix_workspace_owner_id").on(t.owner_id),
    ix_workspace_tenant_id: index("ix_workspace_tenant_id").on(t.tenant_id),
    fk_workspace_0: foreignKey({ columns: [t.organization_id], foreignColumns: [organization.id] }),
    fk_workspace_1: foreignKey({ columns: [t.owner_id], foreignColumns: [user.id] }),
    fk_workspace_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const workspace_environment = pgTable("workspace_environment", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id").notNull(),
  name: varchar("name", { length: 50 }).notNull(),
  env_vars: jsonb("env_vars"),
  runtime: jsonb("runtime"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_workspace_environment_organization_id: index("ix_workspace_environment_organization_id").on(t.organization_id),
    ix_workspace_environment_tenant_id: index("ix_workspace_environment_tenant_id").on(t.tenant_id),
    ix_workspace_environment_workspace_id: index("ix_workspace_environment_workspace_id").on(t.workspace_id),
    uq_workspace_environment_ws_name: unique("uq_workspace_environment_ws_name").on(t.workspace_id, t.name),
    fk_workspace_environment_0: foreignKey({ columns: [t.organization_id], foreignColumns: [organization.id] }),
    fk_workspace_environment_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
    fk_workspace_environment_2: foreignKey({ columns: [t.workspace_id], foreignColumns: [workspace.id] }),
  })
);

export const user = pgTable("user", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  username: varchar("username", { length: 150 }).notNull(),
  email: varchar("email", { length: 320 }).notNull(),
  password_hash: varchar("password_hash", { length: 255 }).notNull(),
  display_name: varchar("display_name", { length: 255 }),
  is_active: boolean("is_active").notNull(),
  is_superuser: boolean("is_superuser").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_user_email: index("ix_user_email").on(t.email),
    ix_user_tenant_id: index("ix_user_tenant_id").on(t.tenant_id),
    ix_user_username: index("ix_user_username").on(t.username),
    uq_user_tenant_email: unique("uq_user_tenant_email").on(t.tenant_id, t.email),
    fk_user_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const membership = pgTable("membership", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  user_id: uuid("user_id").notNull(),
  organization_id: uuid("organization_id"),
  role_id: uuid("role_id"),
  status: varchar("status", { length: 50 }).notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_membership_organization_id: index("ix_membership_organization_id").on(t.organization_id),
    ix_membership_role_id: index("ix_membership_role_id").on(t.role_id),
    ix_membership_tenant_id: index("ix_membership_tenant_id").on(t.tenant_id),
    ix_membership_user_id: index("ix_membership_user_id").on(t.user_id),
    fk_membership_0: foreignKey({ columns: [t.organization_id], foreignColumns: [organization.id] }),
    fk_membership_1: foreignKey({ columns: [t.role_id], foreignColumns: [role.id] }),
    fk_membership_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
    fk_membership_3: foreignKey({ columns: [t.user_id], foreignColumns: [user.id] }),
  })
);

export const role = pgTable("role", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  name: varchar("name", { length: 100 }).notNull(),
  description: varchar("description", { length: 255 }),
  is_system: boolean("is_system").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_role_tenant_id: index("ix_role_tenant_id").on(t.tenant_id),
    uq_role_tenant_name: unique("uq_role_tenant_name").on(t.tenant_id, t.name),
    fk_role_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const permission = pgTable("permission", {
  id: uuid("id").notNull().primaryKey(),
  code: varchar("code", { length: 150 }).notNull(),
  name: varchar("name", { length: 150 }).notNull(),
  description: varchar("description", { length: 255 }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_permission_code: uniqueIndex("ix_permission_code").on(t.code),
  })
);

export const role_permission = pgTable("role_permission", {
  id: uuid("id").notNull().primaryKey(),
  role_id: uuid("role_id").notNull(),
  permission_id: uuid("permission_id").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_role_permission_permission_id: index("ix_role_permission_permission_id").on(t.permission_id),
    ix_role_permission_role_id: index("ix_role_permission_role_id").on(t.role_id),
    uq_role_permission: unique("uq_role_permission").on(t.role_id, t.permission_id),
    fk_role_permission_0: foreignKey({ columns: [t.permission_id], foreignColumns: [permission.id] }),
    fk_role_permission_1: foreignKey({ columns: [t.role_id], foreignColumns: [role.id] }),
  })
);

export const refresh_token = pgTable("refresh_token", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  user_id: uuid("user_id").notNull(),
  session_id: uuid("session_id"),
  token_hash: varchar("token_hash", { length: 255 }).notNull(),
  expires_at: timestamp("expires_at", { withTimezone: true }).notNull(),
  revoked_at: timestamp("revoked_at", { withTimezone: true }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_refresh_token_session_id: index("ix_refresh_token_session_id").on(t.session_id),
    ix_refresh_token_tenant_id: index("ix_refresh_token_tenant_id").on(t.tenant_id),
    ix_refresh_token_token_hash: index("ix_refresh_token_token_hash").on(t.token_hash),
    ix_refresh_token_user_id: index("ix_refresh_token_user_id").on(t.user_id),
    fk_refresh_token_0: foreignKey({ columns: [t.session_id], foreignColumns: [session.id] }),
    fk_refresh_token_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
    fk_refresh_token_2: foreignKey({ columns: [t.user_id], foreignColumns: [user.id] }),
  })
);

export const login_attempt = pgTable("login_attempt", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id"),
  username: varchar("username", { length: 150 }),
  ip_address: varchar("ip_address", { length: 64 }),
  success: boolean("success").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_login_attempt_tenant_id: index("ix_login_attempt_tenant_id").on(t.tenant_id),
    ix_login_attempt_username: index("ix_login_attempt_username").on(t.username),
    fk_login_attempt_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const session = pgTable("session", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  user_id: uuid("user_id").notNull(),
  device: varchar("device", { length: 255 }),
  ip_address: varchar("ip_address", { length: 64 }),
  user_agent: varchar("user_agent", { length: 512 }),
  expires_at: timestamp("expires_at", { withTimezone: true }).notNull(),
  revoked_at: timestamp("revoked_at", { withTimezone: true }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_session_tenant_id: index("ix_session_tenant_id").on(t.tenant_id),
    ix_session_user_id: index("ix_session_user_id").on(t.user_id),
    fk_session_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
    fk_session_1: foreignKey({ columns: [t.user_id], foreignColumns: [user.id] }),
  })
);

export const resource_permission = pgTable("resource_permission", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  subject_type: varchar("subject_type", { length: 20 }).notNull(),
  subject_id: uuid("subject_id").notNull(),
  resource_type: varchar("resource_type", { length: 30 }).notNull(),
  resource_id: uuid("resource_id"),
  action: varchar("action", { length: 20 }).notNull(),
  effect: varchar("effect", { length: 10 }).notNull(),
  scope: jsonb("scope").notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_resource_permission_resource: index("ix_resource_permission_resource").on(t.tenant_id, t.resource_type, t.resource_id),
    ix_resource_permission_subject: index("ix_resource_permission_subject").on(t.tenant_id, t.subject_type, t.subject_id),
    ix_resource_permission_tenant_id: index("ix_resource_permission_tenant_id").on(t.tenant_id),
    uq_resource_permission_subject_resource_action: unique("uq_resource_permission_subject_resource_action").on(t.tenant_id, t.subject_type, t.subject_id, t.resource_type, t.resource_id, t.action),
    fk_resource_permission_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const feature_flag = pgTable("feature_flag", {
  id: uuid("id").notNull().primaryKey(),
  name: varchar("name", { length: 150 }).notNull(),
  enabled: boolean("enabled").notNull(),
  description: varchar("description", { length: 255 }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_feature_flag_name: uniqueIndex("ix_feature_flag_name").on(t.name),
  })
);
