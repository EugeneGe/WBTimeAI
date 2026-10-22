/**
 * T3-03 · `message` 仓储（会话消息 · 会话回放与上下文重建的取数源）。
 *
 * 表**没有 `tenant_id`**（父 = `conversation`）⇒ `extends ChildScopedRepo`（R3-22）。
 * 它是**唯一**一张父列不是 `run_id` 的运行时子表（`conversation_id`），
 * 所以它也是「`ChildScopedRepo` 是不是只给 `run_id` 特化」的试金石。
 *
 * 隔离口径（三条，缺一条就可串流）
 * -------------------------------
 *   1. 父引用是 `conversation` 的 `ScopedRef`，**没有默认值**且必须是本 scope 产出
 *      （裸 id / **别租户 scope 铸造**的 ref ⇒ 构造即抛 `ScopeError`）；
 *      ⚠️ 但「本 scope 铸造 + id 指向**别租户**的会话」**构造期放行** ——
 *      `Scope#owns()` 只校验铸造来源（mint provenance），**不校验行归属**。
 *      那一格由首次使用时的父查询（`parentExists` 的 scoped `findById`）兜住，
 *      见 `tests/child-scope.test.mjs` 里「父存在但属于另一租户」那条决定性夹具；
 *   2. 所有查询经基类 `scopedWhere()`，父谓词恒在 —— 同租户的**另一个会话**也看不见；
 *   3. ⚠️ `message` 还有一条**可空** FK `run_id` 回指 `agent_run`：
 *      {@link MessageRepo.listByRun} 只在**当前会话域内**按 run 过滤，
 *      **不提供**「只给 run_id、不给 conversation」的任何入口 —— 那种入口一开，
 *      "按 run 查消息"就变成"跨会话串流"，正是验收 ④ 要打红的写法。
 *      写路径同理：{@link MessageRepo.append} 在 `runId` 非空时校验
 *      「run 在**本 scope**（本租户）下可见」。FK 只查 run 行是否存在，**不查租户** ——
 *      单靠 FK 挡不住「把 A 租户的 run 挂到 B 租户的会话下」，那一格由这条校验补。
 *      ⚠️ 但**不**比对 `run.conversation_id`：跨会话、同租户的 `run_id` 是**合法**形态
 *      —— ① 契约没声明这条约束（双档 DDL 只有存在性 FK），应用层加严就是契约外扩展、
 *      会破坏 TS 与 py 的行为等价；② 安全不需要（跨租户已被上面那条拦住，会话级零增量）；
 *      ③ 读侧本来就由父谓词兜住。详见 {@link MessageRepo.append} 那三条。
 *
 * 本层**不做**的校验（刻意）
 * ------------------------
 * `role` 是 `VARCHAR(20)` 无枚举、`content_parts` 是自由 JSON、`token_count` 可空 ——
 * 契约 `ConversationMessageResponse` 对它们也**没有**枚举/形状约束（`role` 只有缺省
 * `"user"`）。在仓储层擅自加枚举 = 把服务层的策略提前焊死，故一律留给服务层。
 */

import { randomUUID } from "node:crypto";

import { asc, desc, eq, type InferSelectModel, type SQL, type Table } from "drizzle-orm";

import { message as pgMessage } from "../schema/pg/conversation.js";
import { message as sqliteMessage } from "../schema/sqlite/conversation.js";
import { AgentRunRepo, type AgentRunRow } from "./agent-run-repo.js";
import {
  ChildScopedRepo,
  type ChildRepoOptions,
  type ChildScopedInsert,
} from "./child-scoped-repo.js";
import { ConversationRepo } from "./conversation-repo.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  resolveListLimit,
  ScopeError,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
} from "./scoped-repo.js";

/** `message` 行。 */
export type MessageRow = InferSelectModel<typeof pgMessage>;

/**
 * 追加一条消息的入参。
 *
 * `id` 不在这里：双档 DDL 的 `id` **无默认值**，由仓储用 `randomUUID()` 生成 ——
 * 把"每条消息都有 id"变成结构性保证，而不是靠每个调用方记得传。
 */
export interface AppendMessageInput {
  /** 角色（`user` / `assistant` / `tool` / `system` …）。**本层不校验**，见文件头注。 */
  readonly role: string;
  /** 纯文本内容（`content` 列 NOT NULL）。 */
  readonly content: string;
  /** 结构化分片（多模态 / 工具片段）；不传 ⇒ `null`。 */
  readonly contentParts?: unknown;
  /** token 计数；未知 ⇒ `null`（**不是** 0 —— "未统计"与"统计为 0"必须可分）。 */
  readonly tokenCount?: number | null;
  /** 产生这条消息的 run；可空（用户手打的输入没有 run）。 */
  readonly runId?: string | null;
}

export class MessageRepo extends ChildScopedRepo<MessageRow, "conversation_id"> {
  /**
   * 校验 `message.run_id` 归属用的 **scoped** 仓储。
   *
   * 为什么不是自己拼 where：`agent_run` **有** `tenant_id`（租户直挂），它的
   * `findById` 天然带租户谓词 —— 与 `parentExists` 复用 `ConversationRepo` 同一套路，
   * 不新增架构。自己拼 where 就等于在子表仓储里重开一条裸 id 查询通道（I-2 的破口）。
   */
  readonly #runs: AgentRunRepo;

  /**
   * 表对象（**T3-07 新增**，仅为有序列举服务）。
   *
   * 基类 `ChildScopedRepo` 不暴露表对象（`#table` 是私有的），而本类的两个 list 方法
   * 要自己拼 `orderBy(...)` 才能补第二排序键（见 {@link MessageRepo.#findOrdered}），
   * 故在构造时留一份 —— 与 `ConversationRepo` 同款先例（那边也是构造期留 `#table`）。
   */
  readonly #table: Table;

  constructor(
    db: DrizzleDatabase,
    scope: Scope,
    conversationRef: ScopedRef,
    dialect: SqlDialect = "pg",
  ) {
    // 父可见性校验交给**父表的 scoped 仓储**（天然带 tenant 谓词），基类不反依赖父表。
    const conversations = new ConversationRepo(db, scope, dialect);
    const options: ChildRepoOptions = {
      parentColumn: "conversation_id",
      parentLabel: "conversation",
      parentExists: (ref) => conversations.findById(ref).then((row) => row !== null),
    };
    super(db, resolveTable(dialect, pgMessage, sqliteMessage), scope, conversationRef, options);
    this.#runs = new AgentRunRepo(db, scope, dialect);
    this.#table = resolveTable(dialect, pgMessage, sqliteMessage);
  }

  /**
   * 本会话的消息（**按 `(created_at asc, id asc)`** —— 对话次序即时间次序）。
   *
   * 第二键 `id` 是 T3-07 补的（原先只排 `created_at`）：该列是秒粒度的
   * `DEFAULT CURRENT_TIMESTAMP`，同一秒写入的消息完全并列，只按它排序时先后由
   * rowid / 堆序决定 ⇒ 一旦引入分页或有 `LIMIT` 截断，"取哪几条"就不是数据的函数
   * （丢行 / 重行都是它）。
   *
   * **py oracle 逐字对齐**：`list_by_conversation` 实测
   * `order_by(OrmMessage.created_at.asc(), OrmMessage.id.asc())`
   * （`wbtime_ai_conversation/repositories/message_repository.py:79`）。
   *
   * 实现方式与 `ConversationRepo.#findOrdered` 同款（子类自拼有序链）：
   * 基类 `findManyWhere` 只接受**单**排序键，没有第二键入口。
   */
  list(options: ListOptions = {}): Promise<MessageRow[]> {
    return this.#findOrdered(undefined, options);
  }

  /**
   * 本会话内某次 run 产生的消息（`run_id` 可空，故也可能为空集）。
   *
   * ⚠️ 父谓词由基类自动 and 上 —— 本方法的取数范围**被它锁在本会话**（**前提是谓词在**：
   * 反例探针见下方 `listByRun` 的 B-4 实测 —— 摘掉它，同一调用立刻从 0 行变 3 行、全是别租户的消息）。
   * 这是"按 run 查消息"唯一允许的形态（见文件头注第 3 条）。
   *
   * @throws {ScopeError} **仅当** `runRef` 由**别租户的 scope** 铸造
   *   （`owns()` 比 `tenantId`，这种挡得住）。
   *
   * ⚠️ `owns()` **挡不住**另一种：`runRef` 由**本 scope** 铸造、但 `id` 指向**别租户的
   * run**（`scopeA.ref(runB)`）。此时**不抛**，返回的是**本会话内** `run_id` 匹配的消息 ——
   * 因为父谓词（`conversation_id`）把取数范围锁死在本会话。
   *
   * 也就是说：**行归属由父谓词保证，不是 `owns()` 保证**。`Scope#ref(id)` 接受任意字符串、
   * 只把 `tenantId` 盖成本 scope 的，所以 `owns()` 验的是「这个 ref 由谁铸造」
   * （mint provenance），**不是**「这个 id 的行属于本租户」（row ownership）。
   * 实测（B-4：把基类的父谓词摘掉后同一调用）：`inConvA.listByRun(scopeA.ref(runB))`
   * 从 **0 行**变成 **3 行、全是 convB（别的租户）的消息** ⇒ 兜住它的是父谓词。
   */
  listByRun(runRef: ScopedRef, options: ListOptions = {}): Promise<MessageRow[]> {
    if (!this.scope.owns(runRef)) {
      throw new ScopeError(
        `message.listByRun：run 引用不是本 scope 产出的 ScopedRef，或属于别的租户` +
          `（仓储 scope = ${this.scope.tenantId}）—— 裸 id / 跨租户 ref 一律抛错`,
      );
    }
    return this.#findOrdered(eq(this.columns.run_id, runRef.id), options);
  }

  /**
   * 带 `id` 兜底排序的有序列举（`list` / `listByRun` 的**唯一查询出口**）。
   *
   * 与 `ConversationRepo.#findOrdered` 同款（那边按 `updated_at` 主键 + `id` 兜底，
   * 这里按 `created_at` 主键 + `id` 兜底）；两边的**理由也同源**：双档 DDL 的时间列
   * 都是 `DEFAULT CURRENT_TIMESTAMP`（秒粒度），同秒记录只按时间排序时先后不由数据决定
   * —— SQLite 吐 rowid 序、PG 吐堆序，一次 `UPDATE` 就能换一种顺序。
   *
   * 后果不是"看起来乱"，而是**分页 / 截断静默丢行或重行**：同一个 `limit` 两次可能
   * 取到不同的集合。`id` 是主键、全序且不随时间变化 ⇒ 补成第二键后，**取哪几条**与
   * **怎么排**都成为数据的函数。
   *
   * 排序方向：`descending === true` 才降序（缺省升序 —— 与 py `created_at.asc()`
   * 一致，也保持本类改造前的行为）。第二键恒 `asc(id)`，与 `ConversationRepo` 一致。
   *
   * 非法 `orderBy`（显式传了本表不存在的列，如 `updated_at`）⇒ **抛 `ScopeError`**，
   * **不**静默降级成 `created_at`：静默兜底会把调用方的编程错误变成"排序看起来正常、
   * 其实按别的列"的哑失败 —— 与本仓 `resolveListLimit` 的既有纪律（"非法值直接拒绝，
   * 不静默夹取"）一致。
   *
   * `ensureParent()` 在改造前后**都在**（基类 `ChildScopedRepo.findManyWhere` 原本就调，
   * 见 `child-scoped-repo.ts:272`）—— 本类改成自拼链后显式保留，语义零变化：
   * 父不可见 ⇒ `ScopeError`（不是返回 `[]`）。
   *
   * @param condition 除父谓词外的附加条件（`undefined` = 不限）。
   * @param options 排序 / 上限（`limit` 的合法区间由 {@link resolveListLimit} 校验）。
   * @throws {ScopeError} 父不可见；或显式 `orderBy` 指向本表不存在的列。
   */
  async #findOrdered(condition: SQL | undefined, options: ListOptions): Promise<MessageRow[]> {
    await this.ensureParent();
    const limit = resolveListLimit(this.tableName, options.limit);
    const orderColumn = this.columns[options.orderBy ?? "created_at"];
    if (orderColumn === undefined) {
      throw new ScopeError(
        `表 ${this.tableName}：orderBy 非法（实测 ${JSON.stringify(options.orderBy)}）—— ` +
          "本表的合法排序列为 created_at / id；非法值直接拒绝，不静默降级成 created_at",
      );
    }
    const primary = options.descending === true ? desc(orderColumn) : asc(orderColumn);
    const chain = this.db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(condition))
      .orderBy(primary, asc(this.columns.id))
      .limit(limit);
    return (await (chain as unknown as PromiseLike<MessageRow[]>)).slice();
  }

  /**
   * 追加一条消息（`id` 由仓储生成，父 `conversation_id` 由基类注入）。
   *
   * `runId` 非空时校验**一条**不变式：run 在**本 scope**（= 本租户）下可见
   * （`agent_run` 有 `tenant_id` ⇒ scoped `findById` 自带租户谓词）。
   * 外键只保证「这个 run 行存在」，**不保证它属于本租户** —— 那一格 FK 管不到。
   *
   * ⚠️ **刻意不比对 `run.conversation_id`**（改动前先读这三条）
   * --------------------------------------------------------
   *   ① **契约没声明** ⇒ 加上去就是契约外的语义扩展。双档 DDL 对 `message.run_id`
   *      只有一条**存在性** FK，**没有**「必须等于所在会话的 run」这种约束；
   *      而本版的目标是「契约冻结 + 与 py 线行为等价」—— py 侧不做这个校验，
   *      应用层加严会让同一输入在 TS 与 py 上表现不同，**直接破坏等价性**。
   *      真要做，必须走契约变更（契约增量 + py 侧同步），不能在仓储层静默收紧。
   *   ② **安全不需要**：跨租户引用已被上面那条租户级校验拦住，会话级不带来任何
   *      安全增量（同租户、跨会话的 `run_id` 不构成越权）。
   *   ③ **可测性反而更强**：允许该形态存在，判据①「同租户两会话共用同一 run_id」
   *      才能验证「父谓词**不依赖数据是干净的**」。⚠️ 注意该形态**仓储自己就造得出来**
   *      —— 判据① 正文即 `inConvA2.append({ runId: IDS.runA })`（同租户 ⇒ 通过），
   *      所以判据① 证明的是「父谓词不依赖数据多干净」，**不是**「外部注入的脏数据也
   *      挡得住」；后者要用别的用例，别拿判据① 当那个证据。
   *      读侧也确实由它兜住：`listByRun` 恒 and `conversation_id`（见
   *      {@link MessageRepo.listByRun} 的实测：摘掉父谓词才从 0 行变 3 行）。
   *
   * 校验**每次 `append` 都做一次**，不复用基类 `ensureParent()` 的实例级缓存 ——
   * 父引用在构造期固定（缓存它是对的），而 `runId` 每次调用都可能不同；
   * 复用一个"查过一次就不再查"的缓存，等于第二次 append 换个 runId 就直接跳过校验
   * （那是最典型的假绿：第一次查了，后面全放行）。
   *
   * @throws {ScopeError} 父会话在本 scope 下不可见（首次使用时校验）。
   * @throws {ScopeError} `runId` 指向的 run 在本 scope 下不可见（跨租户或不存在）。
   */
  async append(input: AppendMessageInput): Promise<MessageRow> {
    // 父优先级最高：父本身不可见时，谈 run 归属没有意义。
    await this.ensureParent();
    if (input.runId !== undefined && input.runId !== null) {
      await this.#assertRunVisible(input.runId);
    }
    const row: Record<string, unknown> = {
      id: randomUUID(),
      role: input.role,
      content: input.content,
      content_parts: input.contentParts ?? null,
      token_count: input.tokenCount ?? null,
      run_id: input.runId ?? null,
    };
    return this.insertRow(row as unknown as ChildScopedInsert<MessageRow, "conversation_id">);
  }

  /**
   * 校验 run 在**本 scope** 下可见（只此一条，不看会话）。
   *
   * 单独抽出来的原因：反向验证（把 scoped 查找换成不查租户的直查）要能**只换这一处**
   * 就打红跨租户那条判据，而不牵连父校验。
   */
  async #assertRunVisible(runId: string): Promise<void> {
    const run = await this.#findRun(runId);
    if (run === null) {
      throw new ScopeError(
        `表 message：run ${runId} 在本 scope 下不可见（租户 ${this.scope.tenantId}）—— ` +
          "跨租户或不存在的一律拒绝挂消息（外键只查 run 行是否存在，不查租户）",
      );
    }
  }

  /** 取 run 行：**必须**经 scoped 仓储（`agent_run` 是租户直挂表，直查会跨租户）。 */
  #findRun(runId: string): Promise<AgentRunRow | null> {
    return this.#runs.findById(this.scope.ref(runId));
  }
}
