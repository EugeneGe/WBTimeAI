// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。
// SQLite 档汇总：61 张表。

export * from "./identity.js";
export * from "./agent.js";
export * from "./model.js";
export * from "./tool.js";
export * from "./skill.js";
export * from "./knowledge.js";
export * from "./conversation.js";
export * from "./workflow.js";
export * from "./task.js";
export * from "./evaluation.js";
export * from "./audit.js";

import type { Table } from "drizzle-orm";
import * as identityNS from "./identity.js";
import * as agentNS from "./agent.js";
import * as modelNS from "./model.js";
import * as toolNS from "./tool.js";
import * as skillNS from "./skill.js";
import * as knowledgeNS from "./knowledge.js";
import * as conversationNS from "./conversation.js";
import * as workflowNS from "./workflow.js";
import * as taskNS from "./task.js";
import * as evaluationNS from "./evaluation.js";
import * as auditNS from "./audit.js";

/** 该方言下全部表对象（便于按名取用 / drizzle(db, schema)）。 */
export const ALL_SQLITE_TABLES: Record<string, Table> = {
  "agent": agentNS.agent,
  "agent_event": agentNS.agent_event,
  "agent_knowledge": agentNS.agent_knowledge,
  "agent_run": agentNS.agent_run,
  "agent_skill": agentNS.agent_skill,
  "agent_tool": agentNS.agent_tool,
  "agent_version": agentNS.agent_version,
  "approval": conversationNS.approval,
  "audit_log": auditNS.audit_log,
  "conversation": conversationNS.conversation,
  "credential": modelNS.credential,
  "document": knowledgeNS.document,
  "document_chunk": knowledgeNS.document_chunk,
  "embedding": knowledgeNS.embedding,
  "evaluation_case": evaluationNS.evaluation_case,
  "evaluation_dataset": evaluationNS.evaluation_dataset,
  "evaluation_result": evaluationNS.evaluation_result,
  "evaluation_run": evaluationNS.evaluation_run,
  "feature_flag": identityNS.feature_flag,
  "knowledge_base": knowledgeNS.knowledge_base,
  "login_attempt": identityNS.login_attempt,
  "mcp_permission": conversationNS.mcp_permission,
  "mcp_server": conversationNS.mcp_server,
  "mcp_tool": conversationNS.mcp_tool,
  "membership": identityNS.membership,
  "memory": knowledgeNS.memory,
  "memory_relation": knowledgeNS.memory_relation,
  "message": conversationNS.message,
  "model": modelNS.model,
  "model_provider": modelNS.model_provider,
  "model_provider_credential": modelNS.model_provider_credential,
  "organization": identityNS.organization,
  "permission": identityNS.permission,
  "plugin": skillNS.plugin,
  "project": taskNS.project,
  "refresh_token": identityNS.refresh_token,
  "resource_permission": identityNS.resource_permission,
  "role": identityNS.role,
  "role_permission": identityNS.role_permission,
  "sandbox_session": conversationNS.sandbox_session,
  "schedule": taskNS.schedule,
  "session": identityNS.session,
  "skill": skillNS.skill,
  "skill_resource": skillNS.skill_resource,
  "skill_version": skillNS.skill_version,
  "task": taskNS.task,
  "task_execution": taskNS.task_execution,
  "tenant": identityNS.tenant,
  "tool": toolNS.tool,
  "tool_call": toolNS.tool_call,
  "tool_permission": toolNS.tool_permission,
  "tool_version": toolNS.tool_version,
  "user": identityNS.user,
  "workflow": workflowNS.workflow,
  "workflow_edge": workflowNS.workflow_edge,
  "workflow_node": workflowNS.workflow_node,
  "workflow_node_run": workflowNS.workflow_node_run,
  "workflow_run": workflowNS.workflow_run,
  "workflow_version": workflowNS.workflow_version,
  "workspace": identityNS.workspace,
  "workspace_environment": identityNS.workspace_environment,
};

export const SQLITE_TABLE_COUNT = 61;
