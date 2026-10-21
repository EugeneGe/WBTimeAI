# `contracts/` — 契约冻结基线（V0.0.1）

本目录存放从**旧 Python 仓**（`D:/WBT/WBTimeAI_old`，只读）抽取的运行时契约产物，用于 TS 线开工前的「契约继承与抽取」。除本文件与 `sse/README.md` 两份说明外，所有文件均为**机器生成**，请勿手改；改动请改抽取器并重跑。

> **V0.3.0 增量（2026-10-21，用户批准）**：`v0019` 在 `v0018` 之上加 `agent_run.stop_reason` 1 列、`RunResponse`/`RunOut` 的 `stop_reason` 与 `status` 七值枚举；来源 `manual`，v0018 五文件**未改**。登记与复现见 [`v0019.README.md`](v0019.README.md)。

## 产物登记

| 文件 | 内容 | 生成方式 |
| --- | --- | --- |
| `openapi.v1.frozen.json` | `create_app().openapi()` 规范化冻结件（`ensure_ascii=False, indent=2, sort_keys=True` + 单个结尾换行） | `python scripts/extract-from-py/run.py export --only openapi` |
| `endpoints.txt` | 全部 operation 的 `METHOD PATH` 扁平清单，分「全量 134」/「业务 133」两段 | 同上 |
| `envelope.schema.json` | 响应壳 JSON Schema（draft 2020-12）：**成功壳** `{code:0, message:"ok", data, request_id}` + **失败壳** `{code, message, data, request_id}` + 简单消息壳 | `export --only envelope` |
| `errors.json` | **30** 个 `ErrorCode` 全量：`code` / `http_status` / `python_exception` / `description` | `export --only errors` |
| `sse/channels.json` | **19** 条 SSE 通道：`domain_type` / `channel` / `phase` / `payload_fields` / `golden` / `golden_sha256` + 帧格式 + 数值格式 + 流语义 | `export --only sse` |
| `sse/golden/*.txt` | **19** 条 golden 帧（逐字节可比）+ **1** 条浮点守卫样本 `_guard-float-normalization.txt` | 同上 |
| `sse/README.md` | SSE 通道契约说明（**手写**，纳入台账） | — |
| `test-migration-map.csv` | 旧仓**每个 pytest 用例**的处置决策（1699 行）：`bucket` ①/②/③ + `target_module` + `target_version` + `outcome` + `note` | `export --only migration` |
| `test-migration-summary.json` | 映射表的机器可读统计与口径登记（collected/selected/passed 三口径、bucket/version/outcome 分布、输入输出 sha256） | 同上 |
| `conformance/*.yaml` | 4 个一致性契约**骨架**（`tenant-404` / `idempotency` / `content-negotiation` / `stringly-contracts`），`source` 的文件:行号在导出时逐条实测校验 | 同上 |
| `manifest.sha256` | 本目录产物的 sha256 台账（`<sha256>  <相对路径>`，按路径排序） | `export` 结束时自动重建 |

## 实测基线（2026-10-20）

| 项 | 值 |
| --- | --- |
| `info.version` | `0.4.8` |
| `paths` | 100 |
| operations | 134 |
| `components.schemas` | 116 |
| 业务 operation | 133（= 134 − `GET /health`） |

摘要（前 12 位，实测；**权威台账以 `manifest.sha256` 为准**，本表仅便于人眼速查）：

```
d29fbeafd3af  endpoints.txt
28dd9c152dcb  openapi.v1.frozen.json
6c6759dd138c  envelope.schema.json
9d2f47b12c68  errors.json
db80f7b3bcfd  sse/channels.json
5e88718d569c  sse/golden/_guard-float-normalization.txt
caadddb883a8  sse/README.md
```

校验：

```bash
python scripts/extract-from-py/run.py check   # 0 = 通过，非 0 = 不通过；不依赖旧仓存在
```

## 双台账（C-07）— `contract-manifest.json` + `manifest.sha256`

两本台账**必须逐字节一致**，否则 `run.py check` / `run.py export` 都判红（双真相源比没有台账更糟）：

| 台账 | 回答什么问题 | 形态 |
| --- | --- | --- |
| `manifest.sha256` | 「这个文件还是原来那份字节吗」 | 扁平：`<sha256>  <相对路径>`，按路径排序 |
| `contract-manifest.json` | 「这个文件是什么、从哪来、服务哪条判据」 | 每对象一条记录 + 判据总账 + 声明 |

`contract-manifest.json` 的 `objects[]` 每条**恰好六个字段**：

| 字段 | 取值约束 |
| --- | --- |
| `path` | 相对 `contracts/` 的 POSIX 路径 |
| `sha256` | 该文件实际 sha256（64 位），与 `manifest.sha256` 同值 |
| `source` | **严格三选一**：`metadata`（ORM metadata / 代码内省）/ `migration`（迁移链 raw DDL）/ `manual`（人写骨架） |
| `dialect_only` | **严格三选一**：`pg` / `sqlite` / `null`（跨方言通用） |
| `generated_by` | 产生它的 exporter；人写产物为 `null` |
| `requirement` | 服务的判据（`DoD#n` / `总纲 §x` / `M-n`） |

- 分类**按实质**判定，规则表 + 理由写在 `scripts/extract-from-py/contract_manifest.py::CLASSIFICATION_RULES`；
- **未登记产物直接判红**（fail-closed）——新契约文件必须显式分类，禁止默认套 `manual`；
- 产物若自带 `generated_by`（如 `errors.json`、`sse/channels.json`、`schema.*.normalized.json`、`test-migration-summary.json`），与规则表**交叉校验**，冲突即红。

`criteria[]` 是判据总账（C1–C23）：三集合 `100/134/116`、DDL `61 表 / 629 列 / 174+2=176`、`19` SSE 通道、`30` 错误码、迁移映射 `1699 collected / 1661 passed 口径`、可复现性，外加两条**防回归语义门禁**——`C22`（`errors.http_status_uniformity`：`http_status` 不得掩盖 call-site 差异，D-1）与 `C23`（`migration.disposition_auditability`：桶③ 理由逐条成立、`MUST_NOT_BE_DROPPED` 不得被判放弃，D-2）。**每个数字都是现读产物算出来的**；其中 `1661` 标注 `status: registered`——因为 summary 的 `outcomes.covered = 0`（未在任何一轮复跑），按 `passed` 统计会变成编造。

`notices[]` 固化七条不可丢失的约定：`M-4`（`info.version = 0.4.8` 为代码串、从未发布、不得继承）、`M-08`（字节数不可作判据）、`405 口径作废`（62 已含 2 个 `VectorType`，`+2` 是重复计数；只认 401 / 403）、`SQLite 方言专属对象 8 个`（虚表 1 + 影子表 4 + 触发器 3，文档「5 影子表」作废）、`PG 未在真实例重放`（不得表述为「PG 已验证」）。

### 对象级两列（`ddl_objects[]`，M-10）

文件级 `source` 一个值装不下"主体是 metadata、内含 2 条 migration 来源 hnsw"的 DDL，所以另设 `ddl_objects[]`：**245 条**对象级记录（61 表 / 174 metadata 索引 / 2 raw hnsw / SQLite 1 虚表 + 4 影子表 + 3 触发器），每条带自己的 `source` 与 `dialect_only`，并保留 C-03 快照里的原始来源串 `source_raw`。条数与方言分布是**硬断言**：不符则 `export` 拒绝落盘，`check` 退出码 1。

`field_semantics` 段写死三个字段各自的语义：`source` = 内容事实从哪来，`generated_by` = 哪个程序落盘，两者不同**不构成矛盾**（例如 golden 帧：载荷人写、编码器落盘）。

重建 / 校验：

```bash
python scripts/extract-from-py/run.py export      # 重建两本台账（幂等）
python scripts/extract-from-py/run.py check       # 两本台账 + 磁盘三方比对
python scripts/extract-from-py/contract_manifest.py --summary   # 逐对象摘要
```

> `criteria[].status` 的状态码含义（`verified` / `reconciled` / `registered`）与 `DoD#5` 三口径
> （collected 1699 / passed 1668 / registered 1661）的读法见 `docs/契约基线.md` §2.1；
> **本目录台账只承载事实，读法在文档层**（台账的权威是 `contracts/manifest.sha256` 与
> `contracts/contract-manifest.json`，口径解释一律回文档，避免双真相源）。

## 响应壳（C-04）— `envelope.schema.json`

**实测（非设计文档口径）**：

| 项 | 事实 |
| --- | --- |
| 成功壳 | `{code: 0(int), message: "ok", data: <裸业务对象>, request_id: <uuid>}` —— 由 `ResponseShellMiddleware` 套壳 |
| 失败壳 | `{code: "<ErrorCode 字面值>", message, data, request_id}` —— 由 `errors.py::register_exception_handlers` 直接产出，**不经**中间件 |
| 四顶层键 | 成功 / 失败**恒在 4 键**（实测 4/4 探针用例） |
| `code` 类型 | 成功 = **integer 0**；失败 = **string** —— 同一组键、不同类型，**不得**用同一个 TS 类型写死 |
| `data` | 成功时是**裸业务对象**（无二级 `{data:…}` 外壳）；失败时缺省 `{}` |
| `request_id` | 与响应头 `X-Request-Id` 同源（实测 4/4：`body.request_id == header`） |
| 不套壳的响应 | SSE（`text/event-stream`）、`/openapi.json`、非 JSON、`status >= 400`、空 body、已是壳的响应 |

`ErrorResponse` / `MessageResponse` 两个 pydantic 模型由 `model_json_schema()` **原样导出**（未手抄），放在 `$defs` 下；线上壳层（success / message）是实测 + 手工组织，逐条标注 `source`。`x-wbtimeai.runtime_probe` 内嵌活体探针结果（只记录**形状**：顶层键、每键 JSON 类型、`request_id` 是否等于响应头——真实 `request_id` 是每次请求新生成的 UUIDv7，记录其值会破坏可复现性）。

> OpenAPI 文档里**没有** `ErrorResponse`：所有 2xx 直接 `$ref` 业务模型，422 用 FastAPI 自动的 `HTTPValidationError`。错误壳只能从 `errors.py` + 活体探针取值，这也是本文件存在的理由。

### 壳是**怎么生效**的（`x-wbtimeai.enforcement`）

「响应壳契约」不能只写模型长什么样，必须写清生效路径。以下三点全部实测：

**（1）成功响应确实包了一层壳 —— 裸对象只是「路由返回值」**

从 `create_app().openapi()` 实测 4 个路由族的 `response_model`，并核对其路由是 `return <业务对象>`（不是 `return {code:…}`）：

| 路由族 | operation | 2xx | 实测 `response_model` | 路由实际 `return` | 引用 |
| --- | --- | --- | --- | --- | --- |
| agents | `POST /api/v1/agents` | 201 | `AgentResponse` | `return _to_agent_response(dto)` | `routers/v1/agents.py:112,130` |
| agents（数组） | `GET /api/v1/agents` | 200 | `array<AgentResponse>` | `return [_to_agent_response(dto) for dto in …]` | `routers/v1/agents.py:133,143` |
| workspaces | `POST /api/v1/workspaces` | 201 | `WorkspaceResponse` | `return _to_response(dto)` | `routers/v1/workspaces.py:55,73` |
| runs | `GET /api/v1/runs/{run_id}` | 200 | `RunResponse` | `return _to_run_response(dto)` | `routers/v1/runs.py:36` |

⇒ 客户端看到的是 `{code:0, message:"ok", data:<该 response_model 的实例>, request_id}`。**`data` 可能是对象，也可能是数组**（`GET /agents` 即数组）。

中间件栈（`main.py:40-46`，Starlette `add_middleware` 后加者更靠外）：

```
CORSMiddleware  ⇢  ResponseShellMiddleware  ⇢  RequestContextMiddleware  ⇢  route
```

`RequestContextMiddleware` 先加（更内层）以生成 `X-Request-Id`，`ResponseShellMiddleware` 后加（更外层）才能复用它 ⇒ 「响应体 request_id == 响应头」。`main.py` 注释原文即如此写。

**（2）失败响应由谁产生** —— `errors.py::register_exception_handlers` 的 4 个处理器，全部**绕过**中间件（`dispatch` 在 `status >= 400` 时提前 return，避免二次包裹）：

| 处理器 | 覆盖 | 状态规则 | `data` |
| --- | --- | --- | --- |
| `_domain_error_handler` | `DomainError` 及其子类 | `_STATUS_BY_CODE.get(code, exc.status_code)` | `exc.to_dict()['data']` |
| `_validation_error_handler` | `RequestValidationError` | 恒 422 | `{errors: [...]}` |
| `_http_exception_handler` | Starlette `HTTPException` | 原样保留 | `{}` |
| `_unhandled_exception_handler` | 未捕获 `Exception` | 恒 500 | `{}` |

**（3）四字段是否恒定** —— 键**恒在**，值**不一定**：

| 字段 | 键 | 值 |
| --- | --- | --- |
| `code` | 恒在 | 成功 = **integer `0`**；失败 = **string**（30 种 `ErrorCode`）—— 同一组键、不同类型，**TS 侧不得用同一类型写死，必须按 status 分支判别** |
| `message` | 恒在 | 成功恒为 `"ok"`；失败为人类可读文本（可能中文） |
| `data` | 恒在 | 成功 = 裸业务对象；失败缺省 `{}`，但**可带上下文**：实测 `422 → {errors:[…]}`、`DEPENDENCY_MISSING(503) → {capability:"remote_tasks"}` |
| `request_id` | 恒在 | **值可为 `null`**（无请求上下文时）；与 `X-Request-Id` 同源，实测 4/4 相等 |

旧仓自身用例也钉了同一件事（已登记在 `enforcement.legacy_test_evidence`）：`tests/integration/test_api_2c_surface.py::_assert_shell`（4 处调用覆盖 `/projects`、`/workspaces/{id}/files|environment`、`/approvals`、`/tasks`）、`_create_workspace`（业务 `id` 取 `_shell_data(created)['id']` ⇒ 对象在 `data` 内）、`tests/unit/test_response_shell_value_judgement.py`（「已是壳」是**值判定**而非键判定）。

## 错误码（C-04）— `errors.json`

**30** 个 `ErrorCode` 全量。`http_status` 按运行期**实际解析链**三级取值，并记录每一级的输入与来源标记 `http_status_source`：

| 级 | 来源 | 命中数 | 说明 |
| --- | --- | --- | --- |
| 1 | `errors.py::_STATUS_BY_CODE`（`http_status_by_api_map`） | 27 | API 层的操作性映射表 |
| 2 | 异常类 `status_code`（`http_status_by_exception_class`） | 2 | `_STATUS_BY_CODE` 缺席时的回落：`UNKNOWN`(500)、`INTERNAL_ERROR`(500) |
| 3 | 调用点 `status_code=` 覆盖（`http_status_by_call_site`） | 1 | 前两级皆缺席时，AST 扫描 `<source>/{packages/*,apps/*}/src` 中 `code=ErrorCode.X` 的构造点，逐点取值 |

> ⚠️ **`http_status` 是「逐 call-site 解析后的多数值」，不是「该码恒为此值」的承诺。**
> 判读顺序：先看 `http_status_uniform` ——
> `true` = 全部构造点一致；`false` = 构造点之间**不一致**，此时必须再看 `http_status_distribution`；
> `null` = 该码无构造点，不做一致性声明。下游（V0.2.0 参数化测试、TS 侧）**一律按 call-site 取值**，
> 不得直接把 `http_status` 当成全量断言。


状态分布（实测，30 条全部有值，**无 null**）：

| 状态 | 数量 | 备注 |
| --- | --- | --- |
| 401 | 5 | `UNAUTHORIZED` + 4 个 `AUTH_*`（凭证类） |
| 403 | 1 | `PERMISSION_DENIED` |
| 404 | 7 | `NOT_FOUND` + 6 个 `*_NOT_FOUND` |
| 405 | 1 | `METHOD_NOT_ALLOWED` |
| 409 | 3 | `CONFLICT` / `USER_ALREADY_EXISTS` / `IDEMPOTENCY_KEY_REUSE` |
| 410 | 1 | `EVENT_CURSOR_EXPIRED` |
| 422 | 4 | `VALIDATION_ERROR` / `CONFIGURATION_ERROR` / `MAX_ITERATIONS` / `CONTEXT_LENGTH_EXCEEDED` |
| 423 | 1 | `AUTH_ACCOUNT_LOCKED` |
| 429 | 1 | `RESOURCE_LIMIT_EXCEEDED` |
| 500 | 3 | `UNKNOWN` / `INTERNAL_ERROR` / `HEARTBEAT_TIMEOUT` |
| 501 | 1 | `NOT_IMPLEMENTED` |
| 503 | 1 | `DEPENDENCY_MISSING` —— 见下（**8 处 call-site 显式 503，2 处回落 500；非全量成立**） |
| 504 | 1 | `TOOL_TIMEOUT` |

### `DEPENDENCY_MISSING`：**8 处 503 + 2 处 500，取决于 call-site**

它既不在 `_STATUS_BY_CODE`，也没有专属异常类，`DomainError` 的类默认值是 500。逐点扫描生产代码后得到的事实是**分裂的**：

```
显式 status_code=503（8 处）
apps/api/src/wbtime_ai_api/routers/v1/projects.py:77,143        status_code=503
apps/api/src/wbtime_ai_api/routers/v1/tasks.py:173,186          status_code=503
packages/workspace/src/.../change_review_service.py:648,759,778 status_code=503
packages/workspace/src/.../remote_task_service.py:1258          status_code=503

未传 status_code ⇒ 回落 DomainError 默认 500（2 处）
packages/knowledge/src/wbtime_ai_knowledge/parser/base.py:66    missing_dependency_error()
packages/plugin/src/wbtime_ai_plugin/marketplace/serialize.py:50
```

⇒ `http_status = 503` 是 **10 处构造点中的多数值**，`http_status_uniform = false`，实测分布 `http_status_distribution = {"503": 8, "500": 2}`。
两条偏离点在 `http_status_inconsistent_call_sites` 里逐条列出（`{file, line, actual_status, status_origin}`），
全部 10 点连"谁决定了这个状态"一起列在 `http_status_by_call_site_resolved`（`status_origin` ∈
`api_status_map` / `call_site_explicit` / `exception_class_default` / `domain_error_default`）。
`status_code_overrides` 保留 8 条**显式覆盖**的原始事实（D-1 要求不得删）。

**为什么这条必须写清**：`knowledge/parser/base.py::missing_dependency_error()` 被 pdf / docx / html 三个解析器共用。
用户装漏 `pypdf` 上传 PDF 时，接口实际返回 **500**，而不是契约里那个更"好看"的 503。
`http_status_by_call_site: [503]` 这种只列"拿到 503 的"写法会**主动掩盖** 500 的路径——那是缺陷，不是简化。

旧仓用例 `tests/integration/test_api_2c_surface.py::test_workspace_files_503_when_unassembled` 钉的是 **503 那条路径**
（`status_code == 503` 且 `json()["code"] == "DEPENDENCY_MISSING"`）——它证明 503 **存在**，不证明 503 **全量**。

机器门禁：`export_errors.py::EXPECTED_NON_UNIFORM_CODES` 冻结了这条分裂（`{"500": 2, "503": 8}`），
`contract-manifest.json` 的 `C22` 再把「分布 vs 逐点明细 vs note」三方对账；任何一侧被改动而其它侧没跟上，`export` 直接红。


### `python_exception: null` + `python_exception_unmapped: true` —— 共 22 个

`exception.py` 只声明 7 个异常类（`NotFoundError` / `ValidationError` / `ConflictError` / `PermissionDeniedError` / `UnauthorizedError` / `NotImplementedYetError` / 基类 `WBTimeAIError`），加上 `error.py::DomainError`（承载 `UNKNOWN`）共覆盖 **8** 个码；其余 22 个码**没有专属异常类**，由 `DomainError(code=..., data=...)` 显式携带：

```
METHOD_NOT_ALLOWED, CONFIGURATION_ERROR, DEPENDENCY_MISSING,
AUTH_INVALID_CREDENTIALS, AUTH_TOKEN_EXPIRED, AUTH_TOKEN_INVALID,
AUTH_TOKEN_REVOKED, AUTH_ACCOUNT_LOCKED,
TENANT_NOT_FOUND, USER_NOT_FOUND, USER_ALREADY_EXISTS, ORGANIZATION_NOT_FOUND,
WORKSPACE_NOT_FOUND, TASK_NOT_FOUND, CREDENTIAL_NOT_FOUND,
RESOURCE_LIMIT_EXCEEDED, MAX_ITERATIONS, CONTEXT_LENGTH_EXCEEDED, TOOL_TIMEOUT,
IDEMPOTENCY_KEY_REUSE, HEARTBEAT_TIMEOUT, EVENT_CURSOR_EXPIRED
```

> 这 22 条**都有确定的 HTTP 状态**（30 条全有），所以 `unmapped` 全为 `false`。`python_exception_unmapped` 只表达「没有专属异常类」，与「状态未知」是两件事 —— 不要混用。

**调用点规模**：AST 扫描共找到 **387** 处 `code=ErrorCode.X` 构造点，覆盖 **25** 个错误码（另 5 个码只由框架层 `HTTPException` 反查产生，代码里没有显式构造）。逐码计数见 `codes.*.raise_site_count`，模块清单见 `raise_site_modules`。

### ⚠️ 与 `docs/00-整体设计.md` §11.2 已知偏差

| 码 | 设计表 | 代码（契约取此项） |
| --- | --- | --- |
| `VALIDATION_ERROR` | 400 | **422** |
| `UNAUTHENTICATED`（设计命名） | — | 实际字面值 **`UNAUTHORIZED`** |
| `NOT_IMPLEMENTED_YET`（设计命名） | — | 实际字面值 **`NOT_IMPLEMENTED`** |

设计表**不是**契约来源；一切数字取自实跑。

## SSE（C-05）

19 条通道 + 19 条 golden 帧 + 1 条浮点守卫样本，全部细节（帧格式、通道表、数值格式、流语义、`seq` 口径）见 **`sse/README.md`**。要点：

- `channel` 与 `domain_type` 有 **6 条不同名**（如 `agent.message → message.delta`）；
- 帧内 JSON 为 `ensure_ascii=False, separators=(",",":"), sort_keys=False`（CJK 不转义、无空格、**保插入序**）；
- 数值上帧前归一化为「只有整数」（浮点 → `int` 或 6 位定点字符串），19 条正式载荷实测 **0 个浮点**，故 golden 字节 == 旧仓真实输出；
- 事件包 27 个事件类中 8 个**不产帧**（`channel_for()` 返回 `None`）；
- OpenAPI 把这 4 个 SSE 端点声明成 `application/json`（OpenAPI 无法表达 SSE）——TS 代码生成必须排除它们。

## 旧用例迁移映射（C-06）— `test-migration-map.csv` / `conformance/*.yaml`

### 三口径登记（**1661 vs 1699 差异在此登记**）

| 口径 | 值 | 怎么来的 |
| --- | --- | --- |
| collected（raw） | **1743** | `pytest --collect-only -o addopts=`（清空 addopts，含 `provider_live`） |
| `provider_live` 排除 | **44** | `pyproject.toml` 的 `addopts = "-q -m 'not provider_live' …"` 默认排除 |
| **selected** | **1699** | = 1743 − 44 ⇒ **直接跑 `pytest` 的 collected 集合**，**本表行数口径** |
| 路线图登记 | **1661** | **passed 口径**（旧线记录「1692 selected = 1661P」） |
| 今日实测 outcome | **passed 1668 / skipped 23 / xfailed 8** | 2026-10-20 全量复跑：`1668 passed, 23 skipped, 44 deselected, 8 xfailed in 1056.01s`，**exit 0**，1699/1699 全覆盖 |

**`1661` 与 `1699` 差 38 条**，原因是口径不同（passed vs collected），**不是**用例丢失。已实测对账：

```
selected  1699 − 旧线 1692 = +7        # 采集集合多了 7 条
passed    1668 − 路线图 1661 = +7      # 通过数正好多 7 条
非通过    23 skipped + 8 xfailed = 31 = 旧线 1692 − 1661 = 31   # 一个不多一个不少
```

⇒ **差额完全由新增的 7 条用例解释**，既有用例一条未丢、一条未退化。这也反向验证了「按 collected 覆盖」是正确口径：若按 1661 裁剪，会连这 7 条新增用例也一并裁掉。

- 本表**按 collected 全量覆盖**——映射表的语义是「每个旧用例的处置决策」，与它当前是否通过无关。若按 passed 裁剪，那 38 条 skip/xfail 用例将**没有处置记录**，正好是最容易被无声丢掉的部分；
- `outcome` 列**如实标注**每条的实际结果；未复跑的标注 `unknown`（**不是** `passed`）；
- **禁止**为凑 1661 而裁剪行，**禁止**改路线图里的 1661。

复现（旧仓只读，不写入）：

```bash
cd /d/WBT/WBTimeAI_old
W=$(pwd -W)
PP=$(for d in packages/*/src; do printf "%s;" "$W/$d"; done)$W/apps/api/src\;$W/apps/cli/src\;$W/apps/worker/src
MIG=D:/WBT/WBTimeAI/scripts/extract-from-py/migration
WBTIME_MIGRATION_OUT=D:/WBT/tmp/collect.json PYTHONPATH="$PP;$MIG" \
  ./.venv/Scripts/python.exe -m pytest --collect-only -q -p wbtime_migration_collect -o addopts= tests
# 实测: 1743 tests collected in 12.14s
```

### 实测分布（2026-10-20）

文件数 **214**，用例数 **1699**（每行一个用例）。

| bucket | 行数 | 含义（路线图 §4.1） |
| --- | --- | --- |
| ① 原样移植 | **333** | 语义与判据可原样搬（权限矩阵 / 跨租户 404 / 工作流状态机 / 评测 scorer / 前端） |
| ② 需重设计 | **1363** | 能力延续，实现与门禁重写 |
| ③ 放弃或合并 | **3** | 仅 3 条：`permission/test_*_permissions_redirect.py` 的**旧端点快照类**用例（`/mcp/permissions`、`/tools/permissions` 在 TS 线不存在）；每条 `note` 各自写明「断的是什么 / 为什么放弃」 |

**同文件内不同桶**：`permission/test_*_permissions_redirect.py` 里有一条**不属于** redirect shim 的用例——
`test_unmapped_mcp_tool_is_fail_closed_and_roundtrips`（`mcp_tool_id` 未同步进 `tool` 表 ⇒ **拒绝写运行期判定源** + 告警 + 契约往返）。
它是全仓**唯一**一处 API 级 fail-closed 断言，已单独判 ②（`@wbtime/mcp` / V0.2.0）：
`test_single_chain` 的 5 条是**单元级** checker 断言，**不覆盖**它。逐用例覆盖清单见
`migration/classify.py::CASE_OVERRIDES`，落表后由 `C23` 门禁（`MUST_NOT_BE_DROPPED` + 桶③ note 不得复用）守住。


按目标版本：`V0.1.0` 240 / `V0.2.0` 194 / `V0.3.0` 503 / `V0.4.0` 121 / `V0.5.0` 206 / `V0.6.0` 253 / `V0.7.0` 82 / `V0.8.0` 63 / `V1.0.0` 37（合计 1699）。

> **与路线图「桶① ~357 用例」的差异**：本表 333，差 **−24**。路线图该数是**估算值**（原文带 `~`），本表按 `migration/classify.py` 的规则表**逐条**判定；差异集中在 `audit`（路线图 §4.1 未单列该簇，本表按「身份与多租户」同版推定 ②，已在 `note` 标注「⚠️ 推定项」）与 plugin 扩展点 interface（路线图给 ①，但 ABI 换语言后断言必须重写，本表判 ②）。**两个口径都保留原值**，未做任何一边的凑数。

### 4 个一致性契约骨架

| 文件 | 不变量 | `applies_to` | source 引用 / cases |
| --- | --- | --- | --- |
| `conformance/tenant-404.yaml` | 跨租户访问 → **404**（不是 403/401） | V0.2.0 | 5 / 4 |
| `conformance/idempotency.yaml` | 同键同体复用首次结果；同键异体·跨用户 → **409** `IDEMPOTENCY_KEY_REUSE` | V0.1.0, V0.5.0 | 6 / 5 |
| `conformance/content-negotiation.yaml` | `Accept` 协商 + `Content-Type`；**SSE 帧不套壳** | V0.1.0, V0.3.0 | 6 / 5 |
| `conformance/stringly-contracts.yaml` | 枚举字面值 / ISO-8601 UTC / UUIDv7 形态 / 复合键格式 | V0.1.0 | 7 / 5 |

全部 `status: skeleton`：只固定不变量与种子用例，完整参数化矩阵（如 I-1 的 ≥11 资源族）由所属版本补齐。

**`source` 的每个 `file` + `line` + `quote` 在导出时逐条校验**：`export_migration.build.write_artifacts` 会打开旧仓对应行的文本，若 `quote` 不在该行就直接让 `export` 失败。因此**行号不可能被编造**——改动旧仓或写错行号，`export` 立刻红。

### 生成与校准

```bash
# 只重生成映射表 + 骨架（约 1 秒；输入是已冻结的 inputs/*.json）
python scripts/extract-from-py/run.py export --only migration

# 旧仓测试树变了 → 重采采集账本（约 12 秒，不执行用例）
python scripts/extract-from-py/migration/run_collect.py

# 想让 outcome 列为真实结果 → 跑全量（数十分钟，含需 PG/Docker 的切片）
python scripts/extract-from-py/migration/run_suite.py
```

## ⚠️ 版本号联签约定（C-3 / M-4 条件）

**`info.version = "0.4.8"` 是代码串，从未发布。**

- 它只标识**契约来源**，可用于追溯；
- **不得**作为 TS 线的版本号继承。TS 线版本号由发布流程独立决定，任何以 `0.4.8` 作为 `package.json` 起始版本的写法均视为违规。

## 134 / 133 分列口径

- `134` = OpenAPI 文档中全部 operation（path × method 展开）；
- `133` = 业务 operation，口径为**排除 tag 为 `health` 的唯一非业务端点 `GET /health`**；
- 实测确认：除 `GET /health` 外，其余 133 条 operation **全部**以 `/api/v1/` 开头。

详见 `scripts/extract-from-py/README.md` §6.4 的核实过程与原始输出。
