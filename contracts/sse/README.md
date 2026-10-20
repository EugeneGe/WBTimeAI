# `contracts/sse/` — SSE 通道契约与 golden 帧（C-05）

本目录是 SSE 的**唯一契约来源**：19 条通道名、每条通道的 `data:` 载荷形状、以及 19 条**逐字节可比**的 golden 帧。

| 文件 | 内容 | 生成方式 |
| --- | --- | --- |
| `channels.json` | 19 条通道全量定义（`domain_type` / `channel` / `phase` / `payload_fields` / `golden` / `golden_sha256`）+ 帧格式 + 数值格式 + 流语义 | `run.py export`（`export_sse.py`） |
| `golden/<channel>.txt` | **19** 条正式 golden 帧，一条通道一文件，内容是该帧的完整字符串（含 `id:` / `event:` / `data:` 与结尾空行） | 同上 |
| `golden/_guard-float-normalization.txt` | **第 20 条**：浮点归一化的**守卫样本**，**不属于** 19 条正式通道 | 同上 |
| `README.md` | 本文件。**手写维护**（唯一非机器生成的成员，但同样纳入 `manifest.sha256`） | — |

重生成 / 校验（不要手改任何生成物）：

```bash
cd /d/WBT/WBTimeAI
python scripts/extract-from-py/run.py export --only sse   # 重生成
python scripts/extract-from-py/run.py check               # 校验 sha256 台账
```

---

## 1. 帧格式（实测，非设计推测）

数据帧模板（`encoder.encode_data_frame`）：

```
id: {seq}\nevent: {channel}\ndata: {json}\n\n
```

行布局固定为 5 段（4 个 LF + 结尾空行）：

```
id: 1
event: message.delta
data: {"run_id":"run_01","message_id":"msg_01","role":"assistant","delta":"你好，世界"}

```

硬约束（生成器逐条断言，不靠"我写的时候是对的"）：

- 帧内**不得**出现 `CR` —— 只允许 LF；
- 必须以**空行**结尾（`\n\n`），不得追加换行；
- `data:` 的 JSON 为 `ensure_ascii=False, separators=(",", ":"), sort_keys=False`：
  - `ensure_ascii=False` ⇒ **CJK 原样输出**，不得出现 `\uXXXX`（`message.delta` 的 golden 就是守卫）；
  - `separators=(",", ":")` ⇒ 紧凑、无空格；
  - `sort_keys=False` ⇒ **键序 = payload 插入序**，TS 侧必须保序（`Object.keys` 的顺序即契约，见每条通道的 `payload_keys_in_order` / `projected_fields`）。
- `id:` 固定为 `1`（见 §5）；
- 未映射的 `domain_type` ⇒ `channel_for()` 返回 `None` ⇒ **不产任何帧**（不是错误帧，也不是空帧）。

心跳帧（`encoder.encode_heartbeat`，**不带** `id:`，以免污染 `Last-Event-ID`）：

```
: hb 1700000000000\n\n
```

默认间隔 15.0 s，**仅空闲时**发送（实测自 `stream_run(heartbeat_seconds=15.0)`）；心跳样本与 sha256 记在 `channels.json` 的 `frame_format.heartbeat`（不单独出 golden 文件，因为它不是通道）。

SSE 帧**不套** `{code, message, data, request_id}` 响应壳（§11.1 例外）；`request_id` / `trace_id` 仅经响应头下发。响应壳契约见 `../envelope.schema.json`。

---

## 2. 19 条通道

`seq` 全部固定 `1`；sha256 列是**前 12 位**（完整值见 `channels.json` 各条的 `golden_sha256`）。

| # | `domain_type` | `event:` 通道 | phase | 事件类 | 字节 | golden sha256 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `agent.started` | `agent.started` | core | `AgentStarted` | 157 | `bb0069e15c22` |
| 2 | `agent.thinking` | `agent.thinking` | core | `AgentThinking` | 69 | `8fc9777a5418` |
| 3 | `agent.message` | `message.delta` | core | `AgentMessage` | 121 | `9c14f455021e` |
| 4 | `tool_call.started` | `tool.started` | core | `ToolCallStarted` | 159 | `09dd51bafdb1` |
| 5 | `tool_call.completed` | `tool.completed` | core | `ToolCallCompleted` | 177 | `843dd7cc6a03` |
| 6 | `mcp_call.started` | `mcp.started` | core | `MCPCallStarted` | 124 | `ef2ea4df41f2` |
| 7 | `mcp_call.completed` | `mcp.completed` | core | `MCPCallCompleted` | 173 | `6816f03bdce1` |
| 8 | `agent.completed` | `agent.completed` | core | `AgentCompleted` | 88 | `e713717adad0` |
| 9 | `agent.failed` | `agent.error` | core | `AgentFailed` | 128 | `a0710fea3398` |
| 10 | `skill.resolved` | `skill.resolved` | phase2 | `SkillResolved` | 114 | `7c54b75f5604` |
| 11 | `workflow.started` | `workflow.started` | phase2 | `WorkflowStarted` | 112 | `4d0bdd8f8816` |
| 12 | `workflow.node.started` | `workflow.node.started` | phase2 | `WorkflowNodeStarted` | 124 | `ac85b9bd41ab` |
| 13 | `workflow.node.completed` | `workflow.node.completed` | phase2 | `WorkflowNodeCompleted` | 144 | `3ff5cf6e7976` |
| 14 | `workflow.completed` | `workflow.completed` | phase2 | `WorkflowCompleted` | 98 | `92eebb063c10` |
| 15 | `workflow.failed` | `workflow.failed` | phase2 | `WorkflowFailed` | 154 | `0fd533361af6` |
| 16 | `knowledge.indexed` | `knowledge.indexed` | phase2 | `KnowledgeIndexed` | 114 | `18a93e135c6e` |
| 17 | `memory.written` | `memory.written` | phase2 | `MemoryWritten` | 95 | `0e63282ad5b7` |
| 18 | `approval.requested` | `approval.requested` | phase2 | `ApprovalRequested` | 145 | `d75d1966f91f` |
| 19 | `approval.decided` | `approval.decided` | phase2 | `ApprovalDecided` | 106 | `e7434fb25289` |

- **9 core + 10 Phase 2 = 19**，顺序即 `SSE_CHANNEL_BY_DOMAIN_TYPE` 的声明序；顺序漂移会让 `export` 直接失败。
- **6 条通道名与 domain_type 不同**：`agent.message → message.delta`、`tool_call.started → tool.started`、`tool_call.completed → tool.completed`、`mcp_call.started → mcp.started`、`mcp_call.completed → mcp.completed`、`agent.failed → agent.error`。其余 13 条同名。
- 聚合摘要：`channels_digest_sha256 = 9edda3baea0c…`（19 条条目规范化序列化的 sha256）、`golden_index_sha256 = aaea24d4c241…`（`domain_type<TAB>golden_sha256` 逐行拼接的 sha256）。
- 19 帧合计 2402 字节。

### 载荷从哪来（为什么 golden 不是手写的）

每个 payload 都由**真实事件实例**产生：`<EventClass>.create(**kwargs)`（事件类取自 `wbtime_ai_event.events`，按 `ClassVar type` 与通道表一一对应），再用**真实编码器** `encode_data_frame` 出帧。构造参数（"最小合理值"）逐条登记在 `channels.json` 的 `constructor.kwargs`，参数表本身在 `export_sse.py::PARAM_VALUES / PARAM_OVERRIDES`。没有一处 payload 字面量。

`payload_fields` 的口径：事件 dataclass 自身只有 4 个通用字段（`event_id` / `occurred_at` / `payload` / `seq`），**载荷 schema 实际由 `create()` 的关键字签名定义**，因此 `payload_fields` 记录的是 `create()` 的参数（名 / 类型 / 是否必填 / 默认值）。JSON 对象的键按 canonical 形式排序，**插入序**以 `payload_keys_in_order` 为准。

### 唯一的载荷投影

`agent.message` 上帧前会做一次投影（`encoder._project_payload`）：`content → delta`（并丢弃 `None`）。其余 18 条 **payload 与 `data:` 完全一致、键序不变**。生成器对每条通道都实测差值，若不是"只有 agent.message 有投影"就报错。

### 未映射的 8 个事件类（不产帧）

`system.started` / `system.shutdown` / `system.default_tenant_initialized` / `user.registered` / `user.logged_in` / `user.logged_out` / `workspace.created` / `workspace.updated` —— 事件包共 **27** 个事件类，其中 **19** 个有 SSE 通道，**8** 个没有（`channel_for()` 返回 `None`，静默跳过）。清单登记在 `channels.json` 的 `meta.domain_types_without_channel`。

---

## 3. 数值格式（路线图 §5.5 陷阱 2）

**问题**：`json.dumps(1.0)` 得 `1.0`，`JSON.stringify(1.0)` 得 `1`。只要"整数值浮点"能上帧，「逐字节相同」在原理上不可达。

**规则（`channels.json` → `numeric_format`，`policy = integers-only-on-the-wire`）**：

| 输入 | 输出 |
| --- | --- |
| `bool` | 原样（**先于** `int` 判定，避免 `True → 1`） |
| `int` | 原样 |
| `float`，`is_integer()` 且 `abs < 2**53` | `int(value)`，例 `1.0 → 1` |
| `float`，其余有限值 | **定点十进制字符串，恰好 6 位小数**，例 `0.5 → "0.500000"` |
| `Decimal` | 先转 `float`，再按上面两条处理 |
| `float` `nan` / `inf` | 抛 `ValueError`（不可上线） |
| `dict` / `list` / `tuple` | 递归处理；`dict` 键序保持不变 |

**落地位置**：生成器在把 payload 交给 `encode_data_frame` **之前**归一化（`export_sse.py::normalize_numbers`）；旧仓的 `encode_data_frame` / `encode_heartbeat` **一行未改**。

**关键事实（实测）**：19 条正式 golden 的载荷中浮点数 = **0**（`numeric_format.official_payload_float_count = 0`）。因此归一化对 19 条正式帧是 **no-op**，19 条 golden 的字节**就是旧仓服务端当前的真实输出**，不存在"为了对齐 JS 而篡改 golden"的情况。规则的作用是**防止未来出现浮点**。

**为什么仍然要有守卫帧**：只有文档的规则等于没有规则。所以额外出一条第 20 号样本，从**真实** `AgentCompleted` 实例出发注入浮点，证明两条分支真的会触发：

```
raw        : {"run_id":"run_01","duration_ms":12,"iterations":1,"score":0.5,"ratio":1.0,"neg_zero":-0.0,"nested":{"score":0.25}}
normalized : {"run_id":"run_01","duration_ms":12,"iterations":1,"score":"0.500000","ratio":1,"neg_zero":0,"nested":{"score":"0.250000"}}
```

- `score: 0.5` → `"0.500000"`（非整分支：转定点字符串）
- `ratio: 1.0` → `1`（整值分支：转 int）
- `neg_zero: -0.0` → `0`（`-0.0.is_integer()` 为真；同时`JSON.stringify(-0)` 也得 `0`）
- `nested.score: 0.25` → `"0.250000"`（递归生效）

### ⚠️ 正式 golden 与守卫样本必须分开

| | 文件数 | 文件名 | 是否通道契约 |
| --- | --- | --- | --- |
| 正式 golden | 19 | `golden/<channel>.txt` | ✅ 逐字节比对目标 |
| 守卫样本 | 1 | `golden/_guard-float-normalization.txt` | ❌ 只为证明 §3 规则生效 |

守卫文件用**下划线前缀**标记"不是通道"，`channels.json` 的 `guard.is_official_channel_golden` 明确为 `false`。TS 侧的 golden 测试必须只遍历 `channels[].golden`（19 条），**不要**用 `glob("golden/*.txt")`，否则会把守卫样本误当契约。

---

## 4. 流语义（TS 侧必须复刻的行为）

来自 `stream.py`（细节见 `channels.json` → `stream_semantics`）：

- `seq` 来自 `agent_event.seq`（`EventDispatcher` 投递 / 落库前统一分配），帧 `id:` 即该值，**单调递增**；
- 续传：`Last-Event-ID` 请求头或 `?after_seq=` ⇒ 只回放 `seq > last` 的事件；
- 去重：实时事件 `seq <= 已产出 seq` **丢弃**；无 `seq` 的事件按 `(type, payload)` 指纹兜底去重；
- 终态：`agent.completed` / `agent.failed` ⇒ 编码该帧后**结束**流；
- 断连：生成器被关闭 / 取消 ⇒ INLINE 模式触发 `cancel(run_id)`；
- 心跳：空闲超时才发，不带 `id:`。

## 5. `seq` 为什么固定为 1

`id:` 的值在真实流里是 `agent_event.seq`，天然不可复现（取决于该 Run 的历史）。golden 把它钉成 `1`：

- 让「帧不一样」**只可能**由通道 / 载荷差异导致，而不是计数器差异；
- 19 条通道各自独立取 `1`（不是 1..19 递增），比对时无需维护全局序号。

`id:` 的语义契约由 §4 的「单调递增 + `seq > last` 续传 + `seq <= yielded` 丢弃」承担，不由 golden 的数值承担。

## 6. 已登记的实现 / 文档差异

| # | 差异 | 事实 | 处理 |
| --- | --- | --- | --- |
| 1 | `VALIDATION_ERROR` 的设计表写 400 | 代码是 **422** | 契约取代码值，见 `../errors.json` |
| 2 | `docs/00-整体设计.md` §11.2 的 `UNAUTHENTICATED` / `NOT_IMPLEMENTED_YET` | 实际枚举字面值是 `UNAUTHORIZED` / `NOT_IMPLEMENTED` | 取实际字面值 |
| 3 | OpenAPI 把 SSE 端点声明为 `application/json` | 运行期是 `text/event-stream` | **OpenAPI 无法表达 SSE**：TS 代码生成必须把这 4 个端点排除在 JSON 客户端之外，按本目录的帧契约手写。清单见 `channels.json` → `sse_endpoints` |
| 4 | `agent.started` 等 6 条通道名与 `domain_type` 不同 | 见 §2 | 映射表逐条冻结，改名会让 `export` 失败 |
