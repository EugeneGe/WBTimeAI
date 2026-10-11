"""``Settings``：基于 pydantic-settings 的统一配置模型。

配置优先级（高 → 低）：**初始化入参 → 环境变量(ASTRA_*) → .env → config.yaml → 默认值**。
敏感值（如 ``secret_key``）**不从 config.yaml 读取**（由 loader 过滤）。
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from .defaults import (
    DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
    DEFAULT_APP_NAME,
    DEFAULT_APP_VERSION,
    DEFAULT_AUDIT_FALLBACK_DIR,
    DEFAULT_AUDIT_FALLBACK_ENABLED,
    DEFAULT_DATA_DIR,
    DEFAULT_DATABASE_URL,
    DEFAULT_EGRESS_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_EGRESS_DENY_PRIVATE,
    DEFAULT_EGRESS_ENABLED,
    DEFAULT_EGRESS_LOG_ALLOWED,
    DEFAULT_EGRESS_MAX_REDIRECTS,
    DEFAULT_EGRESS_READ_TIMEOUT_SECONDS,
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_FEATURE_FLAGS,
    DEFAULT_HOST,
    DEFAULT_JWT_ALGORITHM,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOGIN_LOCK_SECONDS,
    DEFAULT_LOGIN_MAX_ATTEMPTS,
    DEFAULT_MCP_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MCP_ENABLED,
    DEFAULT_MCP_MAX_RETRIES,
    DEFAULT_MCP_READ_TIMEOUT_SECONDS,
    DEFAULT_MEMORY_EXTRACTION_ENABLED,
    DEFAULT_MEMORY_EXTRACTION_TOKEN_LIMIT,
    DEFAULT_MEMORY_IMPORTANCE_WEIGHT,
    DEFAULT_MEMORY_RECALL_TOP_K,
    DEFAULT_MEMORY_RECENCY_HALF_LIFE_DAYS,
    DEFAULT_METRICS_ENABLED,
    DEFAULT_MODE,
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_PROVIDER,
    DEFAULT_PORT,
    DEFAULT_REDIS_URL,
    DEFAULT_REFRESH_TOKEN_TTL_SECONDS,
    DEFAULT_RETENTION_AGENT_EVENT_DAYS,
    DEFAULT_RETENTION_AUDIT_LOG_DAYS,
    DEFAULT_RETENTION_BATCH_SIZE,
    DEFAULT_RETENTION_MESSAGE_DAYS,
    DEFAULT_RETENTION_PAUSED,
    DEFAULT_RETENTION_PROTECTED,
    DEFAULT_RETENTION_REMOTE_ARTIFACT_DAYS,
    DEFAULT_RETENTION_REMOTE_ATTEMPT_CLONE_DAYS,
    DEFAULT_RETENTION_REMOTE_LOG_DAYS,
    DEFAULT_RETENTION_TOOL_CALL_DAYS,
    DEFAULT_RUN_TIMEOUT_MS,
    DEFAULT_SANDBOX_EGRESS_NETWORK,
    DEFAULT_SANDBOX_EGRESS_PROXY_URL,
    DEFAULT_SANDBOX_IMAGE,
    DEFAULT_SANDBOX_NETWORK_PROFILE,
    DEFAULT_SANDBOX_PROVIDER,
    DEFAULT_SANDBOX_WORKDIR,
    DEFAULT_SECRET_PROVIDER,
    DEFAULT_SKILL_BUILTIN_DIRS,
    DEFAULT_SKILL_OVERRIDE_PRIORITY,
    DEFAULT_SKILL_PLUGIN_DIRS,
    DEFAULT_SKILL_WORKSPACE_DIRS,
    DEFAULT_SSE_HEARTBEAT_SECONDS,
    DEFAULT_VECTOR_SEARCH,
    DEFAULT_WORKSPACE_ROOT,
)

__all__ = [
    "Settings",
    "ObservabilitySettings",
    "EgressSettings",
    "McpSettings",
    "SkillSettings",
    "AuditSettings",
    "CapabilitySettings",
    "MemorySettings",
    "RetentionSettings",
]


class ObservabilitySettings(BaseModel):
    """可观测配置（设计 §2.7.3）。

    Attributes:
        metrics_enabled: 是否暴露 ``/metrics``（社区默认 ``false``，Team 可开）。
    """

    metrics_enabled: bool = DEFAULT_METRICS_ENABLED


class EgressSettings(BaseModel):
    """出网策略配置（W1 · T2-03；设计 §2.18）。

    环境变量前缀 ``ASTRA_EGRESS__*``（嵌套分隔符 ``__``，如
    ``ASTRA_EGRESS__ALLOW='["api.example.com"]'``）。

    Attributes:
        enabled: 出网策略总开关（默认开）；配合空 ``allow`` ⇒ **默认拒绝全部出网**。
        allow: 出网白名单（域名 glob / IP 字面）；**首批为空**（部署方显式添加）。
        deny_private: 是否强制拒绝私网 / 元数据等拒段（**不可被 ``allow`` 覆盖**）。
        connect_timeout_seconds: 连接超时（秒）。
        read_timeout_seconds: 读取超时（秒）。
        max_redirects: 重定向最大跳数（逐跳校验）。
        log_allowed: 是否记录放行审计（默认仅记拒绝）。
    """

    enabled: bool = DEFAULT_EGRESS_ENABLED
    allow: list[str] = Field(default_factory=list)
    deny_private: bool = DEFAULT_EGRESS_DENY_PRIVATE
    connect_timeout_seconds: float = DEFAULT_EGRESS_CONNECT_TIMEOUT_SECONDS
    read_timeout_seconds: float = DEFAULT_EGRESS_READ_TIMEOUT_SECONDS
    max_redirects: int = DEFAULT_EGRESS_MAX_REDIRECTS
    log_allowed: bool = DEFAULT_EGRESS_LOG_ALLOWED


class McpSettings(BaseModel):
    """MCP 配置（W2 · T2-11；设计 §2.4 / W2 裁定 R14）。

    环境变量前缀 ``ASTRA_MCP__*``（嵌套分隔符 ``__``，如
    ``ASTRA_MCP__MAX_RETRIES=3``）。

    Attributes:
        connect_timeout_seconds: 建连超时（秒）。
        read_timeout_seconds: 读取超时（秒）。
        max_retries: 最大重试次数。
        enabled: MCP 功能总开关。
    """

    connect_timeout_seconds: float = DEFAULT_MCP_CONNECT_TIMEOUT_SECONDS
    read_timeout_seconds: float = DEFAULT_MCP_READ_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MCP_MAX_RETRIES
    enabled: bool = DEFAULT_MCP_ENABLED


class SkillSettings(BaseModel):
    """Skill 配置（W2 · T2-08；设计 §2.3 / W2 裁定 R14）。

    环境变量前缀 ``ASTRA_SKILL__*``（嵌套分隔符 ``__``；列表以 JSON 提供，如
    ``ASTRA_SKILL__BUILTIN_DIRS='["plugins/skills"]'``）。

    Attributes:
        builtin_dirs: 内置目录（相对仓库根）。
        plugin_dirs: 插件提供的 Skill 目录（随之装配）。
        workspace_dirs: 工作区目录（部署方配置）。
        override_priority: 来源覆盖优先级（高 → 低）。
    """

    builtin_dirs: list[str] = Field(default_factory=lambda: list(DEFAULT_SKILL_BUILTIN_DIRS))
    plugin_dirs: list[str] = Field(default_factory=lambda: list(DEFAULT_SKILL_PLUGIN_DIRS))
    workspace_dirs: list[str] = Field(default_factory=lambda: list(DEFAULT_SKILL_WORKSPACE_DIRS))
    override_priority: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SKILL_OVERRIDE_PRIORITY)
    )


class AuditSettings(BaseModel):
    """审计配置（W3 · T2-17；设计 §2.18 / 裁定 R7 §7.3）。

    环境变量前缀 ``ASTRA_AUDIT__*``（嵌套分隔符 ``__``，如
    ``ASTRA_AUDIT__FALLBACK_DIR=/var/lib/astra/audit-spool``）。

    Attributes:
        fallback_enabled: 审计写入失败是否降级本地落盘（**不静默丢弃**）。
        fallback_dir: 降级落盘目录（空 = 由 sink 解析 ``ASTRA_AUDIT_SPOOL_DIR`` /
            ``~/.astra-ai/audit-spool/``）。
    """

    fallback_enabled: bool = DEFAULT_AUDIT_FALLBACK_ENABLED
    fallback_dir: str = DEFAULT_AUDIT_FALLBACK_DIR


class CapabilitySettings(BaseModel):
    """能力（capability）配置（W5 · T2-27；设计 §2.6 / W5 裁定 B4 / B5）。

    环境变量前缀 ``ASTRA_CAPABILITY__*``（嵌套分隔符 ``__``，如
    ``ASTRA_CAPABILITY__VECTOR_SEARCH=true``）。

    Attributes:
        vector_search: 向量检索三态（B5）。``None`` = 由组合根按 dialect + ``pg_extension``
            探测解析（SQLite → ``False``；PG → 探测 ``vector`` 扩展）；显式 ``True`` / ``False``
            覆盖优先。**确定性查询，非 try/except 推断**。
        embedding_dimensions: ``embedding.vector`` 单列固定维度（B4；默认 1536）。
    """

    vector_search: bool | None = DEFAULT_VECTOR_SEARCH
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS


class MemorySettings(BaseModel):
    """Memory 域配置（W6 · T2-33；设计 §2.7 / 裁定 B6 / §3.2 / §3.3）。

    环境变量前缀 ``ASTRA_MEMORY__*``（嵌套分隔符 ``__``，如
    ``ASTRA_MEMORY__EXTRACTION_ENABLED=false``）。

    Attributes:
        extraction_enabled: 记忆抽取开关（§5 #10；默认开，**可关闭**）。
        extraction_token_limit: 单次抽取 token 上限（NFR N4；默认 2000）。
        extraction_model: 抽取所用模型名（``None`` ＝ 沿用默认模型）。
        recall_top_k: 召回默认条数（top-k）。
        importance_weight: 召回权重的重要度系数。
        recency_half_life_days: 召回时效半衰期（天）。
    """

    extraction_enabled: bool = DEFAULT_MEMORY_EXTRACTION_ENABLED
    extraction_token_limit: int = DEFAULT_MEMORY_EXTRACTION_TOKEN_LIMIT
    extraction_model: str | None = None
    recall_top_k: int = DEFAULT_MEMORY_RECALL_TOP_K
    importance_weight: float = DEFAULT_MEMORY_IMPORTANCE_WEIGHT
    recency_half_life_days: float = DEFAULT_MEMORY_RECENCY_HALF_LIFE_DAYS


class RetentionSettings(BaseModel):
    """数据保留与清理配置（W9 · T2-48；设计 §2.19 / 裁定 R8）。

    环境变量前缀 ``ASTRA_RETENTION__*``（嵌套分隔符 ``__``，如
    ``ASTRA_RETENTION__AGENT_EVENT_DAYS=30`` / ``ASTRA_RETENTION__BATCH_SIZE=500``）。

    Attributes:
        agent_event_days: ``agent_event`` 保留天数（默认 90）。
        message_days: ``message`` 保留天数（默认 90）。
        tool_call_days: ``tool_call`` 保留天数（默认 90）。
        audit_log_days: ``audit_log`` 保留天数（默认 180）。
        batch_size: 每批删除行数（默认 1000）。
        protected: 保护名单（表名 / 行 ID，默认空）。
        remote_attempt_clone_days / remote_artifact_days / remote_log_days: 远程对象保留
            （接口位；本波 inert，``None`` = 未启用）。
        paused: 紧急暂停开关（默认关）。
    """

    agent_event_days: int = DEFAULT_RETENTION_AGENT_EVENT_DAYS
    message_days: int = DEFAULT_RETENTION_MESSAGE_DAYS
    tool_call_days: int = DEFAULT_RETENTION_TOOL_CALL_DAYS
    audit_log_days: int = DEFAULT_RETENTION_AUDIT_LOG_DAYS
    batch_size: int = DEFAULT_RETENTION_BATCH_SIZE
    protected: list[str] = Field(default_factory=lambda: list(DEFAULT_RETENTION_PROTECTED))
    remote_attempt_clone_days: int | None = DEFAULT_RETENTION_REMOTE_ATTEMPT_CLONE_DAYS
    remote_artifact_days: int | None = DEFAULT_RETENTION_REMOTE_ARTIFACT_DAYS
    remote_log_days: int | None = DEFAULT_RETENTION_REMOTE_LOG_DAYS
    paused: bool = DEFAULT_RETENTION_PAUSED


class Settings(BaseSettings):
    """平台统一配置。

    环境变量统一前缀 ``ASTRA_``，例如 ``ASTRA_MODE`` / ``ASTRA_DATABASE_URL`` /
    ``ASTRA_SECRET_KEY``。
    """

    model_config = SettingsConfigDict(
        env_prefix="ASTRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
    )

    # -- 运行模式（决策 D4） -----------------------------------------------
    mode: Literal["local", "server"] = DEFAULT_MODE

    # -- 应用元信息 ---------------------------------------------------------
    app_name: str = DEFAULT_APP_NAME
    app_version: str = DEFAULT_APP_VERSION
    debug: bool = False

    # -- HTTP ---------------------------------------------------------------
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cors_origins: list[str] = Field(default_factory=list)

    # -- 数据库 -------------------------------------------------------------
    database_url: str = DEFAULT_DATABASE_URL
    sql_echo: bool = False

    # -- 安全（敏感：仅经 ENV / secrets 提供） -----------------------------
    secret_key: str = ""

    # -- 认证与令牌（T0-12 / 决策 D1、D8） ---------------------------------
    jwt_algorithm: str = DEFAULT_JWT_ALGORITHM
    access_token_ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    refresh_token_ttl_seconds: int = DEFAULT_REFRESH_TOKEN_TTL_SECONDS
    login_max_attempts: int = DEFAULT_LOGIN_MAX_ATTEMPTS
    login_lock_seconds: int = DEFAULT_LOGIN_LOCK_SECONDS
    secret_provider: Literal["env"] = DEFAULT_SECRET_PROVIDER

    # -- 本地数据目录（T0-15；仅字符串默认，解析/建目录在能力包中） --------
    data_dir: str = DEFAULT_DATA_DIR

    # -- 服务器工作区根目录（T2-55；server 档 Project / Attempt 宿主根） ----
    # ``ASTRA_WORKSPACE_ROOT``：Linux 默认 ``/var/lib/astra-ai/workspaces``。
    # 🔴 Project / Attempt 路径由服务端 UUID 派生；**禁止** API DTO 覆写本字段，
    #    客户端只接触不透明 ``checkout_ref``（不含宿主绝对路径）。
    workspace_root: str = DEFAULT_WORKSPACE_ROOT

    # -- Feature Flag（T0-21 / 决策 D7） -----------------------------------
    # ENV ``ASTRA_FEATURE_FLAGS``（JSON）或 config.yaml ``feature_flags``。
    # 合并优先级最高（覆盖默认与数据库覆盖）；空 = 全部按注册表默认（全开）。
    feature_flags: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_FEATURE_FLAGS))

    # -- 日志 ---------------------------------------------------------------
    log_level: str = DEFAULT_LOG_LEVEL
    log_format: Literal["json", "console"] = DEFAULT_LOG_FORMAT

    # -- 配置文件路径（供 loader 使用） -------------------------------------
    config_file: str | None = None

    # -- Phase 1 能力配置（T1-03；仅骨架，装配在 build_providers） ----------
    # Model Provider 默认（可选；空 = 未配置）。
    model_default_provider: str = DEFAULT_MODEL_PROVIDER
    model_default_model: str = DEFAULT_MODEL_NAME
    # Sandbox（T1-02 §5 #3 拍板）：local_process | docker；镜像基线定版。
    sandbox_provider: Literal["local_process", "docker"] = DEFAULT_SANDBOX_PROVIDER
    sandbox_image: str = DEFAULT_SANDBOX_IMAGE
    sandbox_workdir: str = DEFAULT_SANDBOX_WORKDIR
    # Sandbox 网络隔离（T2-56；设计 §2.18 / §2.8.1）：
    #  - offline（默认）：network=none；allowlisted：内部网络（无外部路由）+ 受控 Egress Proxy。
    #  - egress_network：ALLOWLISTED 接入的内部网络名（compose 创建，internal: true）。
    #  - egress_proxy_url：受控代理地址（注入沙箱容器 HTTP(S)_PROXY；判定复用 EgressPolicy）。
    sandbox_network_profile: Literal["offline", "allowlisted"] = DEFAULT_SANDBOX_NETWORK_PROFILE
    sandbox_egress_network: str = DEFAULT_SANDBOX_EGRESS_NETWORK
    sandbox_egress_proxy_url: str = DEFAULT_SANDBOX_EGRESS_PROXY_URL

    # -- Runtime / SSE（W6 · T1-31；设计 §2.9 / §2.16） --------------------
    # Run 级总超时（毫秒）：重启兜底扫描阈值（``RUNNING`` Run 心跳超期判定）。
    run_timeout_ms: int = DEFAULT_RUN_TIMEOUT_MS
    # SSE 心跳注释帧间隔（秒）：仅在空闲时发送，不带 ``id:``（不污染 ``Last-Event-ID``）。
    sse_heartbeat_seconds: int = DEFAULT_SSE_HEARTBEAT_SECONDS

    # -- 可观测（T1-04 / 设计 §2.7.3） -------------------------------------
    # ``observability.metrics_enabled``（社区默认 false）；ENV：
    # ``ASTRA_OBSERVABILITY__METRICS_ENABLED=true``，或 config.yaml ``observability:``。
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    # -- Worker / 队列（W1 · T2-02；设计 §2.9 / §2.16） ---------------------
    # ``ASTRA_REDIS_URL``：Team / server 任务队列连接串；空 = 未配置（回落占位）。
    redis_url: str = DEFAULT_REDIS_URL

    # -- 出网策略（W1 · T2-03；设计 §2.18） --------------------------------
    # ``ASTRA_EGRESS__*``（嵌套）：enabled / allow / deny_private / 超时 / 跳数 / 审计。
    egress: EgressSettings = Field(default_factory=EgressSettings)

    # -- Skill（W2 · T2-08；设计 §2.3 / W2 裁定 R14） ----------------------
    # ``ASTRA_SKILL__*``（嵌套）：builtin_dirs / plugin_dirs / workspace_dirs / 优先级。
    skill: SkillSettings = Field(default_factory=SkillSettings)

    # -- MCP（W2 · T2-11；设计 §2.4 / W2 裁定 R14） ------------------------
    # ``ASTRA_MCP__*``（嵌套）：connect/read 超时 / max_retries / enabled。
    mcp: McpSettings = Field(default_factory=McpSettings)

    # -- 审计（W3 · T2-17；设计 §2.18 / 裁定 R7 §7.3） ---------------------
    # ``ASTRA_AUDIT__*``（嵌套）：fallback_enabled / fallback_dir。
    audit: AuditSettings = Field(default_factory=AuditSettings)

    # -- Knowledge 能力（W5 · T2-27；设计 §2.6 / W5 裁定 B4 / B5） ----------
    # ``ASTRA_CAPABILITY__*``（嵌套）：vector_search（三态）/ embedding_dimensions。
    capability: CapabilitySettings = Field(default_factory=CapabilitySettings)

    # -- Memory 域（W6 · T2-33；设计 §2.7 / 裁定 B6 / §3.2 / §3.3） ---------
    # ``ASTRA_MEMORY__*``（嵌套）：extraction_enabled / token 上限 / 召回权重。
    memory: MemorySettings = Field(default_factory=MemorySettings)

    # -- 数据保留与清理（W9 · T2-48；设计 §2.19 / 裁定 R8） -----------------
    # ``ASTRA_RETENTION__*``（嵌套）：保留天数 / 批大小 / 保护名单 / 暂停。
    retention: RetentionSettings = Field(default_factory=RetentionSettings)

    @classmethod
    def settings_customise_sources(  # noqa: PLR0913 - 由 pydantic-settings 约定
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource | Any, ...]:
        """自定义配置来源优先级。

        顺序即优先级（前者覆盖后者）：init → env → .env → **config.yaml** → secrets 文件。
        ``config.yaml`` 来源通过 :func:`astra_config.loader.yaml_settings_source` 注入，
        此处**延迟导入**以避免模块级循环依赖。
        """
        from .loader import yaml_settings_source

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            yaml_settings_source(cast("type[Settings]", settings_cls)),
            file_secret_settings,
        )
