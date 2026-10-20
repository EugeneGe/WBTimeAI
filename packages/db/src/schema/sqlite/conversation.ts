// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。
// oracle ①: contracts/schema.v0018.sqlite.normalized.json（schema v0018，结构权威）
// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）
// 领域：conversation · 表数 7

import { foreignKey, index, integer, sqliteTable, text, type ForeignKeyBuilder, type IndexBuilder, type UniqueConstraintBuilder, unique } from "drizzle-orm/sqlite-core";

/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */
type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;
import { sql } from "drizzle-orm";
import * as agentNS from "./agent.js";
import * as identityNS from "./identity.js";
import * as modelNS from "./model.js";

export const conversation = sqliteTable("conversation", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }).notNull(),
  agent_id: text("agent_id", { length: 36 }).notNull(),
  user_id: text("user_id", { length: 36 }).notNull(),
  title: text("title", { length: 255 }).notNull(),
  status: text("status", { length: 50 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const message = sqliteTable("message", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  conversation_id: text("conversation_id", { length: 36 }).notNull(),
  run_id: text("run_id", { length: 36 }),
  role: text("role", { length: 20 }).notNull(),
  content: text("content").notNull(),
  content_parts: text("content_parts", { mode: "json" }),
  token_count: integer("token_count"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_message_conversation_id: index("ix_message_conversation_id").on(t.conversation_id),
    ix_message_run_id: index("ix_message_run_id").on(t.run_id),
    fk_message_0: foreignKey({ columns: [t.conversation_id], foreignColumns: [conversation.id] }),
    fk_message_1: foreignKey({ columns: [t.run_id], foreignColumns: [agentNS.agent_run.id] }),
  })
);

export const approval = sqliteTable("approval", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  subject_type: text("subject_type", { length: 20 }).notNull(),
  subject_ref: text("subject_ref", { length: 255 }).notNull(),
  requested_by: text("requested_by", { length: 36 }),
  status: text("status", { length: 20 }).notNull(),
  decided_by: text("decided_by", { length: 36 }),
  decided_at: text("decided_at"),
  payload: text("payload", { mode: "json" }).notNull(),
  expires_at: text("expires_at"),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
}, (t): ExtraConfig => ({
    ix_approval_tenant_id: index("ix_approval_tenant_id").on(t.tenant_id),
    fk_approval_0: foreignKey({ columns: [t.decided_by], foreignColumns: [identityNS.user.id] }),
    fk_approval_1: foreignKey({ columns: [t.requested_by], foreignColumns: [identityNS.user.id] }),
    fk_approval_2: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
  })
);

export const sandbox_session = sqliteTable("sandbox_session", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  run_id: text("run_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  provider: text("provider", { length: 50 }).notNull(),
  image: text("image", { length: 255 }),
  status: text("status", { length: 50 }).notNull(),
  container_ref: text("container_ref", { length: 255 }),
  workdir: text("workdir", { length: 512 }).notNull(),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  ended_at: text("ended_at"),
}, (t): ExtraConfig => ({
    ix_sandbox_session_run_id: index("ix_sandbox_session_run_id").on(t.run_id),
    ix_sandbox_session_tenant_id: index("ix_sandbox_session_tenant_id").on(t.tenant_id),
    ix_sandbox_session_workspace_id: index("ix_sandbox_session_workspace_id").on(t.workspace_id),
    fk_sandbox_session_0: foreignKey({ columns: [t.run_id], foreignColumns: [agentNS.agent_run.id] }),
    fk_sandbox_session_1: foreignKey({ columns: [t.tenant_id], foreignColumns: [identityNS.tenant.id] }),
    fk_sandbox_session_2: foreignKey({ columns: [t.workspace_id], foreignColumns: [identityNS.workspace.id] }),
  })
);

export const mcp_server = sqliteTable("mcp_server", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  organization_id: text("organization_id", { length: 36 }),
  workspace_id: text("workspace_id", { length: 36 }),
  name: text("name", { length: 255 }).notNull(),
  transport: text("transport", { length: 20 }).notNull(),
  endpoint: text("endpoint", { length: 1024 }),
  command: text("command", { length: 1024 }),
  args: text("args", { mode: "json" }),
  env_ref: text("env_ref", { mode: "json" }),
  credential_id: text("credential_id", { length: 36 }),
  status: text("status", { length: 50 }).notNull(),
  capabilities: text("capabilities", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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

export const mcp_tool = sqliteTable("mcp_tool", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  mcp_server_id: text("mcp_server_id", { length: 36 }).notNull(),
  name: text("name", { length: 255 }).notNull(),
  description: text("description"),
  input_schema: text("input_schema", { mode: "json" }),
  output_schema: text("output_schema", { mode: "json" }),
  discovered_at: text("discovered_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  status: text("status", { length: 50 }).notNull(),
}, (t): ExtraConfig => ({
    ix_mcp_tool_mcp_server_id: index("ix_mcp_tool_mcp_server_id").on(t.mcp_server_id),
    uq_mcp_tool_server_name: unique("uq_mcp_tool_server_name").on(t.mcp_server_id, t.name),
    fk_mcp_tool_0: foreignKey({ columns: [t.mcp_server_id], foreignColumns: [mcp_server.id] }),
  })
);

export const mcp_permission = sqliteTable("mcp_permission", {
  id: text("id", { length: 36 }).notNull().primaryKey(),
  tenant_id: text("tenant_id", { length: 36 }).notNull(),
  agent_id: text("agent_id", { length: 36 }),
  agent_version_id: text("agent_version_id", { length: 36 }),
  mcp_tool_id: text("mcp_tool_id", { length: 36 }).notNull(),
  action: text("action", { length: 50 }).notNull(),
  effect: text("effect", { length: 20 }).notNull(),
  scope: text("scope", { mode: "json" }),
  created_at: text("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  updated_at: text("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`),
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
