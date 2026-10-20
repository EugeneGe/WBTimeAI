-- ==============================================================================
-- WBTimeAI DDL 冻结面 · PostgreSQL（schema v0018）
-- ==============================================================================
-- 契约版本：schema_version = v0018（对应迁移链 0018 收敛态）
-- 方言：postgresql
-- 生成者：scripts/extract-from-py/ddl/export_ddl.py（禁止手改；数字由脚本实跑得出）
--
-- 三源构成（缺一源即冻结面失真，路线图 §3.3.1 / M-02）：
--   源① ORM metadata 编译：61 表 / 629 列 / 174 索引（unique 7 / partial 1）
--   源② 迁移链 raw DDL：2 个 hnsw 向量索引（ix_embedding_vector_hnsw / ix_memory_vector_hnsw，metadata 里 0 处）
--   合并后索引对象总数：174 + 2 = 176
--
-- 段落顺序：1) 扩展 → 2) 表 + 所属索引（按表名排序）→ 3) 外键约束 → 4) 迁移 raw 索引
-- 外键延后到建表之后：这样「按表名排序」与「整份文件可执行」可以同时成立
-- 索引一律 FOLLOW 所属表，便于逐表对账；文件名序 = 冻结序（stable diff）
-- ==============================================================================

-- ===== 1. 扩展（源②：迁移 0013 _try_enable_pg_vector，raw DDL）=====
-- source: migration:migrations/versions/0013_phase2_knowledge.py:104
-- source: migration:migrations/versions/0014_phase2_memory.py:95
-- 注：2 处迁移各写一次同一条幂等语句，此处只保留一条
CREATE EXTENSION IF NOT EXISTS vector;

-- ===== 2. 表与所属索引（源①：ORM metadata 编译，按表名排序）=====
CREATE TABLE agent (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	type VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	current_version_id UUID, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_agent_created_by ON agent (created_by);
CREATE INDEX ix_agent_current_version_id ON agent (current_version_id);
CREATE INDEX ix_agent_organization_id ON agent (organization_id);
CREATE INDEX ix_agent_tenant_id ON agent (tenant_id);
CREATE INDEX ix_agent_workspace_id ON agent (workspace_id);
CREATE TABLE agent_event (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	seq INTEGER NOT NULL, 
	type VARCHAR(100) NOT NULL, 
	payload JSONB, 
	trace_id VARCHAR(64), 
	span_id VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_agent_event_run_id ON agent_event (run_id);
CREATE INDEX ix_agent_event_seq ON agent_event (seq);
CREATE TABLE agent_knowledge (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	agent_version_id UUID NOT NULL, 
	knowledge_base_id UUID NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	config JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_agent_knowledge_version_kb UNIQUE (agent_version_id, knowledge_base_id)
);
CREATE INDEX ix_agent_knowledge_agent_version_id ON agent_knowledge (agent_version_id);
CREATE INDEX ix_agent_knowledge_knowledge_base_id ON agent_knowledge (knowledge_base_id);
CREATE INDEX ix_agent_knowledge_tenant_id ON agent_knowledge (tenant_id);
CREATE TABLE agent_run (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	agent_id UUID NOT NULL, 
	agent_version_id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	user_id UUID, 
	task_id UUID, 
	trigger VARCHAR(50) NOT NULL, 
	run_mode VARCHAR(20) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	trace_id VARCHAR(64), 
	span_id VARCHAR(64), 
	last_heartbeat_at TIMESTAMP WITH TIME ZONE, 
	idempotency_key VARCHAR(255), 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	duration_ms INTEGER, 
	token_usage JSONB, 
	success BOOLEAN, 
	error_type VARCHAR(100), 
	tool_error_count INTEGER NOT NULL, 
	cost NUMERIC(18, 6), 
	cost_currency VARCHAR(10), 
	cost_price_version VARCHAR(50), 
	cost_estimated BOOLEAN NOT NULL, 
	cost_breakdown JSONB, 
	cost_status VARCHAR(20) NOT NULL, 
	error TEXT, 
	PRIMARY KEY (id)
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
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	agent_version_id UUID NOT NULL, 
	skill_id UUID NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	config JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_agent_skill_version_skill UNIQUE (agent_version_id, skill_id)
);
CREATE INDEX ix_agent_skill_agent_version_id ON agent_skill (agent_version_id);
CREATE INDEX ix_agent_skill_skill_id ON agent_skill (skill_id);
CREATE INDEX ix_agent_skill_tenant_id ON agent_skill (tenant_id);
CREATE TABLE agent_tool (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	agent_version_id UUID NOT NULL, 
	tool_id UUID NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	permission_scope JSONB, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_agent_tool_version_tool UNIQUE (agent_version_id, tool_id)
);
CREATE INDEX ix_agent_tool_agent_version_id ON agent_tool (agent_version_id);
CREATE INDEX ix_agent_tool_tenant_id ON agent_tool (tenant_id);
CREATE INDEX ix_agent_tool_tool_id ON agent_tool (tool_id);
CREATE TABLE agent_version (
	id UUID NOT NULL, 
	agent_id UUID NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	system_prompt TEXT NOT NULL, 
	model_config JSONB NOT NULL, 
	runtime_config JSONB NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_agent_version_agent_id ON agent_version (agent_id);
CREATE INDEX ix_agent_version_created_by ON agent_version (created_by);
CREATE TABLE approval (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	subject_type VARCHAR(20) NOT NULL, 
	subject_ref VARCHAR(255) NOT NULL, 
	requested_by UUID, 
	status VARCHAR(20) NOT NULL, 
	decided_by UUID, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	payload JSONB NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_approval_tenant_id ON approval (tenant_id);
CREATE TABLE audit_log (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	user_id UUID, 
	agent_id UUID, 
	run_id UUID, 
	tool_call_id UUID, 
	action VARCHAR(100) NOT NULL, 
	resource_type VARCHAR(100), 
	resource_id VARCHAR(255), 
	outcome VARCHAR(20) NOT NULL, 
	duration_ms INTEGER, 
	token_usage JSONB, 
	cost NUMERIC(18, 6), 
	request_id VARCHAR(64) NOT NULL, 
	trace_id VARCHAR(64), 
	ip VARCHAR(64), 
	metadata JSONB, 
	extensions JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_audit_log_action ON audit_log (action);
CREATE INDEX ix_audit_log_request_id ON audit_log (request_id);
CREATE INDEX ix_audit_log_run_id ON audit_log (run_id);
CREATE INDEX ix_audit_log_tenant_id ON audit_log (tenant_id);
CREATE TABLE conversation (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID NOT NULL, 
	agent_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_conversation_agent_id ON conversation (agent_id);
CREATE INDEX ix_conversation_organization_id ON conversation (organization_id);
CREATE INDEX ix_conversation_tenant_id ON conversation (tenant_id);
CREATE INDEX ix_conversation_user_id ON conversation (user_id);
CREATE INDEX ix_conversation_workspace_id ON conversation (workspace_id);
CREATE TABLE credential (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	provider VARCHAR(100) NOT NULL, 
	key_type VARCHAR(50) NOT NULL, 
	encrypted_value TEXT NOT NULL, 
	name VARCHAR(150), 
	status VARCHAR(20) NOT NULL, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	metadata JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_credential_name ON credential (name);
CREATE INDEX ix_credential_organization_id ON credential (organization_id);
CREATE INDEX ix_credential_tenant_id ON credential (tenant_id);
CREATE INDEX ix_credential_workspace_id ON credential (workspace_id);
CREATE TABLE document (
	id UUID NOT NULL, 
	knowledge_base_id UUID NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	source_type VARCHAR(20) NOT NULL, 
	storage_key VARCHAR(1024), 
	mime VARCHAR(255), 
	size INTEGER, 
	checksum VARCHAR(128), 
	status VARCHAR(50) NOT NULL, 
	error TEXT, 
	task_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_document_knowledge_base_id ON document (knowledge_base_id);
CREATE INDEX ix_document_status ON document (status);
CREATE INDEX ix_document_task_id ON document (task_id);
CREATE TABLE document_chunk (
	id UUID NOT NULL, 
	document_id UUID NOT NULL, 
	ordinal INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	token_count INTEGER, 
	metadata JSONB, 
	embedding_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_document_chunk_document_ordinal UNIQUE (document_id, ordinal)
);
CREATE INDEX ix_document_chunk_document_id ON document_chunk (document_id);
CREATE TABLE embedding (
	id UUID NOT NULL, 
	chunk_id UUID NOT NULL, 
	model VARCHAR(255) NOT NULL, 
	dimensions INTEGER NOT NULL, 
	vector VECTOR(1536) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_embedding_chunk_id UNIQUE (chunk_id)
);
CREATE INDEX ix_embedding_chunk_id ON embedding (chunk_id);
CREATE TABLE evaluation_case (
	id UUID NOT NULL, 
	dataset_id UUID NOT NULL, 
	case_key VARCHAR(255) NOT NULL, 
	input JSONB NOT NULL, 
	expected JSONB, 
	assertions JSONB, 
	tags JSONB, 
	position INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluation_case_dataset_case_key UNIQUE (dataset_id, case_key)
);
CREATE INDEX ix_evaluation_case_dataset_id ON evaluation_case (dataset_id);
CREATE TABLE evaluation_dataset (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	name VARCHAR(255) NOT NULL, 
	version INTEGER NOT NULL, 
	parent_dataset_id UUID, 
	status VARCHAR(50) NOT NULL, 
	description VARCHAR(1024), 
	created_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_evaluation_dataset_organization_id ON evaluation_dataset (organization_id);
CREATE INDEX ix_evaluation_dataset_tenant_id ON evaluation_dataset (tenant_id);
CREATE INDEX ix_evaluation_dataset_workspace_id ON evaluation_dataset (workspace_id);
CREATE TABLE evaluation_result (
	id UUID NOT NULL, 
	evaluation_run_id UUID NOT NULL, 
	case_id UUID NOT NULL, 
	agent_run_id UUID, 
	status VARCHAR(50) NOT NULL, 
	score FLOAT, 
	assertion_results JSONB, 
	duration_ms INTEGER, 
	token_usage JSONB, 
	cost FLOAT, 
	error_type VARCHAR(50), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluation_result_run_case UNIQUE (evaluation_run_id, case_id)
);
CREATE INDEX ix_evaluation_result_agent_run_id ON evaluation_result (agent_run_id);
CREATE INDEX ix_evaluation_result_case_id ON evaluation_result (case_id);
CREATE INDEX ix_evaluation_result_evaluation_run_id ON evaluation_result (evaluation_run_id);
CREATE TABLE evaluation_run (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	dataset_id UUID NOT NULL, 
	agent_id UUID NOT NULL, 
	agent_version_id UUID NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	idempotency_key VARCHAR(255), 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	summary JSONB, 
	created_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluation_run_idempotency_key UNIQUE (idempotency_key)
);
CREATE INDEX ix_evaluation_run_agent_id ON evaluation_run (agent_id);
CREATE INDEX ix_evaluation_run_agent_version_id ON evaluation_run (agent_version_id);
CREATE INDEX ix_evaluation_run_dataset_id ON evaluation_run (dataset_id);
CREATE INDEX ix_evaluation_run_organization_id ON evaluation_run (organization_id);
CREATE INDEX ix_evaluation_run_tenant_id ON evaluation_run (tenant_id);
CREATE INDEX ix_evaluation_run_workspace_id ON evaluation_run (workspace_id);
CREATE TABLE feature_flag (
	id UUID NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	description VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_feature_flag_name ON feature_flag (name);
CREATE TABLE knowledge_base (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	embedding_model JSONB NOT NULL, 
	chunk_config JSONB NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_base_tenant_name UNIQUE (tenant_id, name)
);
CREATE INDEX ix_knowledge_base_created_by ON knowledge_base (created_by);
CREATE INDEX ix_knowledge_base_organization_id ON knowledge_base (organization_id);
CREATE INDEX ix_knowledge_base_tenant_id ON knowledge_base (tenant_id);
CREATE INDEX ix_knowledge_base_workspace_id ON knowledge_base (workspace_id);
CREATE TABLE login_attempt (
	id UUID NOT NULL, 
	tenant_id UUID, 
	username VARCHAR(150), 
	ip_address VARCHAR(64), 
	success BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_login_attempt_tenant_id ON login_attempt (tenant_id);
CREATE INDEX ix_login_attempt_username ON login_attempt (username);
CREATE TABLE mcp_permission (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	agent_id UUID, 
	agent_version_id UUID, 
	mcp_tool_id UUID NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	effect VARCHAR(20) NOT NULL, 
	scope JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mcp_permission_tool_agent_action UNIQUE (mcp_tool_id, agent_id, action)
);
CREATE INDEX ix_mcp_permission_agent_id ON mcp_permission (agent_id);
CREATE INDEX ix_mcp_permission_agent_version_id ON mcp_permission (agent_version_id);
CREATE INDEX ix_mcp_permission_mcp_tool_id ON mcp_permission (mcp_tool_id);
CREATE INDEX ix_mcp_permission_tenant_id ON mcp_permission (tenant_id);
CREATE TABLE mcp_server (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	name VARCHAR(255) NOT NULL, 
	transport VARCHAR(20) NOT NULL, 
	endpoint VARCHAR(1024), 
	command VARCHAR(1024), 
	args JSONB, 
	env_ref JSONB, 
	credential_id UUID, 
	status VARCHAR(50) NOT NULL, 
	capabilities JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mcp_server_tenant_name UNIQUE (tenant_id, name)
);
CREATE INDEX ix_mcp_server_credential_id ON mcp_server (credential_id);
CREATE INDEX ix_mcp_server_organization_id ON mcp_server (organization_id);
CREATE INDEX ix_mcp_server_tenant_id ON mcp_server (tenant_id);
CREATE INDEX ix_mcp_server_workspace_id ON mcp_server (workspace_id);
CREATE TABLE mcp_tool (
	id UUID NOT NULL, 
	mcp_server_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	input_schema JSONB, 
	output_schema JSONB, 
	discovered_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_mcp_tool_server_name UNIQUE (mcp_server_id, name)
);
CREATE INDEX ix_mcp_tool_mcp_server_id ON mcp_tool (mcp_server_id);
CREATE TABLE membership (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	organization_id UUID, 
	role_id UUID, 
	status VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_membership_organization_id ON membership (organization_id);
CREATE INDEX ix_membership_role_id ON membership (role_id);
CREATE INDEX ix_membership_tenant_id ON membership (tenant_id);
CREATE INDEX ix_membership_user_id ON membership (user_id);
CREATE TABLE memory (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	kind VARCHAR(50) NOT NULL, 
	scope_type VARCHAR(50) NOT NULL, 
	scope_id VARCHAR(255) NOT NULL, 
	visibility VARCHAR(50) NOT NULL, 
	content TEXT NOT NULL, 
	memory_type VARCHAR(50) NOT NULL, 
	importance FLOAT NOT NULL, 
	confidence FLOAT NOT NULL, 
	source_run_id UUID, 
	vector VECTOR(1536), 
	expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_memory_expires_at ON memory (expires_at);
CREATE INDEX ix_memory_organization_id ON memory (organization_id);
CREATE INDEX ix_memory_source_run_id ON memory (source_run_id);
CREATE INDEX ix_memory_tenant_id ON memory (tenant_id);
CREATE INDEX ix_memory_tenant_scope_kind ON memory (tenant_id, scope_type, scope_id, kind);
CREATE INDEX ix_memory_workspace_id ON memory (workspace_id);
CREATE TABLE memory_relation (
	id UUID NOT NULL, 
	from_memory_id UUID NOT NULL, 
	to_memory_id UUID NOT NULL, 
	relation VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_memory_relation_from_to_relation UNIQUE (from_memory_id, to_memory_id, relation)
);
CREATE INDEX ix_memory_relation_from_memory_id ON memory_relation (from_memory_id);
CREATE INDEX ix_memory_relation_to_memory_id ON memory_relation (to_memory_id);
CREATE TABLE message (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	run_id UUID, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	content_parts JSONB, 
	token_count INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_message_conversation_id ON message (conversation_id);
CREATE INDEX ix_message_run_id ON message (run_id);
CREATE TABLE model (
	id UUID NOT NULL, 
	provider_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	context_window INTEGER, 
	capabilities JSONB, 
	status VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_model_provider_id ON model (provider_id);
CREATE TABLE model_provider (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	name VARCHAR(255) NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	endpoint VARCHAR(512), 
	credential_id UUID, 
	status VARCHAR(50) NOT NULL, 
	config JSONB, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_model_provider_credential_id ON model_provider (credential_id);
CREATE INDEX ix_model_provider_organization_id ON model_provider (organization_id);
CREATE INDEX ix_model_provider_tenant_id ON model_provider (tenant_id);
CREATE INDEX ix_model_provider_workspace_id ON model_provider (workspace_id);
CREATE TABLE model_provider_credential (
	id UUID NOT NULL, 
	provider_id UUID NOT NULL, 
	credential_id UUID NOT NULL, 
	weight INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_model_provider_credential UNIQUE (provider_id, credential_id)
);
CREATE INDEX ix_model_provider_credential_credential_id ON model_provider_credential (credential_id);
CREATE INDEX ix_model_provider_credential_provider_id ON model_provider_credential (provider_id);
CREATE TABLE organization (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	slug VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_organization_slug ON organization (slug);
CREATE INDEX ix_organization_tenant_id ON organization (tenant_id);
CREATE TABLE permission (
	id UUID NOT NULL, 
	code VARCHAR(150) NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	description VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_permission_code ON permission (code);
CREATE TABLE plugin (
	id UUID NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	entry_point VARCHAR(255), 
	permissions JSON NOT NULL, 
	manifest JSON NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	installed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_plugin_name ON plugin (name);
CREATE TABLE project (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description VARCHAR(1024), 
	repo_url VARCHAR(2048), 
	default_branch VARCHAR(255), 
	settings JSONB, 
	created_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_project_organization_id ON project (organization_id);
CREATE INDEX ix_project_tenant_id ON project (tenant_id);
CREATE INDEX ix_project_workspace_id ON project (workspace_id);
CREATE TABLE refresh_token (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	session_id UUID, 
	token_hash VARCHAR(255) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_refresh_token_session_id ON refresh_token (session_id);
CREATE INDEX ix_refresh_token_tenant_id ON refresh_token (tenant_id);
CREATE INDEX ix_refresh_token_token_hash ON refresh_token (token_hash);
CREATE INDEX ix_refresh_token_user_id ON refresh_token (user_id);
CREATE TABLE resource_permission (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	subject_type VARCHAR(20) NOT NULL, 
	subject_id UUID NOT NULL, 
	resource_type VARCHAR(30) NOT NULL, 
	resource_id UUID, 
	action VARCHAR(20) NOT NULL, 
	effect VARCHAR(10) NOT NULL, 
	scope JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_resource_permission_subject_resource_action UNIQUE (tenant_id, subject_type, subject_id, resource_type, resource_id, action)
);
CREATE INDEX ix_resource_permission_resource ON resource_permission (tenant_id, resource_type, resource_id);
CREATE INDEX ix_resource_permission_subject ON resource_permission (tenant_id, subject_type, subject_id);
CREATE INDEX ix_resource_permission_tenant_id ON resource_permission (tenant_id);
CREATE TABLE role (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description VARCHAR(255), 
	is_system BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_role_tenant_name UNIQUE (tenant_id, name)
);
CREATE INDEX ix_role_tenant_id ON role (tenant_id);
CREATE TABLE role_permission (
	id UUID NOT NULL, 
	role_id UUID NOT NULL, 
	permission_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_role_permission UNIQUE (role_id, permission_id)
);
CREATE INDEX ix_role_permission_permission_id ON role_permission (permission_id);
CREATE INDEX ix_role_permission_role_id ON role_permission (role_id);
CREATE TABLE sandbox_session (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	run_id UUID, 
	workspace_id UUID, 
	provider VARCHAR(50) NOT NULL, 
	image VARCHAR(255), 
	status VARCHAR(50) NOT NULL, 
	container_ref VARCHAR(255), 
	workdir VARCHAR(512) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_sandbox_session_run_id ON sandbox_session (run_id);
CREATE INDEX ix_sandbox_session_tenant_id ON sandbox_session (tenant_id);
CREATE INDEX ix_sandbox_session_workspace_id ON sandbox_session (workspace_id);
CREATE TABLE schedule (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	name VARCHAR(255) NOT NULL, 
	target_type VARCHAR(30) NOT NULL, 
	target_id UUID NOT NULL, 
	trigger VARCHAR(20) NOT NULL, 
	cron VARCHAR(255), 
	event_type VARCHAR(100), 
	payload JSONB, 
	enabled BOOLEAN NOT NULL, 
	last_run_at TIMESTAMP WITH TIME ZONE, 
	next_run_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_schedule_target_name UNIQUE (tenant_id, target_type, target_id, name)
);
CREATE INDEX ix_schedule_next_run_at ON schedule (next_run_at);
CREATE INDEX ix_schedule_organization_id ON schedule (organization_id);
CREATE INDEX ix_schedule_tenant_id ON schedule (tenant_id);
CREATE INDEX ix_schedule_workspace_id ON schedule (workspace_id);
CREATE TABLE session (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	device VARCHAR(255), 
	ip_address VARCHAR(64), 
	user_agent VARCHAR(512), 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_session_tenant_id ON session (tenant_id);
CREATE INDEX ix_session_user_id ON session (user_id);
CREATE TABLE skill (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	name VARCHAR(255) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	description TEXT, 
	category VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	current_version_id UUID, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_skill_tenant_name UNIQUE (tenant_id, name)
);
CREATE INDEX ix_skill_created_by ON skill (created_by);
CREATE INDEX ix_skill_current_version_id ON skill (current_version_id);
CREATE INDEX ix_skill_organization_id ON skill (organization_id);
CREATE INDEX ix_skill_tenant_id ON skill (tenant_id);
CREATE TABLE skill_resource (
	id UUID NOT NULL, 
	skill_version_id UUID NOT NULL, 
	path VARCHAR(1024) NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	storage_key VARCHAR(1024), 
	checksum VARCHAR(128), 
	size INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_skill_resource_skill_version_id ON skill_resource (skill_version_id);
CREATE TABLE skill_version (
	id UUID NOT NULL, 
	skill_id UUID NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	instructions TEXT NOT NULL, 
	manifest JSONB NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_skill_version_skill_version UNIQUE (skill_id, version)
);
CREATE INDEX ix_skill_version_created_by ON skill_version (created_by);
CREATE INDEX ix_skill_version_skill_id ON skill_version (skill_id);
CREATE TABLE task (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	type VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	priority INTEGER NOT NULL, 
	execution_mode VARCHAR(20) NOT NULL, 
	payload JSONB, 
	result JSONB, 
	idempotency_key VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_task_organization_id ON task (organization_id);
CREATE INDEX ix_task_status ON task (status);
CREATE INDEX ix_task_tenant_id ON task (tenant_id);
CREATE INDEX ix_task_workspace_id ON task (workspace_id);
CREATE UNIQUE INDEX uq_task_idempotency_key ON task (idempotency_key);
CREATE TABLE task_execution (
	id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	attempt INTEGER NOT NULL, 
	worker_id VARCHAR(128), 
	status VARCHAR(50) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	duration_ms INTEGER, 
	error TEXT, 
	project_id UUID, 
	checkout_ref VARCHAR(128), 
	base_commit VARCHAR(64), 
	result_commit VARCHAR(64), 
	environment_digest VARCHAR(64), 
	artifact_refs JSONB, 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	lease_expires_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_task_execution_task_attempt UNIQUE (task_id, attempt)
);
CREATE INDEX ix_task_execution_project_started ON task_execution (project_id, started_at);
CREATE INDEX ix_task_execution_task_id ON task_execution (task_id);
CREATE UNIQUE INDEX uq_task_execution_checkout_ref ON task_execution (checkout_ref) WHERE checkout_ref IS NOT NULL;
CREATE TABLE tenant (
	id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	slug VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_tenant_slug ON tenant (slug);
CREATE TABLE tool (
	id UUID NOT NULL, 
	tenant_id UUID, 
	organization_id UUID, 
	name VARCHAR(100) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	description TEXT, 
	category VARCHAR(100) NOT NULL, 
	source VARCHAR(50) NOT NULL, 
	input_schema JSONB, 
	output_schema JSONB, 
	requires_sandbox BOOLEAN NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	tool_ref JSONB, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_tool_name ON tool (name);
CREATE INDEX ix_tool_organization_id ON tool (organization_id);
CREATE INDEX ix_tool_tenant_id ON tool (tenant_id);
CREATE TABLE tool_call (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	tool_id UUID, 
	tool_name VARCHAR(255) NOT NULL, 
	tool_type VARCHAR(30) NOT NULL, 
	tool_ref JSONB, 
	attempt INTEGER NOT NULL, 
	trace_id VARCHAR(64), 
	span_id VARCHAR(64), 
	input JSONB, 
	output JSONB, 
	status VARCHAR(50) NOT NULL, 
	duration_ms INTEGER, 
	sandbox_session_id UUID, 
	error TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_tool_call_run_id ON tool_call (run_id);
CREATE INDEX ix_tool_call_sandbox_session_id ON tool_call (sandbox_session_id);
CREATE INDEX ix_tool_call_status ON tool_call (status);
CREATE INDEX ix_tool_call_tool_id ON tool_call (tool_id);
CREATE TABLE tool_permission (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	agent_id UUID, 
	agent_version_id UUID, 
	tool_id UUID NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	effect VARCHAR(20) NOT NULL, 
	scope JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tool_permission_agent_tool_action UNIQUE (agent_id, tool_id, action)
);
CREATE INDEX ix_tool_permission_agent_id ON tool_permission (agent_id);
CREATE INDEX ix_tool_permission_agent_version_id ON tool_permission (agent_version_id);
CREATE INDEX ix_tool_permission_tenant_id ON tool_permission (tenant_id);
CREATE INDEX ix_tool_permission_tool_id ON tool_permission (tool_id);
CREATE TABLE tool_version (
	id UUID NOT NULL, 
	tool_id UUID NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	spec JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_tool_version_tool_id ON tool_version (tool_id);
CREATE TABLE "user" (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	username VARCHAR(150) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	display_name VARCHAR(255), 
	is_active BOOLEAN NOT NULL, 
	is_superuser BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_tenant_email UNIQUE (tenant_id, email)
);
CREATE INDEX ix_user_email ON "user" (email);
CREATE INDEX ix_user_tenant_id ON "user" (tenant_id);
CREATE INDEX ix_user_username ON "user" (username);
CREATE TABLE workflow (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	status VARCHAR(50) NOT NULL, 
	current_version_id UUID, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_tenant_name UNIQUE (tenant_id, name)
);
CREATE INDEX ix_workflow_created_by ON workflow (created_by);
CREATE INDEX ix_workflow_current_version_id ON workflow (current_version_id);
CREATE INDEX ix_workflow_organization_id ON workflow (organization_id);
CREATE INDEX ix_workflow_tenant_id ON workflow (tenant_id);
CREATE TABLE workflow_edge (
	id UUID NOT NULL, 
	workflow_version_id UUID NOT NULL, 
	from_node_key VARCHAR(255) NOT NULL, 
	to_node_key VARCHAR(255) NOT NULL, 
	condition TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_edge_version_from_to UNIQUE (workflow_version_id, from_node_key, to_node_key)
);
CREATE INDEX ix_workflow_edge_workflow_version_id ON workflow_edge (workflow_version_id);
CREATE TABLE workflow_node (
	id UUID NOT NULL, 
	workflow_version_id UUID NOT NULL, 
	node_key VARCHAR(255) NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	config JSONB NOT NULL, 
	position JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_node_version_node_key UNIQUE (workflow_version_id, node_key)
);
CREATE INDEX ix_workflow_node_workflow_version_id ON workflow_node (workflow_version_id);
CREATE TABLE workflow_node_run (
	id UUID NOT NULL, 
	workflow_run_id UUID NOT NULL, 
	node_key VARCHAR(255) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	attempt INTEGER NOT NULL, 
	agent_run_id UUID, 
	tool_call_id UUID, 
	approval_id UUID, 
	input JSONB, 
	output JSONB, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_node_run_run_key_attempt UNIQUE (workflow_run_id, node_key, attempt)
);
CREATE INDEX ix_workflow_node_run_agent_run_id ON workflow_node_run (agent_run_id);
CREATE INDEX ix_workflow_node_run_approval_id ON workflow_node_run (approval_id);
CREATE INDEX ix_workflow_node_run_workflow_run_id ON workflow_node_run (workflow_run_id);
CREATE TABLE workflow_run (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	workflow_version_id UUID NOT NULL, 
	trigger VARCHAR(50) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	task_id UUID, 
	input JSONB, 
	output JSONB, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	error TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_workflow_run_status ON workflow_run (status);
CREATE INDEX ix_workflow_run_task_id ON workflow_run (task_id);
CREATE INDEX ix_workflow_run_tenant_id ON workflow_run (tenant_id);
CREATE INDEX ix_workflow_run_workflow_version_id ON workflow_run (workflow_version_id);
CREATE TABLE workflow_version (
	id UUID NOT NULL, 
	workflow_id UUID NOT NULL, 
	version VARCHAR(50) NOT NULL, 
	definition JSONB NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_version_workflow_version UNIQUE (workflow_id, version)
);
CREATE INDEX ix_workflow_version_created_by ON workflow_version (created_by);
CREATE INDEX ix_workflow_version_workflow_id ON workflow_version (workflow_id);
CREATE TABLE workspace (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	owner_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	workspace_type VARCHAR(50) NOT NULL, 
	settings JSONB, 
	config JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_workspace_organization_id ON workspace (organization_id);
CREATE INDEX ix_workspace_owner_id ON workspace (owner_id);
CREATE INDEX ix_workspace_tenant_id ON workspace (tenant_id);
CREATE TABLE workspace_environment (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	organization_id UUID, 
	workspace_id UUID NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	env_vars JSONB, 
	runtime JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workspace_environment_ws_name UNIQUE (workspace_id, name)
);
CREATE INDEX ix_workspace_environment_organization_id ON workspace_environment (organization_id);
CREATE INDEX ix_workspace_environment_tenant_id ON workspace_environment (tenant_id);
CREATE INDEX ix_workspace_environment_workspace_id ON workspace_environment (workspace_id);

-- ===== 3. 外键约束（源①，159 条；ALTER 形式便于按表名排序后仍可执行）=====
ALTER TABLE agent ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE agent ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE agent ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE agent ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE agent ADD CONSTRAINT fk_agent_current_version_id FOREIGN KEY (current_version_id) REFERENCES agent_version (id);
ALTER TABLE agent_event ADD FOREIGN KEY (run_id) REFERENCES agent_run (id);
ALTER TABLE agent_knowledge ADD FOREIGN KEY (agent_version_id) REFERENCES agent_version (id);
ALTER TABLE agent_knowledge ADD FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id);
ALTER TABLE agent_knowledge ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE agent_run ADD FOREIGN KEY (agent_id) REFERENCES agent (id);
ALTER TABLE agent_run ADD FOREIGN KEY (agent_version_id) REFERENCES agent_version (id);
ALTER TABLE agent_run ADD FOREIGN KEY (conversation_id) REFERENCES conversation (id);
ALTER TABLE agent_run ADD FOREIGN KEY (task_id) REFERENCES task (id);
ALTER TABLE agent_run ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE agent_run ADD FOREIGN KEY (user_id) REFERENCES "user" (id);
ALTER TABLE agent_skill ADD FOREIGN KEY (agent_version_id) REFERENCES agent_version (id);
ALTER TABLE agent_skill ADD FOREIGN KEY (skill_id) REFERENCES skill (id);
ALTER TABLE agent_skill ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE agent_tool ADD FOREIGN KEY (agent_version_id) REFERENCES agent_version (id);
ALTER TABLE agent_tool ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE agent_tool ADD FOREIGN KEY (tool_id) REFERENCES tool (id);
ALTER TABLE agent_version ADD FOREIGN KEY (agent_id) REFERENCES agent (id);
ALTER TABLE agent_version ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE approval ADD FOREIGN KEY (decided_by) REFERENCES "user" (id);
ALTER TABLE approval ADD FOREIGN KEY (requested_by) REFERENCES "user" (id);
ALTER TABLE approval ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE audit_log ADD FOREIGN KEY (agent_id) REFERENCES agent (id);
ALTER TABLE audit_log ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE audit_log ADD FOREIGN KEY (run_id) REFERENCES agent_run (id);
ALTER TABLE audit_log ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE audit_log ADD FOREIGN KEY (tool_call_id) REFERENCES tool_call (id);
ALTER TABLE audit_log ADD FOREIGN KEY (user_id) REFERENCES "user" (id);
ALTER TABLE audit_log ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE conversation ADD FOREIGN KEY (agent_id) REFERENCES agent (id);
ALTER TABLE conversation ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE conversation ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE conversation ADD FOREIGN KEY (user_id) REFERENCES "user" (id);
ALTER TABLE conversation ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE credential ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE credential ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE credential ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE document ADD FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base (id);
ALTER TABLE document ADD FOREIGN KEY (task_id) REFERENCES task (id);
ALTER TABLE document_chunk ADD FOREIGN KEY (document_id) REFERENCES document (id);
ALTER TABLE embedding ADD FOREIGN KEY (chunk_id) REFERENCES document_chunk (id);
ALTER TABLE evaluation_case ADD FOREIGN KEY (dataset_id) REFERENCES evaluation_dataset (id);
ALTER TABLE evaluation_dataset ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE evaluation_dataset ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE evaluation_dataset ADD FOREIGN KEY (parent_dataset_id) REFERENCES evaluation_dataset (id);
ALTER TABLE evaluation_dataset ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE evaluation_dataset ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE evaluation_result ADD FOREIGN KEY (agent_run_id) REFERENCES agent_run (id);
ALTER TABLE evaluation_result ADD FOREIGN KEY (case_id) REFERENCES evaluation_case (id);
ALTER TABLE evaluation_result ADD FOREIGN KEY (evaluation_run_id) REFERENCES evaluation_run (id);
ALTER TABLE evaluation_run ADD FOREIGN KEY (agent_id) REFERENCES agent (id);
ALTER TABLE evaluation_run ADD FOREIGN KEY (agent_version_id) REFERENCES agent_version (id);
ALTER TABLE evaluation_run ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE evaluation_run ADD FOREIGN KEY (dataset_id) REFERENCES evaluation_dataset (id);
ALTER TABLE evaluation_run ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE evaluation_run ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE evaluation_run ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE knowledge_base ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE knowledge_base ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE knowledge_base ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE knowledge_base ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE login_attempt ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE mcp_permission ADD FOREIGN KEY (agent_id) REFERENCES agent (id);
ALTER TABLE mcp_permission ADD FOREIGN KEY (agent_version_id) REFERENCES agent_version (id);
ALTER TABLE mcp_permission ADD FOREIGN KEY (mcp_tool_id) REFERENCES mcp_tool (id);
ALTER TABLE mcp_permission ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE mcp_server ADD FOREIGN KEY (credential_id) REFERENCES credential (id);
ALTER TABLE mcp_server ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE mcp_server ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE mcp_server ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE mcp_tool ADD FOREIGN KEY (mcp_server_id) REFERENCES mcp_server (id);
ALTER TABLE membership ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE membership ADD FOREIGN KEY (role_id) REFERENCES role (id);
ALTER TABLE membership ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE membership ADD FOREIGN KEY (user_id) REFERENCES "user" (id);
ALTER TABLE memory ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE memory ADD FOREIGN KEY (source_run_id) REFERENCES agent_run (id);
ALTER TABLE memory ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE memory ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE memory_relation ADD FOREIGN KEY (from_memory_id) REFERENCES memory (id);
ALTER TABLE memory_relation ADD FOREIGN KEY (to_memory_id) REFERENCES memory (id);
ALTER TABLE message ADD FOREIGN KEY (conversation_id) REFERENCES conversation (id);
ALTER TABLE message ADD FOREIGN KEY (run_id) REFERENCES agent_run (id);
ALTER TABLE model ADD FOREIGN KEY (provider_id) REFERENCES model_provider (id);
ALTER TABLE model_provider ADD FOREIGN KEY (credential_id) REFERENCES credential (id);
ALTER TABLE model_provider ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE model_provider ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE model_provider ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE model_provider_credential ADD FOREIGN KEY (credential_id) REFERENCES credential (id);
ALTER TABLE model_provider_credential ADD FOREIGN KEY (provider_id) REFERENCES model_provider (id);
ALTER TABLE organization ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE project ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE project ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE project ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE project ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE refresh_token ADD FOREIGN KEY (session_id) REFERENCES session (id);
ALTER TABLE refresh_token ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE refresh_token ADD FOREIGN KEY (user_id) REFERENCES "user" (id);
ALTER TABLE resource_permission ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE role ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE role_permission ADD FOREIGN KEY (permission_id) REFERENCES permission (id);
ALTER TABLE role_permission ADD FOREIGN KEY (role_id) REFERENCES role (id);
ALTER TABLE sandbox_session ADD FOREIGN KEY (run_id) REFERENCES agent_run (id);
ALTER TABLE sandbox_session ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE sandbox_session ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE schedule ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE schedule ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE schedule ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE session ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE session ADD FOREIGN KEY (user_id) REFERENCES "user" (id);
ALTER TABLE skill ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE skill ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE skill ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE skill ADD CONSTRAINT fk_skill_current_version_id FOREIGN KEY (current_version_id) REFERENCES skill_version (id);
ALTER TABLE skill_resource ADD FOREIGN KEY (skill_version_id) REFERENCES skill_version (id);
ALTER TABLE skill_version ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE skill_version ADD FOREIGN KEY (skill_id) REFERENCES skill (id);
ALTER TABLE task ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE task ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE task ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE task_execution ADD FOREIGN KEY (task_id) REFERENCES task (id);
ALTER TABLE task_execution ADD CONSTRAINT fk_task_execution_project_id FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE RESTRICT;
ALTER TABLE tool ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE tool ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE tool_call ADD FOREIGN KEY (run_id) REFERENCES agent_run (id);
ALTER TABLE tool_call ADD FOREIGN KEY (sandbox_session_id) REFERENCES sandbox_session (id);
ALTER TABLE tool_call ADD FOREIGN KEY (tool_id) REFERENCES tool (id);
ALTER TABLE tool_permission ADD FOREIGN KEY (agent_id) REFERENCES agent (id);
ALTER TABLE tool_permission ADD FOREIGN KEY (agent_version_id) REFERENCES agent_version (id);
ALTER TABLE tool_permission ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE tool_permission ADD FOREIGN KEY (tool_id) REFERENCES tool (id);
ALTER TABLE tool_version ADD FOREIGN KEY (tool_id) REFERENCES tool (id);
ALTER TABLE "user" ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE workflow ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE workflow ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE workflow ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE workflow ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);
ALTER TABLE workflow ADD CONSTRAINT fk_workflow_current_version_id FOREIGN KEY (current_version_id) REFERENCES workflow_version (id);
ALTER TABLE workflow_edge ADD FOREIGN KEY (workflow_version_id) REFERENCES workflow_version (id);
ALTER TABLE workflow_node ADD FOREIGN KEY (workflow_version_id) REFERENCES workflow_version (id);
ALTER TABLE workflow_node_run ADD FOREIGN KEY (agent_run_id) REFERENCES agent_run (id);
ALTER TABLE workflow_node_run ADD FOREIGN KEY (approval_id) REFERENCES approval (id);
ALTER TABLE workflow_node_run ADD FOREIGN KEY (tool_call_id) REFERENCES tool_call (id);
ALTER TABLE workflow_node_run ADD FOREIGN KEY (workflow_run_id) REFERENCES workflow_run (id);
ALTER TABLE workflow_run ADD FOREIGN KEY (task_id) REFERENCES task (id);
ALTER TABLE workflow_run ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE workflow_run ADD FOREIGN KEY (workflow_version_id) REFERENCES workflow_version (id);
ALTER TABLE workflow_version ADD FOREIGN KEY (created_by) REFERENCES "user" (id);
ALTER TABLE workflow_version ADD FOREIGN KEY (workflow_id) REFERENCES workflow (id);
ALTER TABLE workspace ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE workspace ADD FOREIGN KEY (owner_id) REFERENCES "user" (id);
ALTER TABLE workspace ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE workspace_environment ADD FOREIGN KEY (organization_id) REFERENCES organization (id);
ALTER TABLE workspace_environment ADD FOREIGN KEY (tenant_id) REFERENCES tenant (id);
ALTER TABLE workspace_environment ADD FOREIGN KEY (workspace_id) REFERENCES workspace (id);

-- ===== 4. 迁移 raw DDL 索引（源②，2 个；ORM 无法表达）=====
-- 🔴 这一段是「纯 ORM 编译路线会静默漏掉」的部分：删掉任何一个即 RAG 检索能力失真
-- source: migration:migrations/versions/0013_phase2_knowledge.py:293
CREATE INDEX ix_embedding_vector_hnsw ON embedding USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64);
-- source: migration:migrations/versions/0014_phase2_memory.py:195
CREATE INDEX ix_memory_vector_hnsw ON memory USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64);

