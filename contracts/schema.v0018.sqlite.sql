-- ==============================================================================
-- WBTimeAI DDL 冻结面 · SQLite（schema v0018）
-- ==============================================================================
-- 契约版本：schema_version = v0018（对应迁移链 0018 收敛态）
-- 方言：sqlite
-- 生成者：scripts/extract-from-py/ddl/export_ddl.py（禁止手改；数字由脚本实跑得出）
--
-- 三源构成（缺一源即冻结面失真，路线图 §3.3.1 / M-02）：
--   源① ORM metadata 编译：61 表 / 629 列 / 174 索引（unique 7 / partial 1）
--   源② 迁移链 raw DDL：0 个（hnsw 为 PG 专属，SQLite 侧不存在——合法差异）
--   源③ SQLite 专属（共 8 个对象，PG DDL 里 0 处）：FTS5 虚表 ×1 + 影子表 ×4 + 同步触发器 ×3
--        触发器不是装饰对象：external content 模式下缺 ai/ad/au，FTS 索引不随基表更新，全文检索静默失真
--
-- 🔴 hnsw 系 PG 专属（pgvector USING hnsw），SQLite 侧**不存在**——合法的 dialect_only: pg 差异，不是遗漏；PG 侧对应对象见 schema.v0018.pg.sql 第 4 段
-- 段落顺序：1) 表 + 所属索引（按表名排序）→ 2) FTS5 虚表 → 3) 影子表 → 4) 同步触发器
-- 影子表定义取自 sqlite_master（SQLite 内部生成，源文件无 DDL），故为权威文本
-- ==============================================================================

-- ===== 1. 表与所属索引（源①：ORM metadata 编译，按表名排序）=====
CREATE TABLE agent (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	type VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	current_version_id CHAR(36), 
	created_by CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	CONSTRAINT fk_agent_current_version_id FOREIGN KEY(current_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_agent_created_by ON agent (created_by);
CREATE INDEX ix_agent_current_version_id ON agent (current_version_id);
CREATE INDEX ix_agent_organization_id ON agent (organization_id);
CREATE INDEX ix_agent_tenant_id ON agent (tenant_id);
CREATE INDEX ix_agent_workspace_id ON agent (workspace_id);
CREATE TABLE agent_event (
	id CHAR(36) NOT NULL, 
	run_id CHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	type VARCHAR(100) NOT NULL, 
	payload JSON, 
	trace_id VARCHAR(64), 
	span_id VARCHAR(64), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES agent_run (id)
);
CREATE INDEX ix_agent_event_run_id ON agent_event (run_id);
CREATE INDEX ix_agent_event_seq ON agent_event (seq);
CREATE TABLE agent_knowledge (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	agent_version_id CHAR(36) NOT NULL, 
	knowledge_base_id CHAR(36) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	config JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_agent_knowledge_version_kb UNIQUE (agent_version_id, knowledge_base_id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(agent_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_base (id)
);
CREATE INDEX ix_agent_knowledge_agent_version_id ON agent_knowledge (agent_version_id);
CREATE INDEX ix_agent_knowledge_knowledge_base_id ON agent_knowledge (knowledge_base_id);
CREATE INDEX ix_agent_knowledge_tenant_id ON agent_knowledge (tenant_id);
CREATE TABLE agent_run (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	agent_id CHAR(36) NOT NULL, 
	agent_version_id CHAR(36) NOT NULL, 
	conversation_id CHAR(36) NOT NULL, 
	user_id CHAR(36), 
	task_id CHAR(36), 
	"trigger" VARCHAR(50) NOT NULL, 
	run_mode VARCHAR(20) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	trace_id VARCHAR(64), 
	span_id VARCHAR(64), 
	last_heartbeat_at DATETIME, 
	idempotency_key VARCHAR(255), 
	started_at DATETIME, 
	completed_at DATETIME, 
	duration_ms INTEGER, 
	token_usage JSON, 
	success BOOLEAN, 
	error_type VARCHAR(100), 
	tool_error_count INTEGER NOT NULL, 
	cost NUMERIC(18, 6), 
	cost_currency VARCHAR(10), 
	cost_price_version VARCHAR(50), 
	cost_estimated BOOLEAN NOT NULL, 
	cost_breakdown JSON, 
	cost_status VARCHAR(20) NOT NULL, 
	error TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(agent_id) REFERENCES agent (id), 
	FOREIGN KEY(agent_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversation (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	FOREIGN KEY(task_id) REFERENCES task (id)
);
CREATE INDEX ix_agent_run_agent_id ON agent_run (agent_id);
CREATE INDEX ix_agent_run_agent_version_id ON agent_run (agent_version_id);
CREATE INDEX ix_agent_run_conversation_id ON agent_run (conversation_id);
CREATE INDEX ix_agent_run_status ON agent_run (status);
CREATE INDEX ix_agent_run_task_id ON agent_run (task_id);
CREATE INDEX ix_agent_run_tenant_id ON agent_run (tenant_id);
CREATE INDEX ix_agent_run_trace_id ON agent_run (trace_id);
CREATE INDEX ix_agent_run_user_id ON agent_run (user_id);
CREATE UNIQUE INDEX uq_agent_run_tenant_idempotency_key ON agent_run (tenant_id, idempotency_key);
CREATE TABLE agent_skill (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	agent_version_id CHAR(36) NOT NULL, 
	skill_id CHAR(36) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	config JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_agent_skill_version_skill UNIQUE (agent_version_id, skill_id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(agent_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(skill_id) REFERENCES skill (id)
);
CREATE INDEX ix_agent_skill_agent_version_id ON agent_skill (agent_version_id);
CREATE INDEX ix_agent_skill_skill_id ON agent_skill (skill_id);
CREATE INDEX ix_agent_skill_tenant_id ON agent_skill (tenant_id);
CREATE TABLE agent_tool (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	agent_version_id CHAR(36) NOT NULL, 
	tool_id CHAR(36) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	permission_scope JSON, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_agent_tool_version_tool UNIQUE (agent_version_id, tool_id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(agent_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(tool_id) REFERENCES tool (id)
);
CREATE INDEX ix_agent_tool_agent_version_id ON agent_tool (agent_version_id);
CREATE INDEX ix_agent_tool_tenant_id ON agent_tool (tenant_id);
CREATE INDEX ix_agent_tool_tool_id ON agent_tool (tool_id);
CREATE TABLE agent_version (
	id CHAR(36) NOT NULL, 
	agent_id CHAR(36) NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	system_prompt TEXT NOT NULL, 
	model_config JSON NOT NULL, 
	runtime_config JSON NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(agent_id) REFERENCES agent (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_agent_version_agent_id ON agent_version (agent_id);
CREATE INDEX ix_agent_version_created_by ON agent_version (created_by);
CREATE TABLE approval (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	subject_type VARCHAR(20) NOT NULL, 
	subject_ref VARCHAR(255) NOT NULL, 
	requested_by CHAR(36), 
	status VARCHAR(20) NOT NULL, 
	decided_by CHAR(36), 
	decided_at DATETIME, 
	payload JSON NOT NULL, 
	expires_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(requested_by) REFERENCES user (id), 
	FOREIGN KEY(decided_by) REFERENCES user (id)
);
CREATE INDEX ix_approval_tenant_id ON approval (tenant_id);
CREATE TABLE audit_log (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	user_id CHAR(36), 
	agent_id CHAR(36), 
	run_id CHAR(36), 
	tool_call_id CHAR(36), 
	action VARCHAR(100) NOT NULL, 
	resource_type VARCHAR(100), 
	resource_id VARCHAR(255), 
	outcome VARCHAR(20) NOT NULL, 
	duration_ms INTEGER, 
	token_usage JSON, 
	cost NUMERIC(18, 6), 
	request_id VARCHAR(64) NOT NULL, 
	trace_id VARCHAR(64), 
	ip VARCHAR(64), 
	metadata JSON, 
	extensions JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	FOREIGN KEY(agent_id) REFERENCES agent (id), 
	FOREIGN KEY(run_id) REFERENCES agent_run (id), 
	FOREIGN KEY(tool_call_id) REFERENCES tool_call (id)
);
CREATE INDEX ix_audit_log_action ON audit_log (action);
CREATE INDEX ix_audit_log_request_id ON audit_log (request_id);
CREATE INDEX ix_audit_log_run_id ON audit_log (run_id);
CREATE INDEX ix_audit_log_tenant_id ON audit_log (tenant_id);
CREATE TABLE conversation (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36) NOT NULL, 
	agent_id CHAR(36) NOT NULL, 
	user_id CHAR(36) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(agent_id) REFERENCES agent (id), 
	FOREIGN KEY(user_id) REFERENCES user (id)
);
CREATE INDEX ix_conversation_agent_id ON conversation (agent_id);
CREATE INDEX ix_conversation_organization_id ON conversation (organization_id);
CREATE INDEX ix_conversation_tenant_id ON conversation (tenant_id);
CREATE INDEX ix_conversation_user_id ON conversation (user_id);
CREATE INDEX ix_conversation_workspace_id ON conversation (workspace_id);
CREATE TABLE credential (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	provider VARCHAR(100) NOT NULL, 
	key_type VARCHAR(50) NOT NULL, 
	encrypted_value TEXT NOT NULL, 
	name VARCHAR(150), 
	status VARCHAR(20) NOT NULL, 
	last_used_at DATETIME, 
	metadata JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id)
);
CREATE INDEX ix_credential_name ON credential (name);
CREATE INDEX ix_credential_organization_id ON credential (organization_id);
CREATE INDEX ix_credential_tenant_id ON credential (tenant_id);
CREATE INDEX ix_credential_workspace_id ON credential (workspace_id);
CREATE TABLE document (
	id CHAR(36) NOT NULL, 
	knowledge_base_id CHAR(36) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	source_type VARCHAR(20) NOT NULL, 
	storage_key VARCHAR(1024), 
	mime VARCHAR(255), 
	size INTEGER, 
	checksum VARCHAR(128), 
	status VARCHAR(50) NOT NULL, 
	error TEXT, 
	task_id CHAR(36), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_base (id), 
	FOREIGN KEY(task_id) REFERENCES task (id)
);
CREATE INDEX ix_document_knowledge_base_id ON document (knowledge_base_id);
CREATE INDEX ix_document_status ON document (status);
CREATE INDEX ix_document_task_id ON document (task_id);
CREATE TABLE document_chunk (
	id CHAR(36) NOT NULL, 
	document_id CHAR(36) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	token_count INTEGER, 
	metadata JSON, 
	embedding_id CHAR(36), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_document_chunk_document_ordinal UNIQUE (document_id, ordinal), 
	FOREIGN KEY(document_id) REFERENCES document (id)
);
CREATE INDEX ix_document_chunk_document_id ON document_chunk (document_id);
CREATE TABLE embedding (
	id CHAR(36) NOT NULL, 
	chunk_id CHAR(36) NOT NULL, 
	model VARCHAR(255) NOT NULL, 
	dimensions INTEGER NOT NULL, 
	vector JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_embedding_chunk_id UNIQUE (chunk_id), 
	FOREIGN KEY(chunk_id) REFERENCES document_chunk (id)
);
CREATE INDEX ix_embedding_chunk_id ON embedding (chunk_id);
CREATE TABLE evaluation_case (
	id CHAR(36) NOT NULL, 
	dataset_id CHAR(36) NOT NULL, 
	case_key VARCHAR(255) NOT NULL, 
	input JSON NOT NULL, 
	expected JSON, 
	assertions JSON, 
	tags JSON, 
	position INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluation_case_dataset_case_key UNIQUE (dataset_id, case_key), 
	FOREIGN KEY(dataset_id) REFERENCES evaluation_dataset (id)
);
CREATE INDEX ix_evaluation_case_dataset_id ON evaluation_case (dataset_id);
CREATE TABLE evaluation_dataset (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	version INTEGER NOT NULL, 
	parent_dataset_id CHAR(36), 
	status VARCHAR(50) NOT NULL, 
	description VARCHAR(1024), 
	created_by CHAR(36), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(parent_dataset_id) REFERENCES evaluation_dataset (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_evaluation_dataset_organization_id ON evaluation_dataset (organization_id);
CREATE INDEX ix_evaluation_dataset_tenant_id ON evaluation_dataset (tenant_id);
CREATE INDEX ix_evaluation_dataset_workspace_id ON evaluation_dataset (workspace_id);
CREATE TABLE evaluation_result (
	id CHAR(36) NOT NULL, 
	evaluation_run_id CHAR(36) NOT NULL, 
	case_id CHAR(36) NOT NULL, 
	agent_run_id CHAR(36), 
	status VARCHAR(50) NOT NULL, 
	score FLOAT, 
	assertion_results JSON, 
	duration_ms INTEGER, 
	token_usage JSON, 
	cost FLOAT, 
	error_type VARCHAR(50), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluation_result_run_case UNIQUE (evaluation_run_id, case_id), 
	FOREIGN KEY(evaluation_run_id) REFERENCES evaluation_run (id), 
	FOREIGN KEY(case_id) REFERENCES evaluation_case (id), 
	FOREIGN KEY(agent_run_id) REFERENCES agent_run (id)
);
CREATE INDEX ix_evaluation_result_agent_run_id ON evaluation_result (agent_run_id);
CREATE INDEX ix_evaluation_result_case_id ON evaluation_result (case_id);
CREATE INDEX ix_evaluation_result_evaluation_run_id ON evaluation_result (evaluation_run_id);
CREATE TABLE evaluation_run (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	dataset_id CHAR(36) NOT NULL, 
	agent_id CHAR(36) NOT NULL, 
	agent_version_id CHAR(36) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	idempotency_key VARCHAR(255), 
	started_at DATETIME, 
	completed_at DATETIME, 
	summary JSON, 
	created_by CHAR(36), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluation_run_idempotency_key UNIQUE (idempotency_key), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(dataset_id) REFERENCES evaluation_dataset (id), 
	FOREIGN KEY(agent_id) REFERENCES agent (id), 
	FOREIGN KEY(agent_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_evaluation_run_agent_id ON evaluation_run (agent_id);
CREATE INDEX ix_evaluation_run_agent_version_id ON evaluation_run (agent_version_id);
CREATE INDEX ix_evaluation_run_dataset_id ON evaluation_run (dataset_id);
CREATE INDEX ix_evaluation_run_organization_id ON evaluation_run (organization_id);
CREATE INDEX ix_evaluation_run_tenant_id ON evaluation_run (tenant_id);
CREATE INDEX ix_evaluation_run_workspace_id ON evaluation_run (workspace_id);
CREATE TABLE feature_flag (
	id CHAR(36) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	description VARCHAR(255), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_feature_flag_name ON feature_flag (name);
CREATE TABLE knowledge_base (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	embedding_model JSON NOT NULL, 
	chunk_config JSON NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_base_tenant_name UNIQUE (tenant_id, name), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_knowledge_base_created_by ON knowledge_base (created_by);
CREATE INDEX ix_knowledge_base_organization_id ON knowledge_base (organization_id);
CREATE INDEX ix_knowledge_base_tenant_id ON knowledge_base (tenant_id);
CREATE INDEX ix_knowledge_base_workspace_id ON knowledge_base (workspace_id);
CREATE TABLE login_attempt (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36), 
	username VARCHAR(150), 
	ip_address VARCHAR(64), 
	success BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id)
);
CREATE INDEX ix_login_attempt_tenant_id ON login_attempt (tenant_id);
CREATE INDEX ix_login_attempt_username ON login_attempt (username);
CREATE TABLE mcp_permission (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	agent_id CHAR(36), 
	agent_version_id CHAR(36), 
	mcp_tool_id CHAR(36) NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	effect VARCHAR(20) NOT NULL, 
	scope JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mcp_permission_tool_agent_action UNIQUE (mcp_tool_id, agent_id, action), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(agent_id) REFERENCES agent (id), 
	FOREIGN KEY(agent_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(mcp_tool_id) REFERENCES mcp_tool (id)
);
CREATE INDEX ix_mcp_permission_agent_id ON mcp_permission (agent_id);
CREATE INDEX ix_mcp_permission_agent_version_id ON mcp_permission (agent_version_id);
CREATE INDEX ix_mcp_permission_mcp_tool_id ON mcp_permission (mcp_tool_id);
CREATE INDEX ix_mcp_permission_tenant_id ON mcp_permission (tenant_id);
CREATE TABLE mcp_server (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	transport VARCHAR(20) NOT NULL, 
	endpoint VARCHAR(1024), 
	command VARCHAR(1024), 
	args JSON, 
	env_ref JSON, 
	credential_id CHAR(36), 
	status VARCHAR(50) NOT NULL, 
	capabilities JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mcp_server_tenant_name UNIQUE (tenant_id, name), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(credential_id) REFERENCES credential (id)
);
CREATE INDEX ix_mcp_server_credential_id ON mcp_server (credential_id);
CREATE INDEX ix_mcp_server_organization_id ON mcp_server (organization_id);
CREATE INDEX ix_mcp_server_tenant_id ON mcp_server (tenant_id);
CREATE INDEX ix_mcp_server_workspace_id ON mcp_server (workspace_id);
CREATE TABLE mcp_tool (
	id CHAR(36) NOT NULL, 
	mcp_server_id CHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	input_schema JSON, 
	output_schema JSON, 
	discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mcp_tool_server_name UNIQUE (mcp_server_id, name), 
	FOREIGN KEY(mcp_server_id) REFERENCES mcp_server (id)
);
CREATE INDEX ix_mcp_tool_mcp_server_id ON mcp_tool (mcp_server_id);
CREATE TABLE membership (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	user_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	role_id CHAR(36), 
	status VARCHAR(50) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(role_id) REFERENCES role (id)
);
CREATE INDEX ix_membership_organization_id ON membership (organization_id);
CREATE INDEX ix_membership_role_id ON membership (role_id);
CREATE INDEX ix_membership_tenant_id ON membership (tenant_id);
CREATE INDEX ix_membership_user_id ON membership (user_id);
CREATE TABLE memory (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	kind VARCHAR(50) NOT NULL, 
	scope_type VARCHAR(50) NOT NULL, 
	scope_id VARCHAR(255) NOT NULL, 
	visibility VARCHAR(50) NOT NULL, 
	content TEXT NOT NULL, 
	memory_type VARCHAR(50) NOT NULL, 
	importance FLOAT NOT NULL, 
	confidence FLOAT NOT NULL, 
	source_run_id CHAR(36), 
	vector JSON, 
	expires_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(source_run_id) REFERENCES agent_run (id)
);
CREATE INDEX ix_memory_expires_at ON memory (expires_at);
CREATE INDEX ix_memory_organization_id ON memory (organization_id);
CREATE INDEX ix_memory_source_run_id ON memory (source_run_id);
CREATE INDEX ix_memory_tenant_id ON memory (tenant_id);
CREATE INDEX ix_memory_tenant_scope_kind ON memory (tenant_id, scope_type, scope_id, kind);
CREATE INDEX ix_memory_workspace_id ON memory (workspace_id);
CREATE TABLE memory_relation (
	id CHAR(36) NOT NULL, 
	from_memory_id CHAR(36) NOT NULL, 
	to_memory_id CHAR(36) NOT NULL, 
	relation VARCHAR(50) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_memory_relation_from_to_relation UNIQUE (from_memory_id, to_memory_id, relation), 
	FOREIGN KEY(from_memory_id) REFERENCES memory (id), 
	FOREIGN KEY(to_memory_id) REFERENCES memory (id)
);
CREATE INDEX ix_memory_relation_from_memory_id ON memory_relation (from_memory_id);
CREATE INDEX ix_memory_relation_to_memory_id ON memory_relation (to_memory_id);
CREATE TABLE message (
	id CHAR(36) NOT NULL, 
	conversation_id CHAR(36) NOT NULL, 
	run_id CHAR(36), 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	content_parts JSON, 
	token_count INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversation (id), 
	FOREIGN KEY(run_id) REFERENCES agent_run (id)
);
CREATE INDEX ix_message_conversation_id ON message (conversation_id);
CREATE INDEX ix_message_run_id ON message (run_id);
CREATE TABLE model (
	id CHAR(36) NOT NULL, 
	provider_id CHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	context_window INTEGER, 
	capabilities JSON, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(provider_id) REFERENCES model_provider (id)
);
CREATE INDEX ix_model_provider_id ON model (provider_id);
CREATE TABLE model_provider (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	endpoint VARCHAR(512), 
	credential_id CHAR(36), 
	status VARCHAR(50) NOT NULL, 
	config JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(credential_id) REFERENCES credential (id)
);
CREATE INDEX ix_model_provider_credential_id ON model_provider (credential_id);
CREATE INDEX ix_model_provider_organization_id ON model_provider (organization_id);
CREATE INDEX ix_model_provider_tenant_id ON model_provider (tenant_id);
CREATE INDEX ix_model_provider_workspace_id ON model_provider (workspace_id);
CREATE TABLE model_provider_credential (
	id CHAR(36) NOT NULL, 
	provider_id CHAR(36) NOT NULL, 
	credential_id CHAR(36) NOT NULL, 
	weight INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_model_provider_credential UNIQUE (provider_id, credential_id), 
	FOREIGN KEY(provider_id) REFERENCES model_provider (id), 
	FOREIGN KEY(credential_id) REFERENCES credential (id)
);
CREATE INDEX ix_model_provider_credential_credential_id ON model_provider_credential (credential_id);
CREATE INDEX ix_model_provider_credential_provider_id ON model_provider_credential (provider_id);
CREATE TABLE organization (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	slug VARCHAR(255) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id)
);
CREATE INDEX ix_organization_slug ON organization (slug);
CREATE INDEX ix_organization_tenant_id ON organization (tenant_id);
CREATE TABLE permission (
	id CHAR(36) NOT NULL, 
	code VARCHAR(150) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	description VARCHAR(255), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_permission_code ON permission (code);
CREATE TABLE plugin (
	id CHAR(36) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	entry_point VARCHAR(255), 
	permissions JSON NOT NULL, 
	manifest JSON NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	installed_at DATETIME NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_plugin_name ON plugin (name);
CREATE TABLE project (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description VARCHAR(1024), 
	repo_url VARCHAR(2048), 
	default_branch VARCHAR(255), 
	settings JSON, 
	created_by CHAR(36), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_project_organization_id ON project (organization_id);
CREATE INDEX ix_project_tenant_id ON project (tenant_id);
CREATE INDEX ix_project_workspace_id ON project (workspace_id);
CREATE TABLE refresh_token (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	user_id CHAR(36) NOT NULL, 
	session_id CHAR(36), 
	token_hash VARCHAR(255) NOT NULL, 
	expires_at DATETIME NOT NULL, 
	revoked_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	FOREIGN KEY(session_id) REFERENCES session (id)
);
CREATE INDEX ix_refresh_token_session_id ON refresh_token (session_id);
CREATE INDEX ix_refresh_token_tenant_id ON refresh_token (tenant_id);
CREATE INDEX ix_refresh_token_token_hash ON refresh_token (token_hash);
CREATE INDEX ix_refresh_token_user_id ON refresh_token (user_id);
CREATE TABLE resource_permission (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	subject_type VARCHAR(20) NOT NULL, 
	subject_id CHAR(36) NOT NULL, 
	resource_type VARCHAR(30) NOT NULL, 
	resource_id CHAR(36), 
	action VARCHAR(20) NOT NULL, 
	effect VARCHAR(10) NOT NULL, 
	scope JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_resource_permission_subject_resource_action UNIQUE (tenant_id, subject_type, subject_id, resource_type, resource_id, action), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id)
);
CREATE INDEX ix_resource_permission_resource ON resource_permission (tenant_id, resource_type, resource_id);
CREATE INDEX ix_resource_permission_subject ON resource_permission (tenant_id, subject_type, subject_id);
CREATE INDEX ix_resource_permission_tenant_id ON resource_permission (tenant_id);
CREATE TABLE role (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description VARCHAR(255), 
	is_system BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_role_tenant_name UNIQUE (tenant_id, name), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id)
);
CREATE INDEX ix_role_tenant_id ON role (tenant_id);
CREATE TABLE role_permission (
	id CHAR(36) NOT NULL, 
	role_id CHAR(36) NOT NULL, 
	permission_id CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_role_permission UNIQUE (role_id, permission_id), 
	FOREIGN KEY(role_id) REFERENCES role (id), 
	FOREIGN KEY(permission_id) REFERENCES permission (id)
);
CREATE INDEX ix_role_permission_permission_id ON role_permission (permission_id);
CREATE INDEX ix_role_permission_role_id ON role_permission (role_id);
CREATE TABLE sandbox_session (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	run_id CHAR(36), 
	workspace_id CHAR(36), 
	provider VARCHAR(50) NOT NULL, 
	image VARCHAR(255), 
	status VARCHAR(50) NOT NULL, 
	container_ref VARCHAR(255), 
	workdir VARCHAR(512) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	ended_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(run_id) REFERENCES agent_run (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id)
);
CREATE INDEX ix_sandbox_session_run_id ON sandbox_session (run_id);
CREATE INDEX ix_sandbox_session_tenant_id ON sandbox_session (tenant_id);
CREATE INDEX ix_sandbox_session_workspace_id ON sandbox_session (workspace_id);
CREATE TABLE schedule (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	target_type VARCHAR(30) NOT NULL, 
	target_id CHAR(36) NOT NULL, 
	"trigger" VARCHAR(20) NOT NULL, 
	cron VARCHAR(255), 
	event_type VARCHAR(100), 
	payload JSON, 
	enabled BOOLEAN NOT NULL, 
	last_run_at DATETIME, 
	next_run_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_schedule_target_name UNIQUE (tenant_id, target_type, target_id, name), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id)
);
CREATE INDEX ix_schedule_next_run_at ON schedule (next_run_at);
CREATE INDEX ix_schedule_organization_id ON schedule (organization_id);
CREATE INDEX ix_schedule_tenant_id ON schedule (tenant_id);
CREATE INDEX ix_schedule_workspace_id ON schedule (workspace_id);
CREATE TABLE session (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	user_id CHAR(36) NOT NULL, 
	device VARCHAR(255), 
	ip_address VARCHAR(64), 
	user_agent VARCHAR(512), 
	expires_at DATETIME NOT NULL, 
	revoked_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(user_id) REFERENCES user (id)
);
CREATE INDEX ix_session_tenant_id ON session (tenant_id);
CREATE INDEX ix_session_user_id ON session (user_id);
CREATE TABLE skill (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	description TEXT, 
	category VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	current_version_id CHAR(36), 
	created_by CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_skill_tenant_name UNIQUE (tenant_id, name), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	CONSTRAINT fk_skill_current_version_id FOREIGN KEY(current_version_id) REFERENCES skill_version (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_skill_created_by ON skill (created_by);
CREATE INDEX ix_skill_current_version_id ON skill (current_version_id);
CREATE INDEX ix_skill_organization_id ON skill (organization_id);
CREATE INDEX ix_skill_tenant_id ON skill (tenant_id);
CREATE TABLE skill_resource (
	id CHAR(36) NOT NULL, 
	skill_version_id CHAR(36) NOT NULL, 
	path VARCHAR(1024) NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	storage_key VARCHAR(1024), 
	checksum VARCHAR(128), 
	size INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(skill_version_id) REFERENCES skill_version (id)
);
CREATE INDEX ix_skill_resource_skill_version_id ON skill_resource (skill_version_id);
CREATE TABLE skill_version (
	id CHAR(36) NOT NULL, 
	skill_id CHAR(36) NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	instructions TEXT NOT NULL, 
	manifest JSON NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_skill_version_skill_version UNIQUE (skill_id, version), 
	FOREIGN KEY(skill_id) REFERENCES skill (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_skill_version_created_by ON skill_version (created_by);
CREATE INDEX ix_skill_version_skill_id ON skill_version (skill_id);
CREATE TABLE task (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	type VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	priority INTEGER NOT NULL, 
	execution_mode VARCHAR(20) NOT NULL, 
	payload JSON, 
	result JSON, 
	idempotency_key VARCHAR(255), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id)
);
CREATE INDEX ix_task_organization_id ON task (organization_id);
CREATE INDEX ix_task_status ON task (status);
CREATE INDEX ix_task_tenant_id ON task (tenant_id);
CREATE INDEX ix_task_workspace_id ON task (workspace_id);
CREATE UNIQUE INDEX uq_task_idempotency_key ON task (idempotency_key);
CREATE TABLE task_execution (
	id CHAR(36) NOT NULL, 
	task_id CHAR(36) NOT NULL, 
	attempt INTEGER NOT NULL, 
	worker_id VARCHAR(128), 
	status VARCHAR(50) NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	duration_ms INTEGER, 
	error TEXT, 
	project_id CHAR(36), 
	checkout_ref VARCHAR(128), 
	base_commit VARCHAR(64), 
	result_commit VARCHAR(64), 
	environment_digest VARCHAR(64), 
	artifact_refs JSON, 
	heartbeat_at DATETIME, 
	lease_expires_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_task_execution_task_attempt UNIQUE (task_id, attempt), 
	FOREIGN KEY(task_id) REFERENCES task (id), 
	CONSTRAINT fk_task_execution_project_id FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE RESTRICT
);
CREATE INDEX ix_task_execution_project_started ON task_execution (project_id, started_at);
CREATE INDEX ix_task_execution_task_id ON task_execution (task_id);
CREATE UNIQUE INDEX uq_task_execution_checkout_ref ON task_execution (checkout_ref) WHERE checkout_ref IS NOT NULL;
CREATE TABLE tenant (
	id CHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	slug VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_tenant_slug ON tenant (slug);
CREATE TABLE tool (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36), 
	organization_id CHAR(36), 
	name VARCHAR(100) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	description TEXT, 
	category VARCHAR(100) NOT NULL, 
	source VARCHAR(50) NOT NULL, 
	input_schema JSON, 
	output_schema JSON, 
	requires_sandbox BOOLEAN NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	tool_ref JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id)
);
CREATE INDEX ix_tool_name ON tool (name);
CREATE INDEX ix_tool_organization_id ON tool (organization_id);
CREATE INDEX ix_tool_tenant_id ON tool (tenant_id);
CREATE TABLE tool_call (
	id CHAR(36) NOT NULL, 
	run_id CHAR(36) NOT NULL, 
	tool_id CHAR(36), 
	tool_name VARCHAR(255) NOT NULL, 
	tool_type VARCHAR(30) NOT NULL, 
	tool_ref JSON, 
	attempt INTEGER NOT NULL, 
	trace_id VARCHAR(64), 
	span_id VARCHAR(64), 
	input JSON, 
	output JSON, 
	status VARCHAR(50) NOT NULL, 
	duration_ms INTEGER, 
	sandbox_session_id CHAR(36), 
	error TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES agent_run (id), 
	FOREIGN KEY(tool_id) REFERENCES tool (id), 
	FOREIGN KEY(sandbox_session_id) REFERENCES sandbox_session (id)
);
CREATE INDEX ix_tool_call_run_id ON tool_call (run_id);
CREATE INDEX ix_tool_call_sandbox_session_id ON tool_call (sandbox_session_id);
CREATE INDEX ix_tool_call_status ON tool_call (status);
CREATE INDEX ix_tool_call_tool_id ON tool_call (tool_id);
CREATE TABLE tool_permission (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	agent_id CHAR(36), 
	agent_version_id CHAR(36), 
	tool_id CHAR(36) NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	effect VARCHAR(20) NOT NULL, 
	scope JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tool_permission_agent_tool_action UNIQUE (agent_id, tool_id, action), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(agent_id) REFERENCES agent (id), 
	FOREIGN KEY(agent_version_id) REFERENCES agent_version (id), 
	FOREIGN KEY(tool_id) REFERENCES tool (id)
);
CREATE INDEX ix_tool_permission_agent_id ON tool_permission (agent_id);
CREATE INDEX ix_tool_permission_agent_version_id ON tool_permission (agent_version_id);
CREATE INDEX ix_tool_permission_tenant_id ON tool_permission (tenant_id);
CREATE INDEX ix_tool_permission_tool_id ON tool_permission (tool_id);
CREATE TABLE tool_version (
	id CHAR(36) NOT NULL, 
	tool_id CHAR(36) NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	spec JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tool_id) REFERENCES tool (id)
);
CREATE INDEX ix_tool_version_tool_id ON tool_version (tool_id);
CREATE TABLE user (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	username VARCHAR(150) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	display_name VARCHAR(255), 
	is_active BOOLEAN NOT NULL, 
	is_superuser BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_tenant_email UNIQUE (tenant_id, email), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id)
);
CREATE INDEX ix_user_email ON user (email);
CREATE INDEX ix_user_tenant_id ON user (tenant_id);
CREATE INDEX ix_user_username ON user (username);
CREATE TABLE workflow (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36), 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	status VARCHAR(50) NOT NULL, 
	current_version_id CHAR(36), 
	created_by CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_tenant_name UNIQUE (tenant_id, name), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id), 
	CONSTRAINT fk_workflow_current_version_id FOREIGN KEY(current_version_id) REFERENCES workflow_version (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_workflow_created_by ON workflow (created_by);
CREATE INDEX ix_workflow_current_version_id ON workflow (current_version_id);
CREATE INDEX ix_workflow_organization_id ON workflow (organization_id);
CREATE INDEX ix_workflow_tenant_id ON workflow (tenant_id);
CREATE TABLE workflow_edge (
	id CHAR(36) NOT NULL, 
	workflow_version_id CHAR(36) NOT NULL, 
	from_node_key VARCHAR(255) NOT NULL, 
	to_node_key VARCHAR(255) NOT NULL, 
	condition TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_edge_version_from_to UNIQUE (workflow_version_id, from_node_key, to_node_key), 
	FOREIGN KEY(workflow_version_id) REFERENCES workflow_version (id)
);
CREATE INDEX ix_workflow_edge_workflow_version_id ON workflow_edge (workflow_version_id);
CREATE TABLE workflow_node (
	id CHAR(36) NOT NULL, 
	workflow_version_id CHAR(36) NOT NULL, 
	node_key VARCHAR(255) NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	config JSON NOT NULL, 
	position JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_node_version_node_key UNIQUE (workflow_version_id, node_key), 
	FOREIGN KEY(workflow_version_id) REFERENCES workflow_version (id)
);
CREATE INDEX ix_workflow_node_workflow_version_id ON workflow_node (workflow_version_id);
CREATE TABLE workflow_node_run (
	id CHAR(36) NOT NULL, 
	workflow_run_id CHAR(36) NOT NULL, 
	node_key VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	attempt INTEGER NOT NULL, 
	agent_run_id CHAR(36), 
	tool_call_id CHAR(36), 
	approval_id CHAR(36), 
	input JSON, 
	output JSON, 
	started_at DATETIME, 
	completed_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_node_run_run_key_attempt UNIQUE (workflow_run_id, node_key, attempt), 
	FOREIGN KEY(workflow_run_id) REFERENCES workflow_run (id), 
	FOREIGN KEY(agent_run_id) REFERENCES agent_run (id), 
	FOREIGN KEY(tool_call_id) REFERENCES tool_call (id), 
	FOREIGN KEY(approval_id) REFERENCES approval (id)
);
CREATE INDEX ix_workflow_node_run_agent_run_id ON workflow_node_run (agent_run_id);
CREATE INDEX ix_workflow_node_run_approval_id ON workflow_node_run (approval_id);
CREATE INDEX ix_workflow_node_run_workflow_run_id ON workflow_node_run (workflow_run_id);
CREATE TABLE workflow_run (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	workflow_version_id CHAR(36) NOT NULL, 
	"trigger" VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	task_id CHAR(36), 
	input JSON, 
	output JSON, 
	started_at DATETIME, 
	completed_at DATETIME, 
	error TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(workflow_version_id) REFERENCES workflow_version (id), 
	FOREIGN KEY(task_id) REFERENCES task (id)
);
CREATE INDEX ix_workflow_run_status ON workflow_run (status);
CREATE INDEX ix_workflow_run_task_id ON workflow_run (task_id);
CREATE INDEX ix_workflow_run_tenant_id ON workflow_run (tenant_id);
CREATE INDEX ix_workflow_run_workflow_version_id ON workflow_run (workflow_version_id);
CREATE TABLE workflow_version (
	id CHAR(36) NOT NULL, 
	workflow_id CHAR(36) NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	definition JSON NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by CHAR(36) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_version_workflow_version UNIQUE (workflow_id, version), 
	FOREIGN KEY(workflow_id) REFERENCES workflow (id), 
	FOREIGN KEY(created_by) REFERENCES user (id)
);
CREATE INDEX ix_workflow_version_created_by ON workflow_version (created_by);
CREATE INDEX ix_workflow_version_workflow_id ON workflow_version (workflow_id);
CREATE TABLE workspace (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	owner_id CHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	workspace_type VARCHAR(50) NOT NULL, 
	settings JSON, 
	config JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(owner_id) REFERENCES user (id)
);
CREATE INDEX ix_workspace_organization_id ON workspace (organization_id);
CREATE INDEX ix_workspace_owner_id ON workspace (owner_id);
CREATE INDEX ix_workspace_tenant_id ON workspace (tenant_id);
CREATE TABLE workspace_environment (
	id CHAR(36) NOT NULL, 
	tenant_id CHAR(36) NOT NULL, 
	organization_id CHAR(36), 
	workspace_id CHAR(36) NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	env_vars JSON, 
	runtime JSON, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workspace_environment_ws_name UNIQUE (workspace_id, name), 
	FOREIGN KEY(tenant_id) REFERENCES tenant (id), 
	FOREIGN KEY(organization_id) REFERENCES organization (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id)
);
CREATE INDEX ix_workspace_environment_organization_id ON workspace_environment (organization_id);
CREATE INDEX ix_workspace_environment_tenant_id ON workspace_environment (tenant_id);
CREATE INDEX ix_workspace_environment_workspace_id ON workspace_environment (workspace_id);

-- ===== 2. FTS5 虚表（源③：迁移 0013 _create_sqlite_fts，raw DDL） =====
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
CREATE VIRTUAL TABLE document_chunk_fts USING fts5(content, content='document_chunk', content_rowid='rowid');

-- ===== 3. FTS5 影子表（源③：SQLite 内部生成，sqlite_master 回读） =====
-- 🔴 影子表由 CREATE VIRTUAL TABLE **隐式创建**，SQLite 里再显式建会直接报 `table ... already exists`。
--    因此下列语句以注释形式冻结（权威文本取自 sqlite_master），执行本文件时它们会由虚表自动生成。
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
-- [sqlite_master] CREATE TABLE 'document_chunk_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
-- [sqlite_master] CREATE TABLE 'document_chunk_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
-- [sqlite_master] CREATE TABLE 'document_chunk_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
-- [sqlite_master] CREATE TABLE 'document_chunk_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;

-- ===== 4. FTS5 同步触发器（源③：ai / ad / au） =====
-- 🔴 功能性对象：external content 模式下缺这三个触发器，FTS 索引不随基表 INSERT/UPDATE/DELETE 更新，关键词检索静默返回旧结果
--    原文取自 sqlite_master（与迁移 0013 _create_sqlite_fts 逐字一致）
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
CREATE TRIGGER document_chunk_ad AFTER DELETE ON document_chunk BEGIN INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) VALUES ('delete', old.rowid, old.content); END;
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
CREATE TRIGGER document_chunk_ai AFTER INSERT ON document_chunk BEGIN INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END;
-- source: sqlite_master（执行 0013 FTS5 语句后回读）
CREATE TRIGGER document_chunk_au AFTER UPDATE ON document_chunk BEGIN INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) VALUES ('delete', old.rowid, old.content); INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END;

-- 汇总：方言专属对象 8 个（虚表 1 + 影子表 4 + 触发器 3；PG DDL 里 0 处）

