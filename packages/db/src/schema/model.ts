// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。
// scripts/gen-ddl.ts 的**唯一输入**：与 pg/ sqlite/ 下的 TS schema 文件由同一次
// 脚本运行产出 ⇒ 「TS schema → DDL」链条内部不可能漂移。

export const SCHEMA_VERSION = "v0019";

export interface ModelColumn {
  name: string;
  pgType: string;
  sqliteType: string;
  nullable: boolean;
  pgDefault: string | null;
  sqliteDefault: string | null;
}

export interface ModelIndex {
  name: string;
  columns: string[];
  unique: boolean;
  where: string | null;
}

export interface ModelUniqueConstraint {
  name: string;
  columns: string[];
}

export interface ModelForeignKey {
  name: string | null;
  columns: string[];
  referredTable: string;
  referredColumns: string[];
  ondelete: string | null;
  onupdate: string | null;
}

export interface ModelTable {
  name: string;
  primaryKey: string[];
  columns: ModelColumn[];
  indexes: ModelIndex[];
  uniqueConstraints: ModelUniqueConstraint[];
  foreignKeys: ModelForeignKey[];
}

export interface ModelRawIndex {
  name: string;
  table: string;
  method: string;
  indexedColumn: string;
  operatorClass: string;
  options: Record<string, string>;
  sql: string;
  source: string;
}

export interface ModelExtension {
  name: string;
  sql: string;
  sources: string[];
}

export interface ModelDialectOnly {
  kind: string;
  name: string;
  table: string;
  sql: string;
  source: string;
}

/** 61 张表的完整结构（表序＝冻结序＝表名字典序）。 */
export const TABLES: readonly ModelTable[] = [
  {
    name: "agent",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "current_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_agent_created_by", columns: ["created_by"], unique: false, where: null },
      { name: "ix_agent_current_version_id", columns: ["current_version_id"], unique: false, where: null },
      { name: "ix_agent_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_agent_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_agent_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: "fk_agent_current_version_id", columns: ["current_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "agent_event",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "seq", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "type", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "payload", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "trace_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "span_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_agent_event_run_id", columns: ["run_id"], unique: false, where: null },
      { name: "ix_agent_event_seq", columns: ["seq"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "agent_knowledge",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "knowledge_base_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "enabled", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "config", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_agent_knowledge_agent_version_id", columns: ["agent_version_id"], unique: false, where: null },
      { name: "ix_agent_knowledge_knowledge_base_id", columns: ["knowledge_base_id"], unique: false, where: null },
      { name: "ix_agent_knowledge_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_agent_knowledge_version_kb", columns: ["agent_version_id","knowledge_base_id"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["knowledge_base_id"], referredTable: "knowledge_base", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "agent_run",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "conversation_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "user_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "task_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "trigger", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "run_mode", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "trace_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "span_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "last_heartbeat_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "idempotency_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "started_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "completed_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "duration_ms", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "token_usage", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "success", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "error_type", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "tool_error_count", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "cost", pgType: "NUMERIC(18, 6)", sqliteType: "NUMERIC(18, 6)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "cost_currency", pgType: "VARCHAR(10)", sqliteType: "VARCHAR(10)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "cost_price_version", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "cost_estimated", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "cost_breakdown", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "cost_status", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "error", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "stop_reason", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: true, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_agent_run_agent_id", columns: ["agent_id"], unique: false, where: null },
      { name: "ix_agent_run_agent_version_id", columns: ["agent_version_id"], unique: false, where: null },
      { name: "ix_agent_run_conversation_id", columns: ["conversation_id"], unique: false, where: null },
      { name: "ix_agent_run_status", columns: ["status"], unique: false, where: null },
      { name: "ix_agent_run_task_id", columns: ["task_id"], unique: false, where: null },
      { name: "ix_agent_run_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_agent_run_trace_id", columns: ["trace_id"], unique: false, where: null },
      { name: "ix_agent_run_user_id", columns: ["user_id"], unique: false, where: null },
      { name: "uq_agent_run_tenant_idempotency_key", columns: ["tenant_id","idempotency_key"], unique: true, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["agent_id"], referredTable: "agent", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["agent_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["conversation_id"], referredTable: "conversation", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["task_id"], referredTable: "task", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["user_id"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "agent_skill",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "skill_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "enabled", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "config", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_agent_skill_agent_version_id", columns: ["agent_version_id"], unique: false, where: null },
      { name: "ix_agent_skill_skill_id", columns: ["skill_id"], unique: false, where: null },
      { name: "ix_agent_skill_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_agent_skill_version_skill", columns: ["agent_version_id","skill_id"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["skill_id"], referredTable: "skill", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "agent_tool",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tool_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "enabled", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "permission_scope", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_agent_tool_agent_version_id", columns: ["agent_version_id"], unique: false, where: null },
      { name: "ix_agent_tool_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_agent_tool_tool_id", columns: ["tool_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_agent_tool_version_tool", columns: ["agent_version_id","tool_id"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tool_id"], referredTable: "tool", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "agent_version",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "version", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "system_prompt", pgType: "TEXT", sqliteType: "TEXT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "model_config", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "runtime_config", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_agent_version_agent_id", columns: ["agent_id"], unique: false, where: null },
      { name: "ix_agent_version_created_by", columns: ["created_by"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["agent_id"], referredTable: "agent", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "approval",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "subject_type", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "subject_ref", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "requested_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "decided_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "decided_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "payload", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "expires_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_approval_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["decided_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["requested_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "audit_log",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "user_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "agent_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "tool_call_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "action", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "resource_type", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "resource_id", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "outcome", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "duration_ms", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "token_usage", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "cost", pgType: "NUMERIC(18, 6)", sqliteType: "NUMERIC(18, 6)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "request_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "trace_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "ip", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "metadata", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "extensions", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_audit_log_action", columns: ["action"], unique: false, where: null },
      { name: "ix_audit_log_request_id", columns: ["request_id"], unique: false, where: null },
      { name: "ix_audit_log_run_id", columns: ["run_id"], unique: false, where: null },
      { name: "ix_audit_log_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["agent_id"], referredTable: "agent", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tool_call_id"], referredTable: "tool_call", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["user_id"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "conversation",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "user_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "title", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_conversation_agent_id", columns: ["agent_id"], unique: false, where: null },
      { name: "ix_conversation_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_conversation_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_conversation_user_id", columns: ["user_id"], unique: false, where: null },
      { name: "ix_conversation_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["agent_id"], referredTable: "agent", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["user_id"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "credential",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "provider", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "key_type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "encrypted_value", pgType: "TEXT", sqliteType: "TEXT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(150)", sqliteType: "VARCHAR(150)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "last_used_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "metadata", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_credential_name", columns: ["name"], unique: false, where: null },
      { name: "ix_credential_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_credential_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_credential_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "document",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "knowledge_base_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "title", pgType: "VARCHAR(512)", sqliteType: "VARCHAR(512)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "source_type", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "storage_key", pgType: "VARCHAR(1024)", sqliteType: "VARCHAR(1024)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "mime", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "size", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "checksum", pgType: "VARCHAR(128)", sqliteType: "VARCHAR(128)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "error", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "task_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_document_knowledge_base_id", columns: ["knowledge_base_id"], unique: false, where: null },
      { name: "ix_document_status", columns: ["status"], unique: false, where: null },
      { name: "ix_document_task_id", columns: ["task_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["knowledge_base_id"], referredTable: "knowledge_base", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["task_id"], referredTable: "task", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "document_chunk",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "document_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "ordinal", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "content", pgType: "TEXT", sqliteType: "TEXT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "token_count", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "metadata", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "embedding_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_document_chunk_document_id", columns: ["document_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_document_chunk_document_ordinal", columns: ["document_id","ordinal"] },
    ],
    foreignKeys: [
      { name: null, columns: ["document_id"], referredTable: "document", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "embedding",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "chunk_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "model", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "dimensions", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "vector", pgType: "VECTOR(1536)", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_embedding_chunk_id", columns: ["chunk_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_embedding_chunk_id", columns: ["chunk_id"] },
    ],
    foreignKeys: [
      { name: null, columns: ["chunk_id"], referredTable: "document_chunk", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "evaluation_case",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "dataset_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "case_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "input", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "expected", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "assertions", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "tags", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "position", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_evaluation_case_dataset_id", columns: ["dataset_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_evaluation_case_dataset_case_key", columns: ["dataset_id","case_key"] },
    ],
    foreignKeys: [
      { name: null, columns: ["dataset_id"], referredTable: "evaluation_dataset", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "evaluation_dataset",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "version", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "parent_dataset_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "VARCHAR(1024)", sqliteType: "VARCHAR(1024)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_evaluation_dataset_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_evaluation_dataset_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_evaluation_dataset_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["parent_dataset_id"], referredTable: "evaluation_dataset", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "evaluation_result",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "evaluation_run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "case_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "score", pgType: "FLOAT", sqliteType: "FLOAT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "assertion_results", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "duration_ms", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "token_usage", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "cost", pgType: "FLOAT", sqliteType: "FLOAT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "error_type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_evaluation_result_agent_run_id", columns: ["agent_run_id"], unique: false, where: null },
      { name: "ix_evaluation_result_case_id", columns: ["case_id"], unique: false, where: null },
      { name: "ix_evaluation_result_evaluation_run_id", columns: ["evaluation_run_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_evaluation_result_run_case", columns: ["evaluation_run_id","case_id"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["case_id"], referredTable: "evaluation_case", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["evaluation_run_id"], referredTable: "evaluation_run", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "evaluation_run",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "dataset_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "idempotency_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "started_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "completed_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "summary", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_evaluation_run_agent_id", columns: ["agent_id"], unique: false, where: null },
      { name: "ix_evaluation_run_agent_version_id", columns: ["agent_version_id"], unique: false, where: null },
      { name: "ix_evaluation_run_dataset_id", columns: ["dataset_id"], unique: false, where: null },
      { name: "ix_evaluation_run_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_evaluation_run_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_evaluation_run_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_evaluation_run_idempotency_key", columns: ["idempotency_key"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_id"], referredTable: "agent", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["agent_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["dataset_id"], referredTable: "evaluation_dataset", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "feature_flag",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(150)", sqliteType: "VARCHAR(150)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "enabled", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_feature_flag_name", columns: ["name"], unique: true, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
    ],
  },
  {
    name: "knowledge_base",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "embedding_model", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "chunk_config", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_knowledge_base_created_by", columns: ["created_by"], unique: false, where: null },
      { name: "ix_knowledge_base_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_knowledge_base_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_knowledge_base_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_knowledge_base_tenant_name", columns: ["tenant_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "login_attempt",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "username", pgType: "VARCHAR(150)", sqliteType: "VARCHAR(150)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "ip_address", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "success", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_login_attempt_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_login_attempt_username", columns: ["username"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "mcp_permission",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "agent_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "mcp_tool_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "action", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "effect", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "scope", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_mcp_permission_agent_id", columns: ["agent_id"], unique: false, where: null },
      { name: "ix_mcp_permission_agent_version_id", columns: ["agent_version_id"], unique: false, where: null },
      { name: "ix_mcp_permission_mcp_tool_id", columns: ["mcp_tool_id"], unique: false, where: null },
      { name: "ix_mcp_permission_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_mcp_permission_tool_agent_action", columns: ["mcp_tool_id","agent_id","action"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_id"], referredTable: "agent", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["agent_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["mcp_tool_id"], referredTable: "mcp_tool", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "mcp_server",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "transport", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "endpoint", pgType: "VARCHAR(1024)", sqliteType: "VARCHAR(1024)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "command", pgType: "VARCHAR(1024)", sqliteType: "VARCHAR(1024)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "args", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "env_ref", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "credential_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "capabilities", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_mcp_server_credential_id", columns: ["credential_id"], unique: false, where: null },
      { name: "ix_mcp_server_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_mcp_server_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_mcp_server_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_mcp_server_tenant_name", columns: ["tenant_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["credential_id"], referredTable: "credential", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "mcp_tool",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "mcp_server_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "input_schema", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "output_schema", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "discovered_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_mcp_tool_mcp_server_id", columns: ["mcp_server_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_mcp_tool_server_name", columns: ["mcp_server_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["mcp_server_id"], referredTable: "mcp_server", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "membership",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "user_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "role_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_membership_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_membership_role_id", columns: ["role_id"], unique: false, where: null },
      { name: "ix_membership_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_membership_user_id", columns: ["user_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["role_id"], referredTable: "role", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["user_id"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "memory",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "kind", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "scope_type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "scope_id", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "visibility", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "content", pgType: "TEXT", sqliteType: "TEXT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "memory_type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "importance", pgType: "FLOAT", sqliteType: "FLOAT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "confidence", pgType: "FLOAT", sqliteType: "FLOAT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "source_run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "vector", pgType: "VECTOR(1536)", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "expires_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_memory_expires_at", columns: ["expires_at"], unique: false, where: null },
      { name: "ix_memory_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_memory_source_run_id", columns: ["source_run_id"], unique: false, where: null },
      { name: "ix_memory_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_memory_tenant_scope_kind", columns: ["tenant_id","scope_type","scope_id","kind"], unique: false, where: null },
      { name: "ix_memory_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["source_run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "memory_relation",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "from_memory_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "to_memory_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "relation", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_memory_relation_from_memory_id", columns: ["from_memory_id"], unique: false, where: null },
      { name: "ix_memory_relation_to_memory_id", columns: ["to_memory_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_memory_relation_from_to_relation", columns: ["from_memory_id","to_memory_id","relation"] },
    ],
    foreignKeys: [
      { name: null, columns: ["from_memory_id"], referredTable: "memory", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["to_memory_id"], referredTable: "memory", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "message",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "conversation_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "role", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "content", pgType: "TEXT", sqliteType: "TEXT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "content_parts", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "token_count", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_message_conversation_id", columns: ["conversation_id"], unique: false, where: null },
      { name: "ix_message_run_id", columns: ["run_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["conversation_id"], referredTable: "conversation", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "model",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "provider_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "context_window", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "capabilities", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_model_provider_id", columns: ["provider_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["provider_id"], referredTable: "model_provider", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "model_provider",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "endpoint", pgType: "VARCHAR(512)", sqliteType: "VARCHAR(512)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "credential_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "config", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_model_provider_credential_id", columns: ["credential_id"], unique: false, where: null },
      { name: "ix_model_provider_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_model_provider_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_model_provider_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["credential_id"], referredTable: "credential", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "model_provider_credential",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "provider_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "credential_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "weight", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_model_provider_credential_credential_id", columns: ["credential_id"], unique: false, where: null },
      { name: "ix_model_provider_credential_provider_id", columns: ["provider_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_model_provider_credential", columns: ["provider_id","credential_id"] },
    ],
    foreignKeys: [
      { name: null, columns: ["credential_id"], referredTable: "credential", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["provider_id"], referredTable: "model_provider", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "organization",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "slug", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_organization_slug", columns: ["slug"], unique: false, where: null },
      { name: "ix_organization_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "permission",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "code", pgType: "VARCHAR(150)", sqliteType: "VARCHAR(150)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(150)", sqliteType: "VARCHAR(150)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_permission_code", columns: ["code"], unique: true, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
    ],
  },
  {
    name: "plugin",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(150)", sqliteType: "VARCHAR(150)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "version", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "kind", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "entry_point", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "permissions", pgType: "JSON", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "manifest", pgType: "JSON", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "installed_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_plugin_name", columns: ["name"], unique: true, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
    ],
  },
  {
    name: "project",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "VARCHAR(1024)", sqliteType: "VARCHAR(1024)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "repo_url", pgType: "VARCHAR(2048)", sqliteType: "VARCHAR(2048)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "default_branch", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "settings", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_project_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_project_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_project_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "refresh_token",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "user_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "session_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "token_hash", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "expires_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "revoked_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_refresh_token_session_id", columns: ["session_id"], unique: false, where: null },
      { name: "ix_refresh_token_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_refresh_token_token_hash", columns: ["token_hash"], unique: false, where: null },
      { name: "ix_refresh_token_user_id", columns: ["user_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["session_id"], referredTable: "session", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["user_id"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "resource_permission",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "subject_type", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "subject_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "resource_type", pgType: "VARCHAR(30)", sqliteType: "VARCHAR(30)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "resource_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "action", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "effect", pgType: "VARCHAR(10)", sqliteType: "VARCHAR(10)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "scope", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_resource_permission_resource", columns: ["tenant_id","resource_type","resource_id"], unique: false, where: null },
      { name: "ix_resource_permission_subject", columns: ["tenant_id","subject_type","subject_id"], unique: false, where: null },
      { name: "ix_resource_permission_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_resource_permission_subject_resource_action", columns: ["tenant_id","subject_type","subject_id","resource_type","resource_id","action"] },
    ],
    foreignKeys: [
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "role",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "is_system", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_role_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_role_tenant_name", columns: ["tenant_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "role_permission",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "role_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "permission_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_role_permission_permission_id", columns: ["permission_id"], unique: false, where: null },
      { name: "ix_role_permission_role_id", columns: ["role_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_role_permission", columns: ["role_id","permission_id"] },
    ],
    foreignKeys: [
      { name: null, columns: ["permission_id"], referredTable: "permission", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["role_id"], referredTable: "role", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "sandbox_session",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "provider", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "image", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "container_ref", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workdir", pgType: "VARCHAR(512)", sqliteType: "VARCHAR(512)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "ended_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_sandbox_session_run_id", columns: ["run_id"], unique: false, where: null },
      { name: "ix_sandbox_session_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_sandbox_session_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "schedule",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "target_type", pgType: "VARCHAR(30)", sqliteType: "VARCHAR(30)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "target_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "trigger", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "cron", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "event_type", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "payload", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "enabled", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "last_run_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "next_run_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_schedule_next_run_at", columns: ["next_run_at"], unique: false, where: null },
      { name: "ix_schedule_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_schedule_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_schedule_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_schedule_target_name", columns: ["tenant_id","target_type","target_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "session",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "user_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "device", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "ip_address", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "user_agent", pgType: "VARCHAR(512)", sqliteType: "VARCHAR(512)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "expires_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "revoked_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_session_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_session_user_id", columns: ["user_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["user_id"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "skill",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "display_name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "category", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "current_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_skill_created_by", columns: ["created_by"], unique: false, where: null },
      { name: "ix_skill_current_version_id", columns: ["current_version_id"], unique: false, where: null },
      { name: "ix_skill_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_skill_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_skill_tenant_name", columns: ["tenant_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: "fk_skill_current_version_id", columns: ["current_version_id"], referredTable: "skill_version", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "skill_resource",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "skill_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "path", pgType: "VARCHAR(1024)", sqliteType: "VARCHAR(1024)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "kind", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "storage_key", pgType: "VARCHAR(1024)", sqliteType: "VARCHAR(1024)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "checksum", pgType: "VARCHAR(128)", sqliteType: "VARCHAR(128)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "size", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_skill_resource_skill_version_id", columns: ["skill_version_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["skill_version_id"], referredTable: "skill_version", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "skill_version",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "skill_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "version", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "instructions", pgType: "TEXT", sqliteType: "TEXT", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "manifest", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_skill_version_created_by", columns: ["created_by"], unique: false, where: null },
      { name: "ix_skill_version_skill_id", columns: ["skill_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_skill_version_skill_version", columns: ["skill_id","version"] },
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["skill_id"], referredTable: "skill", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "task",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "type", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "priority", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "execution_mode", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "payload", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "result", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "idempotency_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_task_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_task_status", columns: ["status"], unique: false, where: null },
      { name: "ix_task_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_task_workspace_id", columns: ["workspace_id"], unique: false, where: null },
      { name: "uq_task_idempotency_key", columns: ["idempotency_key"], unique: true, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "task_execution",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "task_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "attempt", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "worker_id", pgType: "VARCHAR(128)", sqliteType: "VARCHAR(128)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "started_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "finished_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "duration_ms", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "error", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "project_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "checkout_ref", pgType: "VARCHAR(128)", sqliteType: "VARCHAR(128)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "base_commit", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "result_commit", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "environment_digest", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "artifact_refs", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "heartbeat_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "lease_expires_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_task_execution_project_started", columns: ["project_id","started_at"], unique: false, where: null },
      { name: "ix_task_execution_task_id", columns: ["task_id"], unique: false, where: null },
      { name: "uq_task_execution_checkout_ref", columns: ["checkout_ref"], unique: true, where: "checkout_ref IS NOT NULL" },
    ],
    uniqueConstraints: [
      { name: "uq_task_execution_task_attempt", columns: ["task_id","attempt"] },
    ],
    foreignKeys: [
      { name: null, columns: ["task_id"], referredTable: "task", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: "fk_task_execution_project_id", columns: ["project_id"], referredTable: "project", referredColumns: ["id"], ondelete: "RESTRICT", onupdate: null },
    ],
  },
  {
    name: "tenant",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "slug", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "is_active", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_tenant_slug", columns: ["slug"], unique: true, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
    ],
  },
  {
    name: "tool",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "display_name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "category", pgType: "VARCHAR(100)", sqliteType: "VARCHAR(100)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "source", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "input_schema", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "output_schema", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "requires_sandbox", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tool_ref", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
    ],
    indexes: [
      { name: "ix_tool_name", columns: ["name"], unique: false, where: null },
      { name: "ix_tool_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_tool_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "tool_call",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tool_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "tool_name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tool_type", pgType: "VARCHAR(30)", sqliteType: "VARCHAR(30)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tool_ref", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "attempt", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "trace_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "span_id", pgType: "VARCHAR(64)", sqliteType: "VARCHAR(64)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "input", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "output", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "duration_ms", pgType: "INTEGER", sqliteType: "INTEGER", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "sandbox_session_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "error", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_tool_call_run_id", columns: ["run_id"], unique: false, where: null },
      { name: "ix_tool_call_sandbox_session_id", columns: ["sandbox_session_id"], unique: false, where: null },
      { name: "ix_tool_call_status", columns: ["status"], unique: false, where: null },
      { name: "ix_tool_call_tool_id", columns: ["tool_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["sandbox_session_id"], referredTable: "sandbox_session", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tool_id"], referredTable: "tool", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "tool_permission",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "agent_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "tool_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "action", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "effect", pgType: "VARCHAR(20)", sqliteType: "VARCHAR(20)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "scope", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_tool_permission_agent_id", columns: ["agent_id"], unique: false, where: null },
      { name: "ix_tool_permission_agent_version_id", columns: ["agent_version_id"], unique: false, where: null },
      { name: "ix_tool_permission_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_tool_permission_tool_id", columns: ["tool_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_tool_permission_agent_tool_action", columns: ["agent_id","tool_id","action"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_id"], referredTable: "agent", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["agent_version_id"], referredTable: "agent_version", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tool_id"], referredTable: "tool", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "tool_version",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tool_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "version", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "spec", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_tool_version_tool_id", columns: ["tool_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["tool_id"], referredTable: "tool", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "user",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "username", pgType: "VARCHAR(150)", sqliteType: "VARCHAR(150)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "email", pgType: "VARCHAR(320)", sqliteType: "VARCHAR(320)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "password_hash", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "display_name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "is_active", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "is_superuser", pgType: "BOOLEAN", sqliteType: "BOOLEAN", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_user_email", columns: ["email"], unique: false, where: null },
      { name: "ix_user_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_user_username", columns: ["username"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_user_tenant_email", columns: ["tenant_id","email"] },
    ],
    foreignKeys: [
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workflow",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "description", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "current_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workflow_created_by", columns: ["created_by"], unique: false, where: null },
      { name: "ix_workflow_current_version_id", columns: ["current_version_id"], unique: false, where: null },
      { name: "ix_workflow_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_workflow_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_workflow_tenant_name", columns: ["tenant_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: "fk_workflow_current_version_id", columns: ["current_version_id"], referredTable: "workflow_version", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workflow_edge",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "workflow_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "from_node_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "to_node_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "condition", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workflow_edge_workflow_version_id", columns: ["workflow_version_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_workflow_edge_version_from_to", columns: ["workflow_version_id","from_node_key","to_node_key"] },
    ],
    foreignKeys: [
      { name: null, columns: ["workflow_version_id"], referredTable: "workflow_version", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workflow_node",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "workflow_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "node_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "config", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "position", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workflow_node_workflow_version_id", columns: ["workflow_version_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_workflow_node_version_node_key", columns: ["workflow_version_id","node_key"] },
    ],
    foreignKeys: [
      { name: null, columns: ["workflow_version_id"], referredTable: "workflow_version", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workflow_node_run",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "workflow_run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "node_key", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "attempt", pgType: "INTEGER", sqliteType: "INTEGER", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "agent_run_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "tool_call_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "approval_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "input", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "output", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "started_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "completed_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workflow_node_run_agent_run_id", columns: ["agent_run_id"], unique: false, where: null },
      { name: "ix_workflow_node_run_approval_id", columns: ["approval_id"], unique: false, where: null },
      { name: "ix_workflow_node_run_workflow_run_id", columns: ["workflow_run_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_workflow_node_run_run_key_attempt", columns: ["workflow_run_id","node_key","attempt"] },
    ],
    foreignKeys: [
      { name: null, columns: ["agent_run_id"], referredTable: "agent_run", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["approval_id"], referredTable: "approval", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tool_call_id"], referredTable: "tool_call", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workflow_run_id"], referredTable: "workflow_run", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workflow_run",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "workflow_version_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "trigger", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "task_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "input", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "output", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "started_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "completed_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "error", pgType: "TEXT", sqliteType: "TEXT", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workflow_run_status", columns: ["status"], unique: false, where: null },
      { name: "ix_workflow_run_task_id", columns: ["task_id"], unique: false, where: null },
      { name: "ix_workflow_run_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_workflow_run_workflow_version_id", columns: ["workflow_version_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["task_id"], referredTable: "task", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workflow_version_id"], referredTable: "workflow_version", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workflow_version",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "workflow_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "version", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "definition", pgType: "JSONB", sqliteType: "JSON", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "status", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_by", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workflow_version_created_by", columns: ["created_by"], unique: false, where: null },
      { name: "ix_workflow_version_workflow_id", columns: ["workflow_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_workflow_version_workflow_version", columns: ["workflow_id","version"] },
    ],
    foreignKeys: [
      { name: null, columns: ["created_by"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workflow_id"], referredTable: "workflow", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workspace",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "owner_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(255)", sqliteType: "VARCHAR(255)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "workspace_type", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "settings", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "config", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workspace_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_workspace_owner_id", columns: ["owner_id"], unique: false, where: null },
      { name: "ix_workspace_tenant_id", columns: ["tenant_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["owner_id"], referredTable: "user", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
  {
    name: "workspace_environment",
    primaryKey: ["id"],
    columns: [
      { name: "id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "tenant_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "organization_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "workspace_id", pgType: "UUID", sqliteType: "CHAR(36)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "name", pgType: "VARCHAR(50)", sqliteType: "VARCHAR(50)", nullable: false, pgDefault: null, sqliteDefault: null },
      { name: "env_vars", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "runtime", pgType: "JSONB", sqliteType: "JSON", nullable: true, pgDefault: null, sqliteDefault: null },
      { name: "created_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
      { name: "updated_at", pgType: "TIMESTAMP WITH TIME ZONE", sqliteType: "DATETIME", nullable: false, pgDefault: "now()", sqliteDefault: "CURRENT_TIMESTAMP" },
    ],
    indexes: [
      { name: "ix_workspace_environment_organization_id", columns: ["organization_id"], unique: false, where: null },
      { name: "ix_workspace_environment_tenant_id", columns: ["tenant_id"], unique: false, where: null },
      { name: "ix_workspace_environment_workspace_id", columns: ["workspace_id"], unique: false, where: null },
    ],
    uniqueConstraints: [
      { name: "uq_workspace_environment_ws_name", columns: ["workspace_id","name"] },
    ],
    foreignKeys: [
      { name: null, columns: ["organization_id"], referredTable: "organization", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["tenant_id"], referredTable: "tenant", referredColumns: ["id"], ondelete: null, onupdate: null },
      { name: null, columns: ["workspace_id"], referredTable: "workspace", referredColumns: ["id"], ondelete: null, onupdate: null },
    ],
  },
];

/** PG raw 索引（源②：迁移链 raw DDL）—— **ORM 编译不出来**，必须显式搬运。 */
export const PG_RAW_INDEXES: readonly ModelRawIndex[] = [
  {
    name: "ix_embedding_vector_hnsw",
    table: "embedding",
    method: "hnsw",
    indexedColumn: "vector",
    operatorClass: "vector_cosine_ops",
    options: {"m":"16","ef_construction":"64"},
    sql: "CREATE INDEX ix_embedding_vector_hnsw ON embedding USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64);",
    source: "migration:migrations/versions/0013_phase2_knowledge.py:293",
  },
  {
    name: "ix_memory_vector_hnsw",
    table: "memory",
    method: "hnsw",
    indexedColumn: "vector",
    operatorClass: "vector_cosine_ops",
    options: {"m":"16","ef_construction":"64"},
    sql: "CREATE INDEX ix_memory_vector_hnsw ON memory USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64);",
    source: "migration:migrations/versions/0014_phase2_memory.py:195",
  },
];

/** PG 扩展（源②：迁移 0013/0014 各写一次同一条幂等语句，此处保留一条）。 */
export const PG_EXTENSIONS: readonly ModelExtension[] = [
  {
    name: "vector",
    sql: "CREATE EXTENSION IF NOT EXISTS vector;",
    sources: ["migration:migrations/versions/0013_phase2_knowledge.py:104","migration:migrations/versions/0014_phase2_memory.py:95"],
  },
];

/** SQLite 专属对象（源③）：FTS5 虚表 1 + 影子表 4 + 同步触发器 3 = 8。 */
export const SQLITE_DIALECT_ONLY: readonly ModelDialectOnly[] = [
  {
    kind: "virtual_table",
    name: "document_chunk_fts",
    table: "document_chunk_fts",
    sql: "CREATE VIRTUAL TABLE document_chunk_fts USING fts5(content, content='document_chunk', content_rowid='rowid');",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
  {
    kind: "shadow_table",
    name: "document_chunk_fts_config",
    table: "document_chunk_fts_config",
    sql: "CREATE TABLE 'document_chunk_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
  {
    kind: "shadow_table",
    name: "document_chunk_fts_data",
    table: "document_chunk_fts_data",
    sql: "CREATE TABLE 'document_chunk_fts_data'(id INTEGER PRIMARY KEY, block BLOB);",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
  {
    kind: "shadow_table",
    name: "document_chunk_fts_docsize",
    table: "document_chunk_fts_docsize",
    sql: "CREATE TABLE 'document_chunk_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
  {
    kind: "shadow_table",
    name: "document_chunk_fts_idx",
    table: "document_chunk_fts_idx",
    sql: "CREATE TABLE 'document_chunk_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
  {
    kind: "trigger",
    name: "document_chunk_ad",
    table: "document_chunk",
    sql: "CREATE TRIGGER document_chunk_ad AFTER DELETE ON document_chunk BEGIN INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) VALUES ('delete', old.rowid, old.content); END;",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
  {
    kind: "trigger",
    name: "document_chunk_ai",
    table: "document_chunk",
    sql: "CREATE TRIGGER document_chunk_ai AFTER INSERT ON document_chunk BEGIN INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END;",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
  {
    kind: "trigger",
    name: "document_chunk_au",
    table: "document_chunk",
    sql: "CREATE TRIGGER document_chunk_au AFTER UPDATE ON document_chunk BEGIN INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) VALUES ('delete', old.rowid, old.content); INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END;",
    source: "sqlite_master（执行 0013 FTS5 语句后回读）",
  },
];

/** 实跑计数（由生成器输出，**禁止手填**）。 */
export const GENERATED_COUNTS = {"tables":61,"columns":630,"metadataIndexes":174,"uniqueIndexes":7,"partialIndexes":1,"uniqueConstraints":29,"foreignKeys":159,"namedForeignKeys":4,"primaryKeys":61,"rawIndexes":2,"hnswIndexes":2,"extensions":1,"sqliteDialectOnlyObjects":8,"sqliteVirtualTables":1,"sqliteShadowTables":4,"sqliteTriggers":3,"domainGroups":11};

/** PG/SQLite 两侧的索引对象合计（PG = metadata + raw hnsw 2）。 */
export const INDEX_OBJECTS_TOTAL = {"pg":176,"sqlite":174};
