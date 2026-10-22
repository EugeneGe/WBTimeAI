/**
 * T3-03 · `conversation` 仓储（会话主链行 · **替换 T1-03 的只读桩**）。
 *
 * 桩的三处缺口（本次补掉）
 * ----------------------
 * 1. **只有 PG 档**：原实现 `super(db, pg.conversation, scope)` 硬绑 PG 表对象 ⇒
 *    CI 的 SQLite 真库**永远跑不到它**，"SQLite 档全绿"对它是句空话。现走
 *    {@link resolveTable} + `dialect` 构造参数（缺省 `"pg"` = 生产档）。
 * 2. **没有 `list()`**：`ScopedRepo` 只把 `findManyWhere` 开给子类（`protected`），
 *    所以桩连"列出本租户会话"都做不到 ⇒ `GET /api/v1/conversations` 无从实现。
 * 3. **没有缺省值**：契约 `ConversationResponse.status` 的 default 是 `"ACTIVE"`，
 *    桩的 `create` 什么都不注入 ⇒ 调用方漏填就写出一行 `status` 未定义的会话。
 *
 * 与契约的对应（5 op，**没有 DELETE**）
 * ------------------------------------
 * | op | 仓储 |
 * |---|---|
 * | `GET /conversations` | {@link ConversationRepo.list} |
 * | `POST /conversations` | {@link ConversationRepo.create}（注入 `status`） |
 * | `GET /conversations/{id}` | 基类 `findById` |
 * | `PUT /conversations/{id}`（**只改 title**） | {@link ConversationRepo.rename} |
 * | `GET /conversations/{id}/messages` | `MessageRepo.list`（另一文件） |
 *
 * 基类自带的 `remove` **不暴露业务语义**：契约 5 op 里没有 DELETE，
 * 给它加业务方法等于凭空造一个契约外的删除口子（真删会话还会连带孤儿消息）。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { conversation as pgConversation } from "../schema/pg/conversation.js";
import { conversation as sqliteConversation } from "../schema/sqlite/conversation.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedPatch,
} from "./scoped-repo.js";

/** `conversation` 行。 */
export type ConversationRow = InferSelectModel<typeof pgConversation>;

/**
 * 会话状态缺省值（= 契约 `ConversationResponse.status` 的 `default: "ACTIVE"`）。
 *
 * **唯一定义处**：`create` 只在这里取缺省，别的层不得再写一遍字面量。
 */
export const CONVERSATION_STATUS_ACTIVE = "ACTIVE";

/** 创建会话的入参（`tenant_id` 与两个时间戳**故意不在**，由 scope / DDL 缺省负责）。 */
export interface CreateConversationInput {
  /** 主键。双档 DDL 的 `id` **无默认值** ⇒ 必须显式给（uuid）。 */
  readonly id: string;
  readonly workspaceId: string;
  readonly agentId: string;
  readonly userId: string;
  /** 标题。契约 `CreateConversationRequest.title` default `""`、maxLength 255。 */
  readonly title?: string;
  readonly organizationId?: string | null;
  /** 状态缺省 {@link CONVERSATION_STATUS_ACTIVE}。 */
  readonly status?: string;
}

export class ConversationRepo extends ScopedRepo<ConversationRow> {
  readonly #dialect: SqlDialect;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgConversation, sqliteConversation), scope);
    this.#dialect = dialect;
  }

  /**
   * 本租户的会话列表（最近的在前）。
   *
   * 排序按 `updated_at`：会话列表页的使用场景是"最近聊过的在前"，
   * 而 `created_at` 会让长期会话永远沉底。
   */
  list(options: ListOptions = {}): Promise<ConversationRow[]> {
    return this.findManyWhere(undefined, { orderBy: "updated_at", ...options });
  }

  /** 按 agent 列举会话：agent 也必须以 ``ScopedRef`` 传入（不能是裸 id）。 */
  listByAgent(agentRef: ScopedRef, options: ListOptions = {}): Promise<ConversationRow[]> {
    this.assertOwnRef(agentRef, "agentRef");
    return this.findManyWhere(eq(this.columns.agent_id, agentRef.id), options);
  }

  /** 按用户列举会话：同上，必须是本 scope 产出的引用。 */
  listByUser(userRef: ScopedRef, options: ListOptions = {}): Promise<ConversationRow[]> {
    this.assertOwnRef(userRef, "userRef");
    return this.findManyWhere(eq(this.columns.user_id, userRef.id), options);
  }

  /**
   * 创建会话，注入 `status` 缺省（{@link CONVERSATION_STATUS_ACTIVE}）。
   *
   * `tenant_id` / `created_at` / `updated_at` 一律不传：前两个由 `scope` 注入，
   * 后两个走 DDL 的 `DEFAULT CURRENT_TIMESTAMP`（双档同型）。
   */
  create(input: CreateConversationInput): Promise<ConversationRow> {
    return this.insertRow({
      id: input.id,
      organization_id: input.organizationId ?? null,
      workspace_id: input.workspaceId,
      agent_id: input.agentId,
      user_id: input.userId,
      title: input.title ?? "",
      status: input.status ?? CONVERSATION_STATUS_ACTIVE,
    } as never);
  }

  /**
   * 改标题（契约 `UpdateConversationRequest` **只有 `title`** ⇒ 本方法也只改标题）。
   *
   * 为什么同时写 `updated_at`：SQLite 的 `updated_at` 只有 `DEFAULT CURRENT_TIMESTAMP`、
   * **没有** `ON UPDATE` 触发器（零 DDL ⇒ 不能加）。若不显式写，会话改名后
   * `updated_at` 不动，按 `updated_at` 排序的列表就会出现"刚改过名的仍排在后面"
   * 这种哑故障。两个档位都显式写，行为才一致。
   *
   * @returns 更新后的行；不可见（404 口径）⇒ `null`。
   */
  rename(conversationRef: ScopedRef, title: string): Promise<ConversationRow | null> {
    this.assertOwnRef(conversationRef, "conversationRef");
    const patch = {
      title,
      updated_at: instantLiteral(this.#dialect, new Date()),
    } as unknown as TenantScopedPatch<ConversationRow>;
    return this.update(conversationRef, patch);
  }
}
