"""配置层默认值常量。

集中管理默认配置，避免散落在各处；被 :mod:`astra_config.settings` 与
:mod:`astra_config.loader` 复用。
"""

from __future__ import annotations

from typing import Literal

#: 默认运行模式（决策 D4）：local | server
DEFAULT_MODE: Literal["local", "server"] = "local"

#: 应用元信息
DEFAULT_APP_NAME = "Astra AI"
DEFAULT_APP_VERSION = "0.1.0"

#: HTTP 服务默认监听地址
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

#: 日志默认值
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT: Literal["json", "console"] = "console"

#: 默认数据库连接串（local 模式：SQLite）
DEFAULT_DATABASE_URL = "sqlite:///./astra_local.db"

#: 默认 config.yaml 文件名（可被 ASTRA_CONFIG_FILE 覆盖）
DEFAULT_CONFIG_FILE_NAME = "config.yaml"

#: 默认本地数据目录（local 模式：存储根；派生 storage/ 等子目录）。
#: 注意：仅作字符串默认值，路径解析（expanduser）与目录创建在能力包中进行。
DEFAULT_DATA_DIR = "~/.astra-ai"

#: 服务器工作区根目录（T2-55；server 档 Project / Attempt 宿主根）。
#: 🔴 Linux 部署默认（由 Astra 服务账号拥有）；允许管理员覆写，**不可**由 API 客户端指定。
#: Project / Attempt 路径由服务端 UUID 派生（``projects/<id>/repo``、``executions/<id>/...``）。
DEFAULT_WORKSPACE_ROOT = "/var/lib/astra-ai/workspaces"

# -- 安全默认值（T0-12） -----------------------------------------------------

#: JWT 签名算法。
DEFAULT_JWT_ALGORITHM = "HS256"

#: access token 有效期（秒，默认 15 分钟）。
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900

#: refresh token 有效期（秒，默认 14 天）。
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 1_209_600

#: 连续登录失败锁定阈值。
DEFAULT_LOGIN_MAX_ATTEMPTS = 5

#: 锁定时长（秒，默认 15 分钟）。
DEFAULT_LOGIN_LOCK_SECONDS = 900

#: 机密提供者类型（Phase 0：env）。
DEFAULT_SECRET_PROVIDER: Literal["env"] = "env"

# -- Phase 1 可选配置默认值（T1-03 / T1-04） ---------------------------------

#: Model Provider / Model 默认值（可选；空 = 未配置，显式路由时由 Model Router 报错）。
DEFAULT_MODEL_PROVIDER = ""
DEFAULT_MODEL_NAME = ""

#: Sandbox Provider 形态（T1-02 §5 #3 拍板）：local_process | docker。
#: 社区默认 local_process（进程级隔离，A-5 承诺）；Team/Compose 下用 docker。
DEFAULT_SANDBOX_PROVIDER: Literal["local_process", "docker"] = "local_process"

#: Sandbox 镜像基线（§5 #3 定版）：Docker 沙箱使用。
DEFAULT_SANDBOX_IMAGE = "python:3.12-slim"

#: Sandbox 工作目录挂载点（可选；空 = 由 SandboxProvider 自行解析为 Workspace 目录）。
DEFAULT_SANDBOX_WORKDIR = ""

#: 可观测：``/metrics`` 开关（§2.7.3）；社区默认关闭，Team 可开。
DEFAULT_METRICS_ENABLED = False

# -- Runtime / SSE（W6 · T1-31；设计 §2.9 / §2.16） --------------------------

#: Run 级总超时（毫秒，兜底扫描阈值）；与 ``astra_domain.DEFAULT_RUN_TIMEOUT_MS`` 一致。
#: 重启兜底扫描据此判定 ``RUNNING`` Run 是否心跳超期（置 ``FAILED`` / ``HEARTBEAT_TIMEOUT``）。
DEFAULT_RUN_TIMEOUT_MS = 900_000

#: SSE 心跳注释帧间隔（秒，默认 15s）；仅在空闲时发送。
DEFAULT_SSE_HEARTBEAT_SECONDS = 15


# -- Worker / 队列（W1 · T2-02；设计 §2.9 / §2.16） -------------------------

#: Redis 连接串（Team / server 任务队列；空 = 未配置，``task_queue`` 回落占位）。
#: 仅当**非空**且 ``astra-task[redis]`` 就位时，server 装配 ``RedisTaskQueue``（W1 裁定 §3.2）。
DEFAULT_REDIS_URL = ""


# -- 出网策略（W1 · T2-03；设计 §2.18） -------------------------------------

#: 出网策略总开关（默认开）；配合空 ``allow`` ⇒ **默认拒绝全部出网**。
DEFAULT_EGRESS_ENABLED = True

#: 是否强制拒绝私网 / 环回 / 链路本地 / 元数据等拒段（**不可被 ``allow`` 覆盖**）。
DEFAULT_EGRESS_DENY_PRIVATE = True

#: 出网连接超时（秒）。
DEFAULT_EGRESS_CONNECT_TIMEOUT_SECONDS = 10.0

#: 出网读取超时（秒）。
DEFAULT_EGRESS_READ_TIMEOUT_SECONDS = 30.0

#: 重定向最大跳数（逐跳校验；超限即拒）。
DEFAULT_EGRESS_MAX_REDIRECTS = 5

#: 是否记录**放行**审计（默认仅记拒绝；``action="egress.request"``）。
DEFAULT_EGRESS_LOG_ALLOWED = False


# -- Skill（W2 · T2-08；设计 §2.3 / W2 裁定 R14） ----------------------------

#: 内置 Skill 目录（相对仓库根）。
DEFAULT_SKILL_BUILTIN_DIRS: list[str] = ["plugins/skills"]

#: 插件提供的 Skill 目录（随之装配）。
DEFAULT_SKILL_PLUGIN_DIRS: list[str] = []

#: 工作区 Skill 目录（部署方配置）。
DEFAULT_SKILL_WORKSPACE_DIRS: list[str] = []

#: 来源覆盖优先级（高 → 低）。
DEFAULT_SKILL_OVERRIDE_PRIORITY: list[str] = ["workspace", "plugin", "builtin"]


# -- MCP（W2 · T2-11；设计 §2.4 / W2 裁定 R14） ------------------------------

#: MCP 建连超时（秒）。
DEFAULT_MCP_CONNECT_TIMEOUT_SECONDS = 10.0

#: MCP 读取超时（秒）。
DEFAULT_MCP_READ_TIMEOUT_SECONDS = 30.0

#: MCP 最大重试次数。
DEFAULT_MCP_MAX_RETRIES = 2

#: MCP 功能总开关。
DEFAULT_MCP_ENABLED = True


# -- 审计（W3 · T2-17；设计 §2.18 / 裁定 R7 §7.3） ---------------------------

#: 审计写入失败是否降级本地落盘（**不静默丢弃**）。
DEFAULT_AUDIT_FALLBACK_ENABLED = True

#: 审计降级落盘目录（空 = 由 sink 回退 ``~/.astra-ai/audit-spool/``）。
DEFAULT_AUDIT_FALLBACK_DIR = ""


# -- Knowledge（W5 · T2-27；设计 §2.6 / W5 裁定 B4 / B5 / §5） ----------------

#: 向量检索能力（三态，B5）：``None`` = 由组合根按 dialect + ``pg_extension`` 探测解析
#: （SQLite → ``False``；PG → 探测 ``vector`` 扩展）；显式 ``True`` / ``False`` 覆盖优先。
DEFAULT_VECTOR_SEARCH: bool | None = None

#: ``embedding.vector`` 单列固定维度（＝ 部署级单维度，B4；默认 1536）。
DEFAULT_EMBEDDING_DIMENSIONS = 1536

#: 默认分块大小（字符 / 近似 token，§5 #7 首批 ``fixed``）。
DEFAULT_CHUNK_SIZE = 800

#: 默认分块重叠（字符 / 近似 token）。
DEFAULT_CHUNK_OVERLAP = 100


# -- Memory（W6 · T2-33；设计 §2.7 / 裁定 B6 / §3.2 / §3.3） -----------------

#: 记忆抽取开关（§5 #10；默认开，**可关闭**）。
DEFAULT_MEMORY_EXTRACTION_ENABLED = True

#: 单次记忆抽取 token 上限（NFR N4：抽取前后 ``token_usage`` 差值 ≤ 上限）。
DEFAULT_MEMORY_EXTRACTION_TOKEN_LIMIT = 2000

#: 记忆召回默认条数（top-k）。
DEFAULT_MEMORY_RECALL_TOP_K = 10

#: 召回权重中的重要度系数（``score = importance_weight × importance × …``）。
DEFAULT_MEMORY_IMPORTANCE_WEIGHT = 1.0

#: 召回时效半衰期（天；``recency = 0.5 ** (age_days / half_life)``）。
DEFAULT_MEMORY_RECENCY_HALF_LIFE_DAYS = 30.0


# -- 数据保留与清理（W9 · T2-48；设计 §2.19 / 裁定 R8） ----------------------

#: ``agent_event`` 保留天数（设计给定）。
DEFAULT_RETENTION_AGENT_EVENT_DAYS = 90

#: ``message`` 保留天数（R8）。
DEFAULT_RETENTION_MESSAGE_DAYS = 90

#: ``tool_call`` 保留天数（R8）。
DEFAULT_RETENTION_TOOL_CALL_DAYS = 90

#: ``audit_log`` 保留天数（设计给定）。
DEFAULT_RETENTION_AUDIT_LOG_DAYS = 180

#: 每批删除行数（分批提交，避免长事务锁表；设计给定）。
DEFAULT_RETENTION_BATCH_SIZE = 1000

#: 保护名单（``retention.protected``）：显式**表名 / 行 ID** 名单；命中则跳过清理
#: （替代对 Phase 1 表加 ``pinned`` 列，裁定 R7）。
DEFAULT_RETENTION_PROTECTED: list[str] = []

#: 远程对象保留（W4 后增量的**接口位**；本波 **inert**，``None`` = 未启用）。
DEFAULT_RETENTION_REMOTE_ATTEMPT_CLONE_DAYS: int | None = None
DEFAULT_RETENTION_REMOTE_ARTIFACT_DAYS: int | None = None
DEFAULT_RETENTION_REMOTE_LOG_DAYS: int | None = None

#: 紧急暂停开关（``True`` 时清理器整体不动作）。
DEFAULT_RETENTION_PAUSED = False


# -- Feature Flag（T0-21 / 决策 D7） -----------------------------------------

#: Feature Flag 配置覆盖默认值；空 = 全部按注册表默认（全开）。
#: 合并优先级（高 → 低）：配置覆盖 → 数据库覆盖 → 默认(全开)。
DEFAULT_FEATURE_FLAGS: dict[str, bool] = {}

#: 不允许从 config.yaml 明文读取的敏感键（仅允许经由 ENV / secrets/ 提供）
SENSITIVE_KEYS = frozenset({"secret_key", "database_url_password"})

__all__ = [
    "DEFAULT_MODE",
    "DEFAULT_APP_NAME",
    "DEFAULT_APP_VERSION",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_DATABASE_URL",
    "DEFAULT_CONFIG_FILE_NAME",
    "DEFAULT_DATA_DIR",
    "DEFAULT_WORKSPACE_ROOT",
    "DEFAULT_JWT_ALGORITHM",
    "DEFAULT_ACCESS_TOKEN_TTL_SECONDS",
    "DEFAULT_REFRESH_TOKEN_TTL_SECONDS",
    "DEFAULT_LOGIN_MAX_ATTEMPTS",
    "DEFAULT_LOGIN_LOCK_SECONDS",
    "DEFAULT_SECRET_PROVIDER",
    "DEFAULT_FEATURE_FLAGS",
    "SENSITIVE_KEYS",
    "DEFAULT_MODEL_PROVIDER",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_SANDBOX_PROVIDER",
    "DEFAULT_SANDBOX_IMAGE",
    "DEFAULT_SANDBOX_WORKDIR",
    "DEFAULT_METRICS_ENABLED",
    "DEFAULT_RUN_TIMEOUT_MS",
    "DEFAULT_SSE_HEARTBEAT_SECONDS",
    "DEFAULT_REDIS_URL",
    "DEFAULT_EGRESS_ENABLED",
    "DEFAULT_EGRESS_DENY_PRIVATE",
    "DEFAULT_EGRESS_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_EGRESS_READ_TIMEOUT_SECONDS",
    "DEFAULT_EGRESS_MAX_REDIRECTS",
    "DEFAULT_EGRESS_LOG_ALLOWED",
    "DEFAULT_SKILL_BUILTIN_DIRS",
    "DEFAULT_SKILL_PLUGIN_DIRS",
    "DEFAULT_SKILL_WORKSPACE_DIRS",
    "DEFAULT_SKILL_OVERRIDE_PRIORITY",
    "DEFAULT_MCP_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_MCP_READ_TIMEOUT_SECONDS",
    "DEFAULT_MCP_MAX_RETRIES",
    "DEFAULT_MCP_ENABLED",
    "DEFAULT_AUDIT_FALLBACK_ENABLED",
    "DEFAULT_AUDIT_FALLBACK_DIR",
    "DEFAULT_VECTOR_SEARCH",
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    # Memory（W6 · T2-33）
    "DEFAULT_MEMORY_EXTRACTION_ENABLED",
    "DEFAULT_MEMORY_EXTRACTION_TOKEN_LIMIT",
    "DEFAULT_MEMORY_RECALL_TOP_K",
    "DEFAULT_MEMORY_IMPORTANCE_WEIGHT",
    "DEFAULT_MEMORY_RECENCY_HALF_LIFE_DAYS",
    # 数据保留与清理（W9 · T2-48）
    "DEFAULT_RETENTION_AGENT_EVENT_DAYS",
    "DEFAULT_RETENTION_MESSAGE_DAYS",
    "DEFAULT_RETENTION_TOOL_CALL_DAYS",
    "DEFAULT_RETENTION_AUDIT_LOG_DAYS",
    "DEFAULT_RETENTION_BATCH_SIZE",
    "DEFAULT_RETENTION_PROTECTED",
    "DEFAULT_RETENTION_REMOTE_ATTEMPT_CLONE_DAYS",
    "DEFAULT_RETENTION_REMOTE_ARTIFACT_DAYS",
    "DEFAULT_RETENTION_REMOTE_LOG_DAYS",
    "DEFAULT_RETENTION_PAUSED",
]
