# `scripts/extract-from-py` — 契约抽取工具链（C-01 / C-02）

把**旧 Python 仓**（`D:/WBT/WBTimeAI_old`，只读）里的运行时可观测契约，导出成**新仓**（`D:/WBT/WBTimeAI`）`contracts/` 下的冻结产物。

本目录只做「抽取与校验」，不含任何业务代码，**不引入任何 TS/npm 依赖**。

---

## 1. 依赖

| 场景 | 依赖 |
| --- | --- |
| `run.py` 自身（含 `check`） | **仅 Python 标准库**，任意 3.9+ 解释器（实测 3.13.14 可跑 `check`） |
| 抽取器（`export_openapi.py` 等） | 旧仓 `.venv` 里已有的包（`fastapi` 等），**无需额外安装** |

抽取器必须由旧仓的虚拟环境解释器执行：

```
D:/WBT/WBTimeAI_old/.venv/Scripts/python.exe   # Python 3.12.10
```

不要用系统的 Python 3.11/3.13 去跑抽取器 —— 它们没有 `fastapi`，也没有旧仓的 `wbtime_ai_*` 包。
`run.py export` 会自动检测并 **re-exec** 到旧 venv 解释器（见 §4），所以你在命令行里用哪个 Python 启动并不重要。

---

## 2. 快速开始

```bash
cd /d/WBT/WBTimeAI

# 导出全部产物（首次/基线变更时）
python scripts/extract-from-py/run.py export

# 只导 OpenAPI（C-02）
python scripts/extract-from-py/run.py export --only openapi

# 校验已入库产物（不需要旧仓存在）
python scripts/extract-from-py/run.py check
```

### 退出码语义

| 码 | 含义 |
| --- | --- |
| `0` | 成功；`check` 全部摘要匹配 |
| `1` | `check` 校验不通过（文件缺失/被改动/存在未登记文件）；或某个抽取器执行失败 |
| `2` | 基座错误（源仓/解释器找不到、参数错误、`--only` 指定了未知抽取器） |

`check` 失败时**必须**返回非 0，CI 据此卡门禁。

---

## 3. `--source` 语义

优先级（高 → 低）：

1. 命令行 `--source PATH`
2. 环境变量 `WBTIME_SOURCE`
3. 默认值 `D:/WBT/WBTimeAI_old`

`--source` 接受三种写法，都会被规范化成 Windows 盘符形式（正斜杠）：

| 输入 | 规范化结果 |
| --- | --- |
| `/d/WBT/WBTimeAI_old`（Git Bash/MSYS） | `D:/WBT/WBTimeAI_old` |
| `D:\WBT\WBTimeAI_old`（反斜杠） | `D:/WBT/WBTimeAI_old` |
| `D:/WBT/WBTimeAI_old` | 原样 |

> ⚠️ **为什么必须做这一步**：Windows CPython 把 `/d/WBT/...` 解释成「当前盘符根下的 `d/WBT/...`」，即 `D:\d\WBT\...`，该路径不存在，于是所有 import 都 `ModuleNotFoundError`。`_bootstrap.to_native_source_path()` 负责转换；目录不存在时立即报错并退出码 2，不会静默降级。

`check` **完全不解析 `--source`**，因此旧仓被删除后依然可校验（实测见 §6）。

---

## 4. 为什么必须显式 `PYTHONPATH`，而不是依赖 `.venv` 的 editable 安装

这一点是本工具链存在的核心理由，已实测确认：

```
$ head -1 D:/WBT/WBTimeAI_old/.venv/Lib/site-packages/_editable_impl_wbtime_ai_database.pth
D:\WBT\WBTimeAI\packages\database\src
```

旧 venv 里 30 个 `_editable_impl_*.pth` 文件，内容是把**绝对路径写死**的，而且指向的是**新仓** `D:\WBT\WBTimeAI\packages\*` / `D:\WBT\WBTimeAI\apps\*`，不是旧仓。
后果有两个，都很危险：

1. `import wbtime_ai_database` 直接 `ModuleNotFoundError`（新仓还没有这些包）；
2. 即使新仓将来放了同名包，也会**静默导入到另一棵树**，产物不可信。

因此抽取器不依赖 editable 安装，而是由 `_bootstrap.enumerate_source_import_dirs()` 在运行时枚举 `<source>/packages/*/src` + `<source>/apps/{api,cli,worker}/src`，显式拼成 `PYTHONPATH`（同时写 `sys.path` 与 `os.environ`，子进程继承同一视图）。

作用域严格限制在 `--source` 之下，**旧仓只读、绝不写入**。

实测段数：**30** = 27 个 `packages/*/src` + `apps/api/src` + `apps/cli/src` + `apps/worker/src`。

手工复现（Git Bash）：

```bash
cd /d/WBT/WBTimeAI_old
W=$(pwd -W)   # -> D:/WBT/WBTimeAI_old
PP=$(for d in packages/*/src; do printf "%s;" "$W/$d"; done)$W/apps/api/src\;$W/apps/cli/src\;$W/apps/worker/src
PYTHONPATH="$PP" ./.venv/Scripts/python.exe -c "from wbtime_ai_api.main import create_app; print(len(create_app().openapi()['paths']))"
```

---

## 5. 文件说明

| 文件 | 职责 |
| --- | --- |
| `_bootstrap.py` | 路径基座：源仓解析、盘符规范化、`*/src` 枚举、`PYTHONPATH` 构建、解释器定位、re-exec 守卫、`ExtractContext` |
| `hashes.py` | `contracts/manifest.sha256` 的生成/解析/逐字节校验（含「未登记文件」检测） |
| `canonical.py` | **C-04 / C-05**：三处共用的规范化序列化（`ensure_ascii=False, indent=2, sort_keys=True` + 单个结尾 `\n`）与 UTF-8 落盘 |
| `export_openapi.py` | **C-02**：导出 `openapi.v1.frozen.json` + `endpoints.txt`，并硬校验三集合 |
| `export_envelope.py` | **C-04a**：导出 `envelope.schema.json`（响应壳，含活体探针形状） |
| `export_errors.py` | **C-04b**：导出 `errors.json`（30 个错误码 + HTTP 状态解析链） |
| `export_sse.py` | **C-05**：导出 `sse/channels.json` + 19 条 golden 帧 + 1 条浮点守卫样本 |
| `export_migration.py` | **C-06**：导出 `test-migration-map.csv`（1699 行处置决策）+ `test-migration-summary.json` + `conformance/*.yaml`（4 骨架，`source` 行号实测校验） |
| `migration/` | **C-06** 的实现：`classify.py`（§4.1 规则表）、`conformance.py`（骨架与行号校验）、`inventory.py`（账本读/采）、`build.py`（渲染）、两个 pytest 插件、`run_collect.py` / `run_suite.py`、`inputs/*.json` |
| `run.py` | CLI：`export` / `check`，抽取器自动注册与错误码 |

### 抽取器注册规约（供并行开发使用）

`run.py` 不硬依赖任何抽取器模块，按约定发现：

1. **内置**：本目录下 `export_*.py`，模块级需提供 `export(ctx)`，可选 `NAME` / `DESCRIPTION`。
2. **可选子包**：本目录下含 `__init__.py`、且名字不以 `_`/`.` 开头的子目录（例如 `ddl/`）。会尝试 import `<pkg>.exporter` 与 `<pkg>`，取 `EXPORTERS` / `exporters` / `EXPORTER` / `export` 中第一个存在的入口。
3. **可选散装脚本**：任意非 `_` 开头的子目录（**不要求** `__init__.py`）里的 `export_*.py`，按文件路径加载（加载期间临时把该子目录放进 `sys.path`，以便兄弟模块互相 import），同样需要模块级 `export(ctx)`。

统一降级规则：import 失败、缺少入口、命名重复 → 打印 `note: skip ...` 并**继续**，**不算失败**、不改变退出码。
这就是 `ddl/` 可以与 `run.py` 并行开发、互不阻塞的原因；`ddl/` 目录本身不由 C-01/C-02 创建或修改。

> ⚠️ **子包内「裸 import 兄弟模块」的坑**（C-03 实测踩到）：子包里的脚本若写 `import _env`，只有 `sys.path` 含**该子包目录**时才能解析。`python path/to/x.py` 直跑时 `sys.path[0]` 恰好是脚本目录所以能跑；但被 `run.py` 以模块方式导入时 `__package__` 非空，若脚本只在 `if __package__ in (None, ""):` 分支里插 `sys.path`，就会 `ModuleNotFoundError: No module named '_env'`。
> 正确写法：**无条件**把 `Path(__file__).resolve().parent` 插入 `sys.path`（C-03 已按此修正）。`run.py` 的第三类发现（散装 `export_*.py`）会临时注入子目录，但它只覆盖"按文件路径加载"这一路；走 `pkg.exporter` 这一路不受它保护。

> 现状（与 C-03 并行时的实测）：`ddl/export_ddl.py` 是独立 CLI（`main(argv)`，无 `export(ctx)`），因此被跳过：
> `note: skip optional script ddl/export_ddl.py: no callable 'export(ctx)' ...`。
> 若希望 `run.py export` 一次性跑完，C-03 只需三行适配（**由 C-03 自行决定是否添加，C-01 不做硬依赖**）：
>
> ```python
> # ddl/exporter.py
> from .export_ddl import main as _main
> NAME, DESCRIPTION = "ddl", "DDL freeze (three-source merge)"
> def export(ctx): return {"ddl_exit": _main(["--source", ctx.source])}
> ```

`ctx`（`_bootstrap.ExtractContext`）字段：`source` / `python_executable` / `pythonpath` / `repo_root` / `contracts_dir` / `script_dir`。
抽取器写入 `ctx.contracts_dir`；`export` 结束后 `run.py` 统一重建 manifest 并立即自校验。

---

## 6. C-02 冻结基线与实测证据

### 6.1 规范化序列化（唯一定义）

```python
json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
```

即：键排序、2 空格缩进、保留中文原文（不转 `\uXXXX`）、UTF-8 编码、**末尾恰好一个 `\n`**。

### 6.2 硬判据（实测，非推测）

| 判据 | 期望 | 实测 |
| --- | --- | --- |
| `info.version` | `0.4.8` | `0.4.8` ✅ |
| `len(spec["paths"])` | 100 | **100** ✅ |
| operations（path × method 展开） | 134 | **134** ✅ |
| `len(spec["components"]["schemas"])` | 116 | **116** ✅ |
| 业务 operation | 133 | **133** ✅ |

归一化产物摘要（`sha256` 前 12 位，2026-10-20 实测）：

```
28dd9c152dcb  contracts/openapi.v1.frozen.json   (355,846 B)
8130f716d659  contracts/endpoints.txt
```

### 6.3 为什么**禁止**用文件字节数当判据

同一份 spec，仅改序列化参数，字节数就会大幅波动（实测同一 spec、同一进程内）：

| 序列化参数 | 字节数 | sha256 前 12 位 |
| --- | --- | --- |
| `ensure_ascii=False, indent=2`（**本基线采用**） | 355,846 | `28dd9c152dcb` |
| `ensure_ascii=True, indent=2` | 375,593 | `e882d1bd4dc6` |
| `ensure_ascii=False, indent=4` | 510,981 | `2b8416bf7b6d` |
| 无缩进、单行 | 192,053 | `7f30337faeea` |

结论：**只看三集合 + 规范化 sha256**，字节数仅作参考信息记录。

### 6.4 `134` / `133` 分列口径（已实测核实，非猜测）

核实方式：对 `spec["paths"]` 逐 path × method 展开，按 operation 的 `tags` 分组，并与 `routers` 的实际装配对照。

实测结果：

```
health_router ops      = 1        -> GET /health
spec ops tagged health = 1        -> GET /health
spec ops non-health    = 133
total                  = 134      (134 条 (method, path) 全不重复)
非 /api/v1/ 前缀的 path = ['/health']        # 仅此一条
```

**结论**：`134` = 全量 operation；`133` = 业务 operation，口径为 **排除 tag 为 `health` 的 1 条非业务端点 `GET /health`**（`apps/api/src/wbtime_ai_api/routers/health.py`，经 `application.include_router(health_router)` 直接挂在根路径，不在 `/api/v1` 之下）。除此之外，**133 条业务 operation 全部以 `/api/v1/` 开头**，无例外。

#### 三种独立口径的集合等价性验证

为避免「按 tag 排除」与「按 path 前缀排除」在某些 spec 上不等价，用三套互不相同的实现各自求集合后逐一比对（实测三集合**完全相等**）：

```
A（排除 tag 含 health）        len = 133
B（排除 path 以 /health 开头） len = 133
C（排除 tag==health 且 path 前缀 /health 的交集）len = 133
A == B  集合相等: True
A == C  集合相等: True
A - B = []    B - A = []
A 中全部以 /api/v1/ 开头: True
134 - 133 = 1
```

另实测：`trace` 方法在全 spec 中不存在（方法集取 7 个或 8 个不影响计数）；`/metrics` 不在 spec 中。

对 `endpoints.txt` 本身的解析反证（按「忽略 `#` 行」规则切两段）：

```
SECTION A data lines = 134
SECTION B data lines = 133
A - B = ['GET /health']
B ⊆ A = True
B 中全部以 /api/v1/ 开头 = True
```

`endpoints.txt` 用两个显式分段登记该口径：

- `SECTION A -- ALL OPERATIONS (134 of 134)`：全量，含 `GET /health`；
- `SECTION B -- BUSINESS OPERATIONS (133 of 134)`：排除 `GET /health`，文件内**写死公式** `Rule: 133 = 134 - 1   (GET /health -- non-business contract surface)` 并注明 `Excluded: GET /health`。

解析规则：**忽略首个非空白字符为 `#` 的行**。机器可读的权威产物是 `openapi.v1.frozen.json`，`endpoints.txt` 是同一数据的人类/CI 友好扁平视图。

> `metrics` 端点（`/metrics`）默认**未启用**（`observability.metrics_enabled=False`），因此不出现在 134 之内；这是 `include_router` 的条件分支，实测确认。

---

## 7. `contracts/manifest.sha256` 格式

每行 `<64位sha256><两个空格><相对 contracts/ 的 POSIX 路径>`，按路径排序，UTF-8 + LF：

```
8130f716d659df435db70c83815f6001d3354de194674b4aa687cacfffb962b9  endpoints.txt
28dd9c152dcb65f15f4b4832563c1601d30ae122496eec5e2432fee4976dfc54  openapi.v1.frozen.json
```

- manifest 覆盖 `contracts/` 下**除自身**以外的所有文件，因此其他同事后续新增的产物（DDL/SSE/错误码等）在重跑 `export` 后自动纳入台账；
- 忽略 `*.pyc` / `__pycache__` / `*.tmp` / `*.bak`；
- `check` 同时检测三类问题：`missing`（登记了但文件没了）、`modified`（摘要不符）、`unrecorded`（在盘上但未登记）。

---

## 8. 实测命令与输出（可复现）

```bash
$ cd /d/WBT/WBTimeAI
$ python scripts/extract-from-py/run.py export
[export] re-executing under legacy interpreter: D:/WBT/WBTimeAI_old/.venv/Scripts/python.exe
[export] source: D:/WBT/WBTimeAI_old
[export] interpreter: D:/WBT/WBTimeAI_old/.venv/Scripts/python.exe
[export] contracts: D:/WBT/WBTimeAI/contracts
  PYTHONPATH segments: 30
  ...
[export] running openapi: Freeze create_app().openapi() into contracts/openapi.v1.frozen.json
  [ok] openapi version=0.4.8 paths=100 operations=134 business_operations=133 schemas=116 openapi_bytes=355846 sha256=28dd9c152dcb
[export] manifest written: D:/WBT/WBTimeAI/contracts/manifest.sha256
[export] OK: 2 artifact(s) recorded and verified
  8130f716d659  endpoints.txt
  28dd9c152dcb  openapi.v1.frozen.json
# exit 0

$ python scripts/extract-from-py/run.py check
[check] contracts dir: D:/WBT/WBTimeAI/contracts
[check] OK: 2 artifact(s) match manifest.sha256
  8130f716d659  endpoints.txt
  28dd9c152dcb  openapi.v1.frozen.json
# exit 0

# 篡改检测（追加一个换行）:
$ python scripts/extract-from-py/run.py check
[check] FAILED: modified: endpoints.txt expected 8130f716d659 got b6260b4c5eec
[check] 1 problem(s), 2 entr(ies) checked
# exit 1

# _old 不可用时依然可校验（证明 check 不依赖旧仓）:
$ WBTIME_SOURCE=/nope python scripts/extract-from-py/run.py check
# exit 0

# --source 不存在 -> 基座错误:
$ python scripts/extract-from-py/run.py export --source /d/WBT/NO_SUCH_DIR
[export] legacy source root not found: 'D:/WBT/NO_SUCH_DIR' (pass --source PATH or set $WBTIME_SOURCE)
# exit 2
```

---

## 9. 归零约定（C-3/M-4 联签条件）

`info.version = "0.4.8"` 是**代码串，从未发布**（旧仓未发布过任何版本）。

- 它可以用来标识**契约来源**；
- **不得**作为 TS 线的版本号继承。TS 线版本号由发布流程另行决定。

登记位置：`contracts/README.md`。

---

## 10. C-04 / C-05 抽取器（响应壳 / 错误码 / SSE）

三个 exporter 与 C-02 走同一套注册规约（模块级 `export(ctx)`），因此 `run.py export` 一条命令即可全部重生成，`run.py check` 一并纳入台账。

```bash
python scripts/extract-from-py/run.py export                      # 全部（openapi + envelope + errors + sse）
python scripts/extract-from-py/run.py export --only envelope,errors,sse
python scripts/extract-from-py/run.py check
```

| exporter | 产物 | 硬判据（不满足即非 0 退出，不静默写盘） |
| --- | --- | --- |
| `envelope` | `contracts/envelope.schema.json` | `_SUCCESS_CODE == 0`、`_SUCCESS_MESSAGE == "ok"`、4 个壳键、`ErrorResponse.required == [code, message]`、`MessageResponse.required == [message]`、`ErrorCode` 计数 == 30、**4 个路由族 2xx 响应 schema 的 `$ref` 与预期 `response_model` 逐一相等**（路由确实返回裸业务对象） |
| `errors` | `contracts/errors.json` | `ErrorCode` 计数 == 30、`exception.py` 异常类 == 7、`_STATUS_BY_CODE` 条目 == 27、**「仅由调用点解析」的码集合 == `{DEPENDENCY_MISSING: 503}`**、30 条描述齐全且无多余、**不存在 http_status 为 null 的码** |
| `sse` | `contracts/sse/channels.json` + `sse/golden/*.txt` | 通道数 == 19、顺序 == 9 core + 10 phase2、6 条改名逐条一致、`stream._DOMAIN_TYPES` 与通道表一致、`channel_for()` 未映射返回 `None`、19 条都对应一个真实事件类、未映射事件类 == 8、每条帧的行布局/紧凑分隔符/键序/无 CR/无 `\uXXXX` |

### 10.1 `summary` 约定

`run.py::_report_exporter` 原样打印 `openapi` 那套指标键。产物形态不同的 exporter（`envelope` / `errors` / `sse`）改为返回一个 `"summary"` 字符串，`run.py` 直接打印一行，例如：

```
  [ok] sse channels=19 core=9 phase2=10 golden=19 guard=1 floats=0 frame_bytes=2402 sha256=db80f7b3bcfd
```

### 10.2 只读纪律

三个 exporter 都只 **读** 旧仓：`install_import_paths()` 只改本进程的 `sys.path` / `PYTHONPATH`；产物一律写 `ctx.contracts_dir`。`D:/WBT/WBTimeAI_old` 与 `docs/`（独立 git 仓）零写入。

### 10.3 数值归一化的唯一实现

`export_sse.py::normalize_numbers` 是 SSE 数值格式的**唯一实现**（规则表见 `contracts/sse/README.md` §3 与 `channels.json` → `numeric_format`）。它作用在 payload 上、`encode_data_frame` 之前；旧仓编码器一行未改。新增通道若引入 `float` 参数，`_fallback_value` 会显式报错，强制走人工决策而不是悄悄引入不可比字节。

### 10.4 三级状态解析与调用点扫描（`errors`）

`http_status` 不是查一张表得来的，而是按运行期真实解析链取值：

1. `_STATUS_BY_CODE`（27 条）；
2. 异常类 `status_code` 回落（2 条）；
3. **调用点覆盖**（1 条）：`export_errors.py::_scan_call_sites` 用 `ast` 扫描 `<source>/{packages/*,apps/{api,cli,worker}}/src`，只认**字面量关键字参数** `code=ErrorCode.<NAME>` 与 `status_code=<int>`，不做正则猜测；无法解析的文件直接跳过（不静默信任）。

存在第 3 级的原因：`DEPENDENCY_MISSING` 在前两级都没有答案，但生产代码 `raise DomainError(..., status_code=503)` 显式覆盖，且旧仓集成测试断言 `503 + {"code":"DEPENDENCY_MISSING"}`。若只做到第 2 级就会错标 `null`；若凭常识填 500 更是编造。三级链把它钉成 **503** 并列出 8 处覆盖点。

改动这一层时的硬约束：`EXPECTED_CALL_SITE_RESOLVED = {"DEPENDENCY_MISSING": 503}`，并且**任何码落到 null 都直接失败**（`codes without any HTTP status`），不允许「留空待补」。

---

## 11. C-06 迁移映射表与 conformance 骨架（`export_migration.py` + `migration/`）

产物三个：`contracts/test-migration-map.csv`（1699 行）、`contracts/test-migration-summary.json`（口径与统计）、`contracts/conformance/*.yaml`（4 骨架）。

### 11.1 为什么用 pytest 插件，而不是解析 `--collect-only` 的 stdout

旧仓 `pyproject.toml` 的 `addopts` 自带 `-q`；命令行再加 `-q` 就是 `-qq`，输出退化成 `文件: 数量`，**每个 test id 都不见了**。所以采集走 `pytest_collection_modifyitems` 钩子：

| 插件 | 作用 | 触发方式 |
| --- | --- | --- |
| `migration/wbtime_migration_collect.py` | 把 `nodeid` + `markers` 写成 JSON | `--collect-only -p wbtime_migration_collect` |
| `migration/wbtime_migration_outcome.py` | 把每条用例的真实结果写成 JSON | `-p wbtime_migration_outcome`（真跑） |

插件在 `--collect-only` 前就拿到 `Item` 对象，**markers 与 nodeid 都不依赖 verbosity**，也不需要 grep 文本。

### 11.2 三口径与「1661 vs 1699」

实测（2026-10-20）：

```
-d addopts= --collect-only  → 1743 tests collected in 12.14s      # raw，含 provider_live
provider_live 标记         → 44
select(result)             → 1699                                # = 直接跑 pytest 的 collected 集合
```

路线图登记的 **1661** 是 **passed 口径**（旧线记录「1692 selected = 1661P」）。差 **38** 条。

**本轮已跑完全量**（`-o addopts= -m 'not provider_live'`，17 分 36 秒）：

```
1668 passed, 23 skipped, 44 deselected, 8 xfailed in 1056.01s   # exit 0，1699/1699 全覆盖
```

对账（两个差都是 +7，非通过数都是 31）：

```
selected 1699 − 旧线 1692 = +7
passed   1668 − 路线图 1661 = +7
非通过   23 + 8 = 31 = 1692 − 1661 = 31
```

⇒ 差额**完全由新增 7 条用例解释**：既有用例一条未丢、一条未退化。若按 1661 裁剪，反倒会把新增的 7 条通过用例一起裁掉。

**本表按 collected 全量（1699）覆盖，不裁剪。** 理由：映射表的语义是「每个旧用例的处置决策」，与它当前是否通过无关；按 passed 裁剪会让那 38 条 skip/xfail 用例**没有处置记录**——正好是最容易被无声丢掉的部分。

登记位置（四处，同一句话）：

1. `contracts/test-migration-map.csv` 表头注释；
2. `contracts/README.md` §「旧用例迁移映射（C-06）」；
3. 本节 §11.2；
4. `contracts/test-migration-summary.json` → `basis.roadmap_registered_1661`。

`outcome` 列**如实标注**，取值域 `passed/failed/skipped/xfailed/xpassed/error/unknown`。**`unknown` = 本轮未复跑，不是「通过」**；`build.py` 里不存在任何把缺失结果默认成 `passed` 的路径。

### 11.3 输入账本（`migration/inputs/`）

| 文件 | 生产者 | 何时重生成 | 耗时 |
| --- | --- | --- | --- |
| `collect.json` | `migration/run_collect.py` | 旧仓测试树变化时；`export` 发现缺失也会自动重采 | ≈12 s |
| `outcomes.json` | `migration/run_suite.py` | 想让 `outcome` 列变成真实结果时（可选）。**当前已入库**（2026-10-20 全量，exit 0） | 数十分钟（实测 17m41s，含 PG/Docker 切片） |

`export` **不会**自己去跑全量套件——CI 里跑一次 40 分钟的测试只为重生成一张映射表是不可接受的。缺 `outcomes.json` 时全部登记 `unknown`，summary 里 `outcomes.ledger = null` 明示这一点。

### 11.4 规则表（`migration/classify.py`）

`CLASSIFICATION_RULES` 是**有序、首个命中生效**的规则表，键是相对路径 regex，值是 `(capability, bucket, target_module, target_version, note)`：

- `bucket` 直接取路线图 §4.1 归并总表的 ①/②/③；
- `target_version` 取 §3.2 的「产品版 → 工程期」映射（基座 V0.1.0 / 身份 V0.2.0 / 运行时 V0.3.0 / 知识 V0.4.0 / 编排 V0.5.0 / 工作区完整档 V0.6.0 / 插件 V0.7.0 / 应用层 V0.8.0 / 制度 V1.0.0）；
- **顺序是有意义的**：`tests/unit/test_domain_workspace.py` 必须先命中 workspace 规则，再轮到通用的 `test_domain_*`。

无法判定时的行为：`strict=True` ⇒ `export` **直接失败**并把未匹配路径全部列出（`UnmatchedPathError`）。**不填 `TBD` 蒙混过关**，也不猜版本号。当前 214 个文件 **0 未匹配**。

### 11.5 `source` 行号是实测的，不是手抄的

`migration/conformance.py` 里每个 `SourceRef` 有 `file` / `line` / `quote` / `why`。`build.write_artifacts` 会打开旧仓该行，断言 `quote` 逐字出现在该行：

```
SourceVerificationError: tenant-404: quote not found at tests/integration/test_cross_tenant_404.py:3
  expected fragment: '越权（跨租户）返回 404 而非 403'
  actual line      : '...'
```

⇒ 写错行号 / 旧仓变动 **立刻让 `export` 变红**，编造行号无法存活。当前 4 个骨架共 **24** 条引用全部通过（tenant-404: 5、idempotency: 6、content-negotiation: 6、stringly-contracts: 7）。

### 11.6 实测输出

```bash
$ python scripts/extract-from-py/run.py export --only migration
[export] running migration: Test migration map (1699 rows) + conformance skeletons (4 YAML)
  [ok] migration rows=1699 files=214 bucket=1:333/2:1363/3:3 case_overrides=4 collected=1743 \
       selected=1699 outcome_covered=1699 conformance=4 refs=24 sha256=eb95b086db7e
[export] contract manifest: contract-manifest.json objects=38 by_source={'manual': 29, 'metadata': 9} criteria=23 pending=none
[export] manifest written: D:/WBT/WBTimeAI/contracts/manifest.sha256
[export] OK: 39 artifact(s) recorded and verified
[export] OK: dual ledger consistent (38 object record(s))
# exit 0

# 幂等性：连续两次 export，4 个产物字节不变（实测 md5sum -c 全 OK）

$ python scripts/extract-from-py/run.py check
[check] OK: 39 artifact(s) match manifest.sha256
[check] OK: dual ledger consistent (contract-manifest.json)
# exit 0
```

分布（`test-migration-summary.json`）：

| bucket | 行数 | target_version 分布（行数） |
| --- | --- | --- |
| ① 原样移植 | 333 | V0.1.0 240 / V0.2.0 194 / V0.3.0 503 / V0.4.0 121 / V0.5.0 206 / V0.6.0 253 / V0.7.0 82 / V0.8.0 63 / V1.0.0 37 |
| ② 需重设计 | 1363 | 同上（另 +1：`test_unmapped_mcp_tool_is_fail_closed_and_roundtrips`，逐用例覆盖，D-2；合计 1699） |
| ③ 放弃或合并 | 3 | `permission/test_*_permissions_redirect.py` 的旧端点快照类用例（每条 note 各自写明断言与放弃理由） |

> **逐用例覆盖（`migration/classify.py::CASE_OVERRIDES`）**：文件级规则按"能力簇"判定，粒度不足以表达"同一文件里
> 3 条是旧端点 shim、1 条是 API 级 fail-closed 安全断言"。上表 ② 的 `+1 / ③` 的 `−1` 就是这条覆盖的净效果：
> 该用例（`mcp_tool_id` 未同步进 `tool` 表 ⇒ 拒绝写运行期判定源 + 告警 + 契约往返）是全仓唯一的 fail-closed 断言，
> 已改判 ②（`@wbtime/mcp` / V0.2.0）并列进 `contract_manifest.MUST_NOT_BE_DROPPED`（`C23` 守门）。
> **4 条覆盖的 note 各不相同**——共用同一段文本会让处置不可审计（D-2 的伴随缺陷）。

> **与路线图「桶① ~357」差 −24**：路线图该数是估算（原文带 `~`）。本表逐条判定，差异集中在 `audit`（§4.1 未单列该簇，本表按身份同版推定 ②，`note` 内标「⚠️ 推定项」）与 plugin 扩展点 interface（路线图 ① / 本表 ②，ABI 换语言后断言必须重写）。两个值都保留原文，未做任何一边的凑数。

### 11.7 只读纪律

- 旧仓只读：采集/真跑都以 `cwd=<source>` 启动子进程，产物一律写本仓 `scripts/extract-from-py/migration/inputs/` 与 `contracts/`；
- 不写旧仓 `tests/`、不改 `docs/`（独立 git 仓）；
- 全流程只用标准库（`json` / `csv` / `subprocess` / `re`），无 PyYAML 依赖：YAML 由 `render_yaml()` 直接产出（JSON 标量是合法的 YAML 1.2 双引号标量），并已用 `yaml.safe_load` 回读校验 4/4。


---

## 12. C-07 对象台账（`contract_manifest.py`）

### 12.1 为什么需要第二本台账

`manifest.sha256` 只能回答「字节变没变」。它不能回答「这份 CSV 是 metadata 编译来的，还是迁移链扒出来的」「这个 golden 帧服务哪条 DoD」。`contracts/contract-manifest.json` 补上这两问，并**与 sha256 台账交叉锁定**：任一文件在两本台账中的 sha256 不同 ⇒ 直接抛 `ManifestConsistencyError`，`export` 拒绝落盘、`check` 判红。两份台账打架比没有台账更糟（`施工纪律.md` §4.5.1-2 要的是唯一台账，不是两个说法）。

### 12.2 写入顺序（不能颠倒）

1. 各 exporter 产物落盘；
2. `contract_manifest.write()` → `contract-manifest.json`（对象集合 = 除两本台账外的全部文件）；
3. `hashes.write_manifest()` → `manifest.sha256`（**覆盖**第 2 步产物，所以它必须在后）；
4. `contract_manifest.verify()` 双向复核（磁盘 ↔ 对象台账 ↔ sha256 台账）。

对象台账无法包含自身摘要，因此第 2 步的交叉比对针对「除两本台账外的交集」——这正是两本台账被要求一致的集合。

### 12.3 分类方法论：读产物、不猜

- 22 条规则按 `fnmatch` 顺序匹配（具体在前），每条带 `requirement` + `rationale`；
- 产物**自带** `generated_by` 的（`errors.json`、`sse/channels.json`、`envelope.schema.json` 的 `x-wbtimeai`、两份 `normalized.json`、`test-migration-summary.json`）→ 与规则表**比对**，冲突即红；
- 产物**没有规则** → 判红并列出文件名，提示去 `CLASSIFICATION_RULES` 登记（**默认值 `manual` 是禁止的**，那等于把"没想过"伪装成"已判定"）；
- `generated_by` 为人写产物时写 `null`，不硬塞一个 exporter 名。

### 12.4 判据总账（`criteria[]`，C1–C20）

数字全部**现读产物算出**，不抄文档：

| 组 | 判据 | 期望 | 来源 |
| --- | --- | --- | --- |
| C1–C3 | openapi paths / operations / schemas | 100 / 134 / 116 | `openapi.v1.frozen.json`（复用 `export_openapi.collect_operations`，不重复实现） |
| C4–C8 | DDL 表 / 列 / metadata 索引 / raw hnsw / 索引对象合计 | 61 / 629 / 174 / 2 / 176 | 两份 `normalized.json` 自带的 `counts` |
| C9 | SQLite 方言专属对象分解 | `reconciled` | 实测 `1 虚表 + 4 影子表 + 3 触发器`；DoD 写「5 影子表」= 1 虚表 + 4 影子表的合并口径（外部内容表不生成 `_content` 影子表） |
| C10–C12 | SSE 通道 / golden 帧 / 通道覆盖率 | 19 / 19 / 全覆盖 | `sse/channels.json` + `sse/golden/`（守卫夹具不计入 19） |
| C13–C14 | 错误码 / 响应壳顶层键 | 30 / 4 | `errors.json`、`envelope.schema.json` |
| C15 | 迁移映射 collected/selected | 1699 | CSV 实测行数，并与 `summary.rows` 交叉 |
| C16 | 迁移映射 passed 口径 | 1661（旧线登记） | **自适应**：`outcomes.covered>0` ⇒ 报实测 passed（当前 1668，标 `reconciled`，差额 Δpassed=+7 与 Δselected=+7 同步、非 passed 恒为 31）；`covered=0` ⇒ 只报登记值并降级 `registered`，禁止冒充实测 |
| C17–C18 | 可复现工具链 + 两本台账存在 | 全在 | 文件存在性实测 |
| C19–C20 | conformance 骨架数 / C-06 自带摘要 ↔ 磁盘 | 4 / 一致 | `summary.conformance`、`summary.artifacts` |

`status` 语义：`verified`（实测=期望）/ `reconciled`（口径已对齐并写明差额原因）/ `registered`（**登记值，非本轮实测**）/ `pending`（产物未落盘，不判红）/ `mismatch`（判红）。

### 12.5 负例（先红后绿）

```
未登记产物         → [export] FAILED ... unclassified artifact(s) ... : stray.unknown     exit 1
篡改一个字节        → [check] FAILED: modified: errors.json expected e93c0165819a got 0090c3c11355
                      [check] FAILED: errors.json: object ledger digest ... != disk ...
                      [check] FAILED: errors.json: sha256 ledger ... != object ledger ...   exit 1
删掉对象台账        → [check] FAILED: missing: contract-manifest.json                     exit 1
恢复                → [check] OK: 39 artifact(s) match manifest.sha256
                      [check] OK: dual ledger consistent (contract-manifest.json)         exit 0
```

### 12.6 当前分类分布

实测 `objects=38`：`manual 29 / metadata 9 / migration 0`；`dialect_only`：`null 34 / pg 2 / sqlite 2`。另有 `ddl_objects=245`（见 12.7），其中 `migration` **10 条**——**迁移来源在对象级可追溯，只是文件级没有独立产物**（2 条 hnsw 与 FTS5 8 个对象内嵌在 DDL 四件套里，文件按主导来源归 `metadata`）。

三个曾改判的对象（都被证据推翻过一次，记录在此以免再被"顺手改回去"）：

| 文件 | 判定 | 判据 |
| --- | --- | --- |
| `test-migration-map.csv` | **manual** | 判定依据是「谁产生了内容」：`bucket`/`target_version`/`outcome`/`note` 全是人做的迁移决策；`test_id`/`file`/`markers` 虽由 pytest 内省，只占三列 |
| `envelope.schema.json` | **manual** | 产物自带 `x-wbtimeai.provenance`：6 个 `$defs` 里只有 `ErrorResponse` / `MessageResponse` 是 `pydantic:` 反射，其余 4 个壳层 + `enforcement` 表全是 `manual+measured:` ⇒ 壳层如何组装由人定 |
| `errors.json` | **metadata**（保留） | 产物 `sources` 把每个规范性字段指到代码位置（`ErrorCode` 枚举 / `exception.py` / `_STATUS_BY_CODE` / AST 扫描），`http_status_source` 实测 `api_status_map 27 + exception_class 2 + call_site_override 1`；人工部分被限定为 30/30 条 `description` 且逐条标 `description_source=manual` ⇒ 描述是注记不是规范事实 |

`db/type-map.csv` 的 `ts_target` / `strategy` 两列属人工映射策略，已在 rationale 里显式登记，故仍判 `metadata`（其余四列是编译事实）。

### 12.7 `ddl_objects[]`：M-10 的对象级两列

文件级 `source` 会把 2 条 `migration` 来源的 hnsw 藏起来（`schema.v0018.pg.sql` 整体只能标一个值），所以 M-10「**每个对象**带 `source` + `dialect_only`」必须在对象级落地。`ddl_objects[]` 直接从两份 normalized 快照派生（**不新建文件、不重新抽**）：

| kind | 条数 | `source` | `dialect_only` | 数据来源 |
| --- | --- | --- | --- | --- |
| `table` | 61 | `metadata` | `null` | `pg.tables[]`（与 sqlite 的表名集合逐项相等，已断言） |
| `index.metadata` | 174（unique 7 / partial 1） | `metadata` | `null` | `pg.tables[].indexes[]` |
| `index.raw_hnsw` | 2 | `migration` | `pg` | `pg.raw_indexes[]`，`source_raw` 保留 `migration:...:293` 原文 |
| `virtual_table` | 1 | `migration` | `sqlite` | `sqlite.dialect_only[]` |
| `shadow_table` | 4 | `migration` | `sqlite` | 同上，附 `source_note` 说明"无人工 DDL，是 FTS5 引擎产物" |
| `trigger` | 3 | `migration` | `sqlite` | 同上 |
| **合计** | **245** | | | |

断言（写在 `_build_ddl_objects()` 里，条数不符即 `export` 拒绝落盘）：

```
len(ddl_objects) == 245
kind 分布 == {table:61, index.metadata:174, index.raw_hnsw:2, virtual_table:1, shadow_table:4, trigger:3}
dialect_only=pg == 2      dialect_only=sqlite == 8
source=migration == 10    （= 2 hnsw + 8 sqlite；若 != 10 说明某处 source 标错）
表名集合 PG == SQLite；列数合计 629 == counts.columns
tables/metadata_indexes/raw_indexes/index_objects_total/dialect_only_objects == 快照 counts
```

`C21 ddl_objects.total` 把上述条数与 `C6 metadata_indexes=174` / `C7 raw_hnsw=2` / `C8 index_objects_total=176` / `C9 sqlite dialect_only=8` 显式交叉。

> `source_raw` 的归一化不是猜测：`raw_indexes[].source` 原文就以 `migration:` 开头；`dialect_only[].source` 原文是 `sqlite_master（执行 0013 FTS5 语句后回读）`——DDL 文本源自迁移 0013，`sqlite_master` 只是回读通道，故归 `migration` 并保留原文。影子表则额外标 `source_note`，说明它没有人工书写 DDL（是执行 FTS5 定义时引擎自动生成），归属其声明来源。

### 12.8 `field_semantics` / `status_semantics`

`source` 与 `generated_by` 回答的是两个不同问题，**两者不同不构成矛盾**；只有 `source` 与「内容实际由谁决定」不符才是错误。这句话连同三个字段的正反向约束、4 个真实样例一起写进台账的 `field_semantics` 段，避免下一个人再把 `manual + generated_by` 当成 bug 改掉。

`criteria[].status` 的五个取值也在 `status_semantics` 里定义：`verified` / `reconciled`（与文档口径不一致但判定为文档错误，产物按实测）/ `registered`（登记值、无实测）/ `pending` / `mismatch`（判红）。`reconciled` 存在的意义就是**不假装相等**。
