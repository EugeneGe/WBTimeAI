/**
 * V0.3.1 · G031-SPK · 子 Agent 委派的**域常量**（零 DDL 方案的标记值，全仓唯一定义处）。
 *
 * 为什么常量放 `packages/domain` 而不是 `apps/api`
 * -----------------------------------------------
 *   `agent_run.trigger` / `agent_event.type` 都是**自由字符串**列（v0019 冻结面：
 *   无 CHECK / 无 enum / 无外键，实测 `output/ddl.sqlite.sql`），`"subagent"` 这个值
 *   没有任何数据库约束兜底 —— 防止各处手写字符串漂移的唯一办法，是让**唯一真源**
 *   落在一个零依赖、谁都能 import 的纯域模块里（`packages/db` 不依赖 `@wbtime/domain`，
 *   故 db 侧连 CHECK 都加不了，这是零 DDL 的既定代价，由应用层纪律补偿）。
 *
 * 与《调用契约》的对应（`apps/api/tests/subagent-spike.test.mjs` 文件头）
 * ----------------------------------------------------------------
 *   `RUN_TRIGGER_SUBAGENT = "subagent"` / `RUN_ORIGIN_SUBAGENT = "SUBAGENT"` /
 *   `MAX_SUBAGENT_DEPTH = 1` —— 三个取值被判据 S-1-2 **逐字断言**，不得改拼法。
 */

/**
 * 子 run 写入 `agent_run.trigger` 的标记值（**小写**）。
 *
 * 零 DDL：`trigger VARCHAR(50) NOT NULL` 无 CHECK ⇒ 新取值不需要 migration。
 * 该值**只作标记、永不参与放行判定** —— 豁免判据是 `origin`（见
 * {@link RUN_ORIGIN_SUBAGENT}），不是 trigger（D10：trigger 是客户端可达的自由串）。
 */
export const RUN_TRIGGER_SUBAGENT = "subagent";

/**
 * 应用层"入口来源"的**豁免值**（**大写**，与 trigger 的小写刻意区分开）。
 *
 * 只有应用层单入口（T031-04 的 `open_run`）会传真值；客户端可达的任何字段
 * （`RunRequest` 不含 trigger、workflow 的自由串 trigger）都**到不了**这个形参
 * ⇒ 客户端无法伪造"子 run 身份"绕过并发闸（D10 / R11 / P0-2 补丁 P-1）。
 */
export const RUN_ORIGIN_SUBAGENT = "SUBAGENT";

/**
 * `max_subagent_depth` 缺省值：**1 = 单层委派**（父 run 可派子 run，
 * 子 run 内再派生必拒）。被判据 S-1-2 / S-3-2 双向钉住。
 */
export const MAX_SUBAGENT_DEPTH = 1;

/**
 * 第 6 个内置工具的工具名（`spawn_agent`）。
 *
 * 三个消费方必须逐字同源：`packages/db` 的 `BUILTIN_TOOLS`（input_schema 唯一真源）、
 * `apps/api` 的 `BUILTIN_REGISTRY`（可执行实现）、`SubAgentSpawner`（落 `tool_call.tool_name`）。
 * 单边改名会立刻被 `builtin-tools` / `subagent-spike` 双侧判红。
 */
export const SPAWN_AGENT_TOOL_NAME = "spawn_agent";

/** 深度超限时 `subagent.rejected` 事件 `payload.reason` 的取值（D1 观察面 ②）。 */
export const DEPTH_EXCEEDED_REASON = "DEPTH_EXCEEDED";

/**
 * 派生被拒时落的**内部事件**类型（`agent_event.type`，自由串 ⇒ 零 DDL）。
 *
 * `subagent.*` 不是 19 条 SSE 冻结通道之一（`isSseChannel` 不认）⇒ 它是纯内部行、
 * 从不下发 —— 与 `loop.turn.started` 等 R3-11 内部行同一待遇。
 * （T031-01 落地 `channels.delta.json` 后 `subagent.started / finished` 才成为下发帧；
 * 本常量是拒绝侧的内部事件，与之无冲突。）
 */
export const SUBAGENT_REJECTED_EVENT = "subagent.rejected";

/**
 * 派生被放行时落的**内部事件**类型（父 run 侧；`agent_event.type`，零 DDL）。
 *
 * ⚠️ spike 阶段它只是内部行；T031-01 把 `subagent.started` 登记为 SSE delta 通道后，
 * 它会随 `frameOf` 变成父流的下发帧 —— 届时 payload 键序以冻结件
 * `channels.delta.json` 的 `payload_keys_in_order` 为准（本骨架的 payload 形状
 * 是 spike 探针形状，T031-02/T031-05 接线时必须重对键序）。
 */
export const SUBAGENT_STARTED_EVENT = "subagent.started";
