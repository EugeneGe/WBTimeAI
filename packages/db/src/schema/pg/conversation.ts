// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.pg.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：conversation · 表数 7

import { foreignKey, index, integer, jsonb, pgTable, text, timestamp, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique, uuid, varchar } from "drizzle-orm/pg-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";
import * as modelNS from "./model.js";

export const conversation = pgTable("conversation", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id").notNull(),
  agent_id: uuid("agent_id").notNull(),
  user_id: uuid("user_id").notNull(),
  title: varchar("title", { length: 255 }).notNull(),
  status: varchar("status", { length: 50 }).notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_conversation_agent_id: index("ix_conversation_agent_id").on(t.agent_id),
    ix_conversation_organization_id: index("ix_conversation_organization_id").on(t.organization_id),
    ix_conversation_tenant_id: index("ix_conversation_tenant_id").on(t.tenant_id),
    ix_conversation_user_id: index("ix_conversation_user_id").on(t.user_id),
    ix_conversation_workspace_id: index("ix_conversation_workspace_id").on(t.workspace_id),
    fk_conversation_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agentNS.agent.id] }),
    fk_conversation_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_conversation_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_conversation_3: foreignKey({ columns: [t.user_id], foreignColumns: [identityNS.user.id] }),
    fk_conversation_4: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const message = pgTable("message", {
  id: uuid("id").notNull().primaryKey(),
  conversation_id: uuid("conversation_id").notNull(),
  run_id: uuid("run_id"),
  role: varchar("role", { length: 20 }).notNull(),
  content: text("content").notNull(),
  content_parts: jsonb("content_parts"),
  token_count: integer("token_count"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_message_conversation_id: index("ix_message_conversation_id").on(t.conversation_id),
    ix_message_run_id: index("ix_message_run_id").on(t.run_id),
    fk_message_0: foreignKey({ columns: [t.conversation_id], foreignColumns: [conversation.id] }),
    fk_message_1: foreignKey({ columns: [t.run_id], foreignColumns: [agentNS.agent_run.id] }),
  })
);

export const approval = pgTable("approval", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  subject_type: varchar("subject_type", { length: 20 }).notNull(),
  subject_ref: varchar("subject_ref", { length: 255 }).notNull(),
  requested_by: uuid("requested_by"),
  status: varchar("status", { length: 20 }).notNull(),
  decided_by: uuid("decided_by"),
  decided_at: timestamp("decided_at", { withTimezone: true }),
  payload: jsonb("payload").notNull(),
  expires_at: timestamp("expires_at", { withTimezone: true }),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_approval_tenant_id: index("ix_approval_tenant_id").on(t.tenant_id),
    fk_approval_0: foreignKey({ columns: [t.decided_by], foreignColumns: [identityNS.user.id] }),
    fk_approval_1: foreignKey({ columns: [t.requested_by], foreignColumns: [identityNS.user.id] }),
    fk_approval_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
  })
);

export const sandbox_session = pgTable("sandbox_session", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  run_id: uuid("run_id"),
  workspace_id: uuid("workspace_id"),
  provider: varchar("provider", { length: 50 }).notNull(),
  image: varchar("image", { length: 255 }),
  status: varchar("status", { length: 50 }).notNull(),
  container_ref: varchar("container_ref", { length: 255 }),
  workdir: varchar("workdir", { length: 512 }).notNull(),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  ended_at: timestamp("ended_at", { withTimezone: true }),
}, (t): ExtraConfig => ({
    ix_sandbox_session_run_id: index("ix_sandbox_session_run_id").on(t.run_id),
    ix_sandbox_session_tenant_id: index("ix_sandbox_session_tenant_id").on(t.tenant_id),
    ix_sandbox_session_workspace_id: index("ix_sandbox_session_workspace_id").on(t.workspace_id),
    fk_sandbox_session_0: foreignKey({ columns: [t.run_id], foreignColumns: [agentNS.agent_run.id] }),
    fk_sandbox_session_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_sandbox_session_2: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const mcp_server = pgTable("mcp_server", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  organization_id: uuid("organization_id"),
  workspace_id: uuid("workspace_id"),
  name: varchar("name", { length: 255 }).notNull(),
  transport: varchar("transport", { length: 20 }).notNull(),
  endpoint: varchar("endpoint", { length: 1024 }),
  command: varchar("command", { length: 1024 }),
  args: jsonb("args"),
  env_ref: jsonb("env_ref"),
  credential_id: uuid("credential_id"),
  status: varchar("status", { length: 50 }).notNull(),
  capabilities: jsonb("capabilities"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_mcp_server_credential_id: index("ix_mcp_server_credential_id").on(t.credential_id),
    ix_mcp_server_organization_id: index("ix_mcp_server_organization_id").on(t.organization_id),
    ix_mcp_server_tenant_id: index("ix_mcp_server_tenant_id").on(t.tenant_id),
    ix_mcp_server_workspace_id: index("ix_mcp_server_workspace_id").on(t.workspace_id),
    uq_mcp_server_tenant_name: unique("uq_mcp_server_tenant_name").on(t.tenant_id, t.name),
    fk_mcp_server_0: foreignKey({ columns: [t.credential_id], foreignColumns: [modelNS.credential.id] }),
    fk_mcp_server_1: foreignKey({ columns: [t.organization_id], foreignColumns: [identityNS.organization.id] }),
    fk_mcp_server_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_mcp_server_3: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const mcp_tool = pgTable("mcp_tool", {
  id: uuid("id").notNull().primaryKey(),
  mcp_server_id: uuid("mcp_server_id").notNull(),
  name: varchar("name", { length: 255 }).notNull(),
  description: text("description"),
  input_schema: jsonb("input_schema"),
  output_schema: jsonb("output_schema"),
  discovered_at: timestamp("discovered_at", { withTimezone: true }).notNull().defaultNow(),
  status: varchar("status", { length: 50 }).notNull(),
}, (t): ExtraConfig => ({
    ix_mcp_tool_mcp_server_id: index("ix_mcp_tool_mcp_server_id").on(t.mcp_server_id),
    uq_mcp_tool_server_name: unique("uq_mcp_tool_server_name").on(t.mcp_server_id, t.name),
    fk_mcp_tool_0: foreignKey({ columns: [t.mcp_server_id], foreignColumns: [mcp_server.id] }),
  })
);

export const mcp_permission = pgTable("mcp_permission", {
  id: uuid("id").notNull().primaryKey(),
  tenant_id: uuid("tenant_id").notNull(),
  agent_id: uuid("agent_id"),
  agent_version_id: uuid("agent_version_id"),
  mcp_tool_id: uuid("mcp_tool_id").notNull(),
  action: varchar("action", { length: 50 }).notNull(),
  effect: varchar("effect", { length: 20 }).notNull(),
  scope: jsonb("scope"),
  created_at: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updated_at: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (t): ExtraConfig => ({
    ix_mcp_permission_agent_id: index("ix_mcp_permission_agent_id").on(t.agent_id),
    ix_mcp_permission_agent_version_id: index("ix_mcp_permission_agent_version_id").on(t.agent_version_id),
    ix_mcp_permission_mcp_tool_id: index("ix_mcp_permission_mcp_tool_id").on(t.mcp_tool_id),
    ix_mcp_permission_tenant_id: index("ix_mcp_permission_tenant_id").on(t.tenant_id),
    uq_mcp_permission_tool_agent_action: unique("uq_mcp_permission_tool_agent_action").on(t.mcp_tool_id, t.agent_id, t.action),
    fk_mcp_permission_0: foreignKey({ columns: [t.agent_id], foreignColumns: [agentNS.agent.id] }),
    fk_mcp_permission_1: foreignKey({ columns: [t.agent_version_id], foreignColumns: [agentNS.agent_version.id] }),
    fk_mcp_permission_2: foreignKey({ columns: [t.mcp_tool_id], foreignColumns: [mcp_tool.id] }),
    fk_mcp_permission_3: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
  })
);
