// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0019.sqlite.normalized.json（schema v0019，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：identity · 表数 14

import { foreignKey, index, integer, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uniqueIndex } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";

export const tenant = sqliteTable("tenant", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  name: text("name", { length: 255 }).notNull(),
  slug: text("slug", { length: 255 }).notNull(),
  is_active: integer("is_active", { mode: "boolean" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_tenant_slug: uniqueIndex("ix_tenant_slug").on(t.slug),
  })
);

export const organization = sqliteTable("organization", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  name: text("name", { length: 255 }).notNull(),
  slug: text("slug", { length: 255 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_organization_slug: index("ix_organization_slug").on(t.slug),
    ix_organization_tenant_id: index("ix_organization_tenant_id").on(t.tenant_id),
    fk_organization_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const workspace = sqliteTable("workspace", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  owner_id: text("owner_id", { length: 36 }).notNull(),
  name: text("name", { length: 255 }).notNull(),
  workspace_type: text("workspace_type", { length: 50 }).notNull(),
  settings: text("settings", { mode: "json" }),
  config: text("config", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_workspace_organization_id: index("ix_workspace_organization_id").on(t.organization_id),
    ix_workspace_owner_id: index("ix_workspace_owner_id").on(t.owner_id),
    ix_workspace_tenant_id: index("ix_workspace_tenant_id").on(t.tenant_id),
    fk_workspace_0: foreignKey({ columns: [t.organization_id], foreignColumns: [organization.id] }),
    fk_workspace_1: foreignKey({ columns: [t.owner_id], foreignColumns: [user.id] }),
    fk_workspace_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const workspace_environment = sqliteTable("workspace_environment", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }).notNull(),
  name: text("name", { length: 50 }).notNull(),
  env_vars: text("env_vars", { mode: "json" }),
  runtime: text("runtime", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const user = sqliteTable("user", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  username: text("username", { length: 150 }).notNull(),
  email: text("email", { length: 320 }).notNull(),
  password_hash: text("password_hash", { length: 255 }).notNull(),
  display_name: text("display_name", { length: 255 }),
  is_active: integer("is_active", { mode: "boolean" }).notNull(),
  is_superuser: integer("is_superuser", { mode: "boolean" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_user_email: index("ix_user_email").on(t.email),
    ix_user_tenant_id: index("ix_user_tenant_id").on(t.tenant_id),
    ix_user_username: index("ix_user_username").on(t.username),
    uq_user_tenant_email: unique("uq_user_tenant_email").on(t.tenant_id, t.email),
    fk_user_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const membership = sqliteTable("membership", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  user_id: text("user_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  role_id: text("role_id", { length: 36 }),
  status: text("status", { length: 50 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const role = sqliteTable("role", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  name: text("name", { length: 100 }).notNull(),
  description: text("description", { length: 255 }),
  is_system: integer("is_system", { mode: "boolean" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_role_tenant_id: index("ix_role_tenant_id").on(t.tenant_id),
    uq_role_tenant_name: unique("uq_role_tenant_name").on(t.tenant_id, t.name),
    fk_role_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const permission = sqliteTable("permission", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  code: text("code", { length: 150 }).notNull(),
  name: text("name", { length: 150 }).notNull(),
  description: text("description", { length: 255 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_permission_code: uniqueIndex("ix_permission_code").on(t.code),
  })
);

export const role_permission = sqliteTable("role_permission", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  role_id: text("role_id", { length: 36 }).notNull(),
  permission_id: text("permission_id", { length: 36 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_role_permission_permission_id: index("ix_role_permission_permission_id").on(t.permission_id),
    ix_role_permission_role_id: index("ix_role_permission_role_id").on(t.role_id),
    uq_role_permission: unique("uq_role_permission").on(t.role_id, t.permission_id),
    fk_role_permission_0: foreignKey({ columns: [t.permission_id], foreignColumns: [permission.id] }),
    fk_role_permission_1: foreignKey({ columns: [t.role_id], foreignColumns: [role.id] }),
  })
);

export const refresh_token = sqliteTable("refresh_token", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  user_id: text("user_id", { length: 36 }).notNull(),
  session_id: text("session_id", { length: 36 }),
  token_hash: text("token_hash", { length: 255 }).notNull(),
  expires_at: text("expires_at").notNull(),
  revoked_at: text("revoked_at"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const login_attempt = sqliteTable("login_attempt", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }),
  username: text("username", { length: 150 }),
  ip_address: text("ip_address", { length: 64 }),
  success: integer("success", { mode: "boolean" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_login_attempt_tenant_id: index("ix_login_attempt_tenant_id").on(t.tenant_id),
    ix_login_attempt_username: index("ix_login_attempt_username").on(t.username),
    fk_login_attempt_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const session = sqliteTable("session", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  user_id: text("user_id", { length: 36 }).notNull(),
  device: text("device", { length: 255 }),
  ip_address: text("ip_address", { length: 64 }),
  user_agent: text("user_agent", { length: 512 }),
  expires_at: text("expires_at").notNull(),
  revoked_at: text("revoked_at"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_session_tenant_id: index("ix_session_tenant_id").on(t.tenant_id),
    ix_session_user_id: index("ix_session_user_id").on(t.user_id),
    fk_session_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
    fk_session_1: foreignKey({ columns: [t.user_id], foreignColumns: [user.id] }),
  })
);

export const resource_permission = sqliteTable("resource_permission", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  subject_type: text("subject_type", { length: 20 }).notNull(),
  subject_id: text("subject_id", { length: 36 }).notNull(),
  resource_type: text("resource_type", { length: 30 }).notNull(),
  resource_id: text("resource_id", { length: 36 }),
  action: text("action", { length: 20 }).notNull(),
  effect: text("effect", { length: 10 }).notNull(),
  scope: text("scope", { mode: "json" }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_resource_permission_resource: index("ix_resource_permission_resource").on(t.tenant_id, t.resource_type, t.resource_id),
    ix_resource_permission_subject: index("ix_resource_permission_subject").on(t.tenant_id, t.subject_type, t.subject_id),
    ix_resource_permission_tenant_id: index("ix_resource_permission_tenant_id").on(t.tenant_id),
    uq_resource_permission_subject_resource_action: unique("uq_resource_permission_subject_resource_action").on(t.tenant_id, t.subject_type, t.subject_id, t.resource_type, t.resource_id, t.action),
    fk_resource_permission_0: foreignKey({ columns: [t.tenant_id], foreignColumns: [tenant.id] }),
  })
);

export const feature_flag = sqliteTable("feature_flag", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  name: text("name", { length: 150 }).notNull(),
  enabled: integer("enabled", { mode: "boolean" }).notNull(),
  description: text("description", { length: 255 }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_feature_flag_name: uniqueIndex("ix_feature_flag_name").on(t.name),
  })
);
