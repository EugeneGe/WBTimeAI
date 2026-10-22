/**
 * T3-07 · Conversation / Message 服务（**5 op** 的全部主体 + 消息写入的两条不变量）。
 *
 * 5 op 与错误语义（**py oracle：`wbtime_ai_api/routers/v1/conversations.py` 逐条对齐**）
 * ------------------------------------------------------------------------------
 * | # | op | 成功码 | 错误 |
 * |---|---|---|---|
 * | 1 | `GET /conversations` | 200 数组 | ——（跨租户天然不可见：scope 谓词） |
 * | 2 | `POST /conversations` | 201 | `agent_id` 缺 ⇒ 422（schema）；`workspace_id` 空 ⇒ 422（py 服务层守卫） |
 * | 3 | `GET /conversations/{id}` | 200 | 不存在 / 跨租户 ⇒ **404**（I-1 口径，不是 403） |
 * | 4 | `PUT /conversations/{id}` | 200 | 不可见 ⇒ 404；`title` 缺 / 空 / 超长 ⇒ 422（schema） |
 * | 5 | `GET /conversations/{id}/messages` | 200 数组 | 不可见 ⇒ 404 |
 *
 * 契约面**没有** DELETE（`contracts/openapi.v1.frozen.json` 实测 5 条 path 全无 delete）
 * ⇒ 本服务**不提供**删除入口（`ConversationRepo` 继承来的 `remove` 不暴露业务方法）。
 *
 * 刻意不做
 * --------
 *   - **消息编辑 / 删除**：契约无此 op（范围红线）；`message` 只有追加语义。
 *   - **`POST /conversations/{id}/messages`**：契约与 py 都**没有**消息写路由 ——
 *     {@link ConversationService.appendMessage} 是**服务层入口**（run 装配 / 回放写入方用），
 *     不挂路由；把它挂上去就等于凭空造契约外端点。
 *
 * 两条不变量（验收 ④ 与反例 ②），都落在本文件的**写路径**上
 * --------------------------------------------------------
 *   ① **写幂等**（验收 ④）：同一 `run_id` 重复提交 assistant 消息**不产生第二行**。
 *      py `append_message` 每次都插一行（`ConversationService.append_message` 实证），
 *      TS 侧按任务卡验收 ④ 在服务层「先查后写」（偏差已登记，见交付报告偏差表）。
 *      幂等键 = `(conversation_id, run_id, role=assistant)`，查的是**本会话域内**的
 *      `MessageRepo.listByRun`（父谓词恒在 ⇒ 跨会话不可见 ⇒ 不会误判为"已写过"）。
 *   ② **不得绕过 conversation scope**（反例）：写路径**先**在 scoped `ConversationRepo`
 *      里 `findById` 一次，父会话不可见（不存在 / 跨租户）⇒ 404，**且一行都不写**。
 *      注意 `Scope#owns()` 是 **mint provenance**（谁铸造了这个 ref），**不是** row
 *      ownership —— 所以这里**不**用 `owns()` 当行归属证明（T3-03 §16.5 注释纪律），
 *      走的是 scope 内查询。
 *
 * 分页 / 次序
 * -----------
 * 契约实测：`GET /conversations` 的 `parameters` 是**空数组**，`GET /{id}/messages`
 * 只有 path 参数 ⇒ 两条列表 op **都不接受分页参数**（与 py 同形：`list_by_tenant` /
 * `list_by_conversation` 无分页）。故本服务不自造 `page` / `page_size`（那是契约外扩展）。
 *
 * 但「无分页参数」不等于「次序可以不确定」。验收 ③ 要求**同 `created_at` 用 `id`
 * 作次序键**，否则同一批消息两次调用可能给出不同次序（分页一旦引入就丢行/重行）。
 * `message` 的 `created_at` 是 `DEFAULT CURRENT_TIMESTAMP`（**秒粒度**）⇒ 同秒写入
 * 天然并列；而在 `packages/db` 的 `ChildScopedRepo.findManyWhere` 里只支持**单**排序键
 * （无第二键、无 offset，且该文件属 T3-03 冻结面、本卡不碰），因此次序键由本服务在
 * 内存里补齐：`(created_at, id)` 全序 —— 它是**数据的函数**，与 rowid / 堆序无关。
 * 复跑命令（红/绿都看这一条）：
 *   `cd apps/api && node --experimental-sqlite --test tests/routes-conversations.test.mjs`
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  ConversationRepo,
  MessageRepo,
  Scope,
  type ConversationRow,
  type DrizzleDatabase,
  type MessageRow,
  type SqlDialect,
} from "@wbtime/db";

import { toIsoOrNull } from "../agent/versioning.js";
import { authError } from "../auth/errors.js";

/**
 * 会话列表的取数上限。
 *
 * py `list_by_tenant` **无上限**（返回全部）；`packages/db` 的 `resolveListLimit`
 * 合法区间是 `1..500`、缺省 100（T1-03 既有约定）。本服务取**允许的最大值** 500，
 * 使"与 py 的差异"只在 >500 会话时才出现（登记为遗留，不在本卡私改 db 层）。
 */
export const CONVERSATIONS_LIST_LIMIT = 500;

/** 消息列表的取数上限（理由同 {@link CONVERSATIONS_LIST_LIMIT}）。 */
export const CONVERSATION_MESSAGES_LIST_LIMIT = 500;

/** 对外会话视图（契约 `ConversationResponse`，键集合逐字对齐：**9 键**）。 */
export interface ConversationView {
  readonly id: string;
  readonly tenant_id: string | null;
  /** 契约该键是 `type: string` + `default: ""`（**非可空**）⇒ 列值为 null 时回落空串。 */
  readonly workspace_id: string;
  readonly agent_id: string;
  readonly user_id: string;
  readonly title: string;
  readonly status: string;
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

/** 对外消息视图（契约 `ConversationMessageResponse`，键集合逐字对齐：**8 键**）。 */
export interface ConversationMessageView {
  readonly id: string;
  readonly conversation_id: string;
  readonly run_id: string | null;
  readonly role: string;
  readonly content: string;
  /** 契约该键是 `type: array`（**非可空**）⇒ 列值为 null 时回落空数组（py `or []` 同口径）。 */
  readonly content_parts: readonly unknown[];
  readonly token_count: number | null;
  readonly created_at: string | null;
}

/** 创建入参（契约 `CreateConversationRequest`：`agent_id` 必填；`title` / `workspace_id` 缺省 `""`）。 */
export interface CreateConversationInput {
  readonly agent_id: string;
  readonly title?: string;
  readonly workspace_id?: string;
}

/** 追加消息入参（服务层入口，**非契约 op** —— 见文件头注「刻意不做」第 2 条）。 */
export interface AppendConversationMessageInput {
  readonly conversation_id: string;
  /** `user` / `assistant` / `tool` / `system` …（仓储层不校验枚举，契约亦无枚举）。 */
  readonly role: string;
  readonly content: string;
  readonly content_parts?: unknown;
  readonly token_count?: number | null;
  /** 产生这条消息的 run；用户手打的输入没有 run ⇒ `null`。 */
  readonly run_id?: string | null;
}

/** {@link ConversationService.appendMessage} 的产物。 */
export interface AppendConversationMessageResult {
  readonly message: ConversationMessageView;
  /** `true` = 本次真的插了一行；`false` = 命中幂等键，返回的是**既有**那一行。 */
  readonly created: boolean;
}

/** 会话服务的依赖（装配一次，见 `app.ts` 的 `buildIdentityStack`）。 */
export interface ConversationServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
}

export class ConversationService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(deps: ConversationServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect;
  }

  /** 本租户的会话仓储（每次现建 —— 与 agent / skill 服务同一模式）。 */
  #repo(tenantId: string): ConversationRepo {
    return new ConversationRepo(this.#db, new Scope(tenantId), this.#dialect);
  }

  /**
   * 本会话的消息仓储。
   *
   * 父引用只能由**本 scope** 铸造（`Scope#ref`）—— 仓储构造期会校验品牌与租户；
   * **行归属**由构造期的 `parentExists`（父表 scoped `findById`）与每次查询的父谓词兜住，
   * 不依赖 `Scope#owns()`（它只证明"谁铸造了这个 ref"）。
   */
  #messages(tenantId: string, conversationId: string): MessageRepo {
    const scope = new Scope(tenantId);
    return new MessageRepo(this.#db, scope, scope.ref(conversationId), this.#dialect);
  }

  /**
   * 列出本租户会话（`GET /conversations`；契约无分页参数 ⇒ 不解析 page / page_size）。
   *
   * 次序由 `ConversationRepo.list` 给出（`updated_at` 降序 + `id` 升序兜底 ——
   * 同秒记录的次序是数据的函数，T3-03 已在该文件立据）。
   *
   * @throws {HttpException} repo 的 `ScopeError`（本路径正常不触发）⇒ 422。
   */
  async list(tenantId: string): Promise<ConversationView[]> {
    try {
      const rows = await this.#repo(tenantId).list({ limit: CONVERSATIONS_LIST_LIMIT });
      return rows.map(toConversationView);
    } catch (error) {
      throw this.#mapValidation(error);
    }
  }

  /**
   * 创建会话（`POST /conversations`：`status` 缺省 `ACTIVE`、`organization_id` 不填）。
   *
   * `workspace_id` 是**服务层守卫**（py 同文案同码）：契约把它标成 `default: ""` 且
   * 不在 `required` 里，所以缺失时 schema 放行、由这里挡成 422。若不挡，PG 档会撞
   * `workspace_id` 的 NOT NULL/FK ⇒ 500（py 的 F-4 / P2-110 就是这条）。
   *
   * @param userId 当前登录用户 id（`conversation.user_id` NOT NULL；py 同口径）。
   * @throws {HttpException} `workspace_id` 为空 ⇒ 422 `VALIDATION_ERROR`（`field=workspace_id`）。
   */
  async create(
    tenantId: string,
    userId: string,
    input: CreateConversationInput,
  ): Promise<ConversationView> {
    const workspaceId = input.workspace_id ?? "";
    if (workspaceId === "") {
      // py `if not workspace_id:` —— 只对空串（与 None）触发；空白串在 py 侧是"真值"，
      // 会一路走到 FK 报错。这里逐字对齐，不擅自 trim 收紧（收紧就是契约外语义）。
      throw authError(ERROR_CODES.VALIDATION_ERROR, "workspace_id 为必填（新建会话须归属工作区）", {
        field: "workspace_id",
      });
    }
    const row = await this.#repo(tenantId).create({
      id: randomUUID(),
      workspaceId,
      agentId: input.agent_id,
      userId,
      title: input.title ?? "",
    });
    return toConversationView(row);
  }

  /**
   * 取会话（`GET /conversations/{id}`：不存在 / 跨租户 ⇒ 404 —— 契约描述原文，I-1 口径）。
   *
   * @throws {HttpException} 404 `NOT_FOUND`「会话不存在」（同文案同 `data` 键，py 同形）。
   */
  async get(tenantId: string, conversationId: string): Promise<ConversationView> {
    return toConversationView(await this.#visible(tenantId, conversationId));
  }

  /**
   * 重命名会话（`PUT /conversations/{id}`：契约 `UpdateConversationRequest` **只有 title**）。
   *
   * 与 py 同序：先按 scope 取会话（不可见 ⇒ 404），再落库；落库返回 `null`
   * （并发删除）同样 404 —— 不让"改名落空"变成 200 假成功。
   *
   * `updated_at` 由 `ConversationRepo.rename` 显式推进（SQLite 无 `ON UPDATE` 触发器，
   * 零 DDL ⇒ 只能应用层写），否则按 `updated_at` 排序的列表会出现"刚改名却仍在后面"。
   *
   * @throws {HttpException} 不可见 ⇒ 404。
   */
  async rename(tenantId: string, conversationId: string, title: string): Promise<ConversationView> {
    await this.#visible(tenantId, conversationId);
    const updated = await this.#repo(tenantId).rename(new Scope(tenantId).ref(conversationId), title);
    if (updated === null) {
      throw notFound(conversationId);
    }
    return toConversationView(updated);
  }

  /**
   * 列出某会话的消息（`GET /conversations/{id}/messages`：按创建顺序）。
   *
   * 次序 = `(created_at asc, id asc)`（验收 ③）：
   *   - `created_at` 是主键位 —— 对话次序即时间次序；
   *   - `id` 是**并列时的次序键**：同一秒写入的消息 `created_at` 完全相同，只按它排序时
   *     先后由 rowid / 堆序决定（一次 `UPDATE` 就能换一种顺序）⇒ 分页会静默丢行/重行。
   *     补 `id` 后次序成为数据的函数，两次调用逐字一致（用例 C-2 钉住）。
   *
   * @throws {HttpException} 会话不可见 ⇒ 404（先判，再读消息 —— 与 py 同序）。
   */
  async listMessages(
    tenantId: string,
    conversationId: string,
  ): Promise<ConversationMessageView[]> {
    await this.#visible(tenantId, conversationId);
    const rows = await this.#messages(tenantId, conversationId).list({
      orderBy: "created_at",
      descending: false,
      limit: CONVERSATION_MESSAGES_LIST_LIMIT,
    });
    return [...rows].sort(compareMessages).map(toMessageView);
  }

  /**
   * 追加一条消息（**服务层入口，不挂路由** —— 契约无写消息 op）。
   *
   * 两条不变量，按此序执行（次序不可换）：
   *   1. **scope 闸门**（反例 ②）：`ConversationRepo.findById` 在**本租户 scope** 内
   *      查一次父会话；不可见 ⇒ 404，**一行都不写**。这是"写路径不得绕过 conversation
   *      scope"的落点 —— 注意它**不是** `Scope#owns()`（那只验 ref 的铸造来源）。
   *   2. **写幂等**（验收 ④）：`role === "assistant"` 且 `run_id` 非空时，先在本会话域内
   *      按 `run_id` 查既有消息；命中 assistant 行 ⇒ 直接返回该行（`created=false`），
   *      不再插入。`run_id` 为空（用户手打输入）不参与幂等 —— 没有幂等键就没有幂等语义。
   *
   * 幂等是**应用层**护栏（双档 DDL 对 `(conversation_id, run_id, role)` 无唯一索引，
   * 零 DDL 红线 ⇒ 不能加）。读-写之间存在并发窗口：同 `run_id` 的两次**并发**写入
   * 仍可能各插一行 —— 登记为遗留（本版写入方是单写者的 run 执行路径，T3-08 接线时
   * 以 run 级串行保证；py 侧连幂等都无）。
   *
   * @throws {HttpException} 父会话不可见 ⇒ 404 `NOT_FOUND`。
   */
  async appendMessage(
    tenantId: string,
    input: AppendConversationMessageInput,
  ): Promise<AppendConversationMessageResult> {
    await this.#visible(tenantId, input.conversation_id);

    const repo = this.#messages(tenantId, input.conversation_id);
    const runId = input.run_id ?? null;
    if (input.role === "assistant" && runId !== null) {
      const scope = new Scope(tenantId);
      const existing = (await repo.listByRun(scope.ref(runId), {
        orderBy: "created_at",
        descending: false,
        limit: CONVERSATION_MESSAGES_LIST_LIMIT,
      })).find((row) => row.role === "assistant");
      if (existing !== undefined) {
        return { message: toMessageView(existing), created: false };
      }
    }

    const created = await repo.append({
      role: input.role,
      content: input.content,
      ...(input.content_parts === undefined ? {} : { contentParts: input.content_parts }),
      ...(input.token_count === undefined ? {} : { tokenCount: input.token_count }),
      runId,
    });
    return { message: toMessageView(created), created: true };
  }

  /** scope 内取会话行；不可见 ⇒ 404（**唯一的 404 出口**，5 op 与写路径共用）。 */
  async #visible(tenantId: string, conversationId: string): Promise<ConversationRow> {
    const row = await this.#repo(tenantId).findById(new Scope(tenantId).ref(conversationId));
    if (row === null) {
      throw notFound(conversationId);
    }
    return row;
  }

  /** repo 的 `ScopeError`（值域校验）→ 422 `VALIDATION_ERROR`（同 agent / skill 服务口径）。 */
  #mapValidation(error: unknown): Error {
    if (error instanceof Error && error.name === "ScopeError") {
      return authError(ERROR_CODES.VALIDATION_ERROR, error.message);
    }
    return error as Error;
  }
}

/** 会话不可见的统一错误（404 —— I-1 口径；py 文案同「会话不存在」）。 */
function notFound(conversationId: string): Error {
  return authError(ERROR_CODES.NOT_FOUND, "会话不存在", { conversation_id: conversationId });
}

/**
 * 消息的**全序**比较：`(created_at asc, id asc)`。
 *
 * 时间先经 `toIsoOrNull` 规整再比 —— PG 档给 `Date`、SQLite 档给 `YYYY-MM-DD HH:MM:SS`
 * 文本，直接比原值会拿两种不可比的形状做 `<` 运算（`Date < string` 的隐式转换结果
 * 取决于字符串能否被解析，是个哑失败源）。
 */
function compareMessages(left: MessageRow, right: MessageRow): number {
  const leftAt = toIsoOrNull(left.created_at) ?? "";
  const rightAt = toIsoOrNull(right.created_at) ?? "";
  if (leftAt !== rightAt) return leftAt < rightAt ? -1 : 1;
  if (left.id === right.id) return 0;
  return left.id < right.id ? -1 : 1;
}

/** 行 → 契约视图（键集合逐字对齐 `ConversationResponse`：9 键）。 */
export function toConversationView(row: ConversationRow): ConversationView {
  return {
    id: row.id,
    tenant_id: row.tenant_id ?? null,
    workspace_id: row.workspace_id ?? "",
    agent_id: row.agent_id ?? "",
    user_id: row.user_id ?? "",
    title: row.title ?? "",
    status: row.status,
    created_at: toIsoOrNull(row.created_at),
    updated_at: toIsoOrNull(row.updated_at),
  };
}

/** 行 → 契约视图（键集合逐字对齐 `ConversationMessageResponse`：8 键）。 */
export function toMessageView(row: MessageRow): ConversationMessageView {
  return {
    id: row.id,
    conversation_id: row.conversation_id,
    run_id: row.run_id ?? null,
    role: row.role ?? "user",
    content: row.content ?? "",
    content_parts: Array.isArray(row.content_parts) ? row.content_parts : [],
    token_count: row.token_count ?? null,
    created_at: toIsoOrNull(row.created_at),
  };
}
