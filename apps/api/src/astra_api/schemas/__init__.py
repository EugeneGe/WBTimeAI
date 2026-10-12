"""统一请求 / 响应 schema 汇总导出（pydantic）。"""

from __future__ import annotations

from .agent import (
    AgentResponse,
    AgentToolBind,
    AgentToolResponse,
    AgentVersionResponse,
    CreateAgentRequest,
    PublishRequest,
    RunRequest,
    UpdateAgentRequest,
)
from .approval import ApprovalResponse
from .audit import AuditLogResponse
from .auth import (
    AuthUserResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from .common import ErrorResponse, MessageResponse
from .conversation import (
    ConversationMessageResponse,
    ConversationResponse,
    CreateConversationRequest,
)

# -- W9 / T2-47：Evaluation（任务集 / 用例 / 评测 / 对比视图） ---------------
from .evaluation import (
    CaseIn,
    CaseOut,
    CompareReport,
    CreateDatasetRequest,
    DatasetOut,
    FailsOut,
    ImportCasesRequest,
    MetricDeltaOut,
    ResultOut,
    RunOut,
    StartRunRequest,
)

# -- W6 / T2-35（前端/API 流）：knowledge / memory --------------------------
from .knowledge import (
    CreateDocumentRequest,
    CreateKnowledgeBaseRequest,
    DocumentResponse,
    KnowledgeBaseResponse,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
)

# -- W8 / T2-44：Marketplace（导入 / 导出视图） ----------------------------
from .marketplace import (
    ExportResultResponse,
    ImportPackageRequest,
    ImportResultResponse,
    PackageMetadataResponse,
)
from .mcp import (
    CreateMCPPermissionRequest,
    MCPPermissionResponse,
    MCPServerResponse,
    MCPToolResponse,
    RegisterMCPServerRequest,
)
from .memory import MemoryResponse
from .model import (
    BindCredentialRequest,
    ModelProviderResponse,
    ModelResponse,
    RegisterModelRequest,
    RegisterProviderRequest,
)
from .organization import OrganizationResponse
from .permission import PermissionCheckResponse
from .plugin import InstallPluginRequest, PluginResponse

# -- W10 / T2-49：2c API 子集（projects / workspace files / environment） ------
from .project import (
    CloneProjectRequest,
    CloneProjectResponse,
    CreateProjectRequest,
    EnvironmentResponse,
    EnvironmentVarResponse,
    FileContentResponse,
    FileObjectResponse,
    GitRefResponse,
    ProjectResponse,
    ProjectStatusResponse,
)
from .run import RunEventResponse, RunResponse, ToolCallResponse

# -- W7 / T2-39：Task/Scheduler 增强（调度 CRUD） --------------------------
from .schedule import (
    CreateScheduleRequest,
    ScheduleResponse,
    TriggerScheduleResponse,
    UpdateScheduleRequest,
)
from .settings import (
    CredentialResponse,
    FeatureFlagsResponse,
    PersonalSettingsResponse,
    SaveCredentialRequest,
    SystemSettingsResponse,
    UpdatePersonalSettingsRequest,
)
from .skill import (
    CreateSkillRequest,
    CreateSkillVersionRequest,
    SkillResponse,
    SkillVersionResponse,
    UpdateSkillRequest,
)
from .task import (
    DiffFileResponse,
    RemoteTaskSubmitRequest,
    RemoteTaskSubmitResponse,
    RemoteTaskViewResponse,
    TaskArtifactResponse,
    TaskAttemptResponse,
    TaskDiffResponse,
    TaskEventPageResponse,
    TaskEventResponse,
    TaskExecutionResponse,
    TaskLogResponse,
    TaskResponse,
)
from .tool import ToolPermissionRequest, ToolPermissionResponse, ToolResponse
from .user import DeviceResponse, UpdateUserRequest, UserResponse
from .workflow import (
    CreateWorkflowRequest,
    PublishWorkflowRequest,
    RunWorkflowRequest,
    UpdateWorkflowRequest,
    WorkflowEdgeInput,
    WorkflowNodeInput,
    WorkflowNodeRunResponse,
    WorkflowReplayResponse,
    WorkflowResponse,
    WorkflowRunResponse,
    WorkflowVersionResponse,
)
from .workspace import (
    CreateWorkspaceRequest,
    UpdateWorkspaceSettingsRequest,
    WorkspaceResponse,
)

__all__ = [
    # common
    "ErrorResponse",
    "MessageResponse",
    # auth
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "TokenResponse",
    "AuthUserResponse",
    # user
    "UserResponse",
    "UpdateUserRequest",
    "DeviceResponse",
    # organization
    "OrganizationResponse",
    # workspace
    "CreateWorkspaceRequest",
    "UpdateWorkspaceSettingsRequest",
    "WorkspaceResponse",
    # settings
    "SystemSettingsResponse",
    "PersonalSettingsResponse",
    "UpdatePersonalSettingsRequest",
    "SaveCredentialRequest",
    "CredentialResponse",
    "FeatureFlagsResponse",
    # agent（W6 / T1-28）
    "CreateAgentRequest",
    "UpdateAgentRequest",
    "AgentToolBind",
    "PublishRequest",
    "RunRequest",
    "AgentResponse",
    "AgentVersionResponse",
    "AgentToolResponse",
    # run（W6 / T1-28）
    "RunResponse",
    "RunEventResponse",
    "ToolCallResponse",
    # model（W6 / T1-29 + T1-30）
    "RegisterProviderRequest",
    "RegisterModelRequest",
    "BindCredentialRequest",
    "ModelProviderResponse",
    "ModelResponse",
    # tool（W6 / T1-29）
    "ToolResponse",
    "ToolPermissionRequest",
    "ToolPermissionResponse",
    # conversation（W6 / T1-29）
    "CreateConversationRequest",
    "ConversationResponse",
    "ConversationMessageResponse",
    # task（W6 / T1-29；W10-E2 增执行记录；R3 / T2-60 增远程视图）
    "TaskResponse",
    "TaskExecutionResponse",
    "RemoteTaskSubmitRequest",
    "RemoteTaskSubmitResponse",
    "RemoteTaskViewResponse",
    "TaskAttemptResponse",
    "TaskEventResponse",
    "TaskEventPageResponse",
    "TaskLogResponse",
    "DiffFileResponse",
    "TaskDiffResponse",
    "TaskArtifactResponse",
    # permission（W3 / T2-14）
    "PermissionCheckResponse",
    # skill / mcp / plugin / audit（W3 / T2-17）
    "CreateSkillRequest",
    "UpdateSkillRequest",
    "CreateSkillVersionRequest",
    "SkillResponse",
    "SkillVersionResponse",
    "RegisterMCPServerRequest",
    "MCPServerResponse",
    "MCPToolResponse",
    "CreateMCPPermissionRequest",
    "MCPPermissionResponse",
    "InstallPluginRequest",
    "PluginResponse",
    "AuditLogResponse",
    # workflow（W4 / T2-25）
    "CreateWorkflowRequest",
    "UpdateWorkflowRequest",
    "WorkflowNodeInput",
    "WorkflowEdgeInput",
    "PublishWorkflowRequest",
    "RunWorkflowRequest",
    "WorkflowResponse",
    "WorkflowVersionResponse",
    "WorkflowRunResponse",
    "WorkflowNodeRunResponse",
    "WorkflowReplayResponse",
    # knowledge（W6 / T2-35 · 前端/API 流）
    "CreateKnowledgeBaseRequest",
    "CreateDocumentRequest",
    "SearchRequest",
    "KnowledgeBaseResponse",
    "DocumentResponse",
    "SearchHitResponse",
    "SearchResponse",
    # memory（W6 / T2-35 · 前端/API 流）
    "MemoryResponse",
    # schedule（W7 / T2-39 · Task/Scheduler 增强）
    "CreateScheduleRequest",
    "UpdateScheduleRequest",
    "ScheduleResponse",
    "TriggerScheduleResponse",
    # marketplace（W8 / T2-44）
    "ImportPackageRequest",
    "PackageMetadataResponse",
    "ImportResultResponse",
    "ExportResultResponse",
    # evaluation（W9 / T2-47）
    "CreateDatasetRequest",
    "ImportCasesRequest",
    "StartRunRequest",
    "DatasetOut",
    "CaseIn",
    "CaseOut",
    "ResultOut",
    "RunOut",
    "MetricDeltaOut",
    "FailsOut",
    "CompareReport",
    # -- W10 / T2-49（2c API 子集：projects / files / environment / approvals）
    "CreateProjectRequest",
    "ProjectResponse",
    "FileObjectResponse",
    "FileContentResponse",
    "EnvironmentVarResponse",
    "EnvironmentResponse",
    # R3 / T2-60：远程 Project 视图
    "CloneProjectRequest",
    "CloneProjectResponse",
    "ProjectStatusResponse",
    "GitRefResponse",
    "ApprovalResponse",
]
