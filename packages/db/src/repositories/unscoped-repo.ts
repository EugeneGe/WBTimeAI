/**
 * T2-03 · 三个**白名单通道**的基类（unscoped，但有硬闸门）。
 *
 * 为什么会有「没有 scope 的仓储」
 * ------------------------------
 * `ScopedRepo` 构造时若表没有 `tenant_id` 列，**直接抛 `ScopeError`**
 * （`scoped-repo.ts` 的构造校验，实测行为）。而身份域有三张表**本来就没有**
 * `tenant_id`，且不是疏漏：
 *
 * | 表 | 为什么可以没有 scope |
 * |---|---|
 * | `permission` | 平台级权限码字典：`code` 全平台唯一一份，不该按租户复制 |
 * | `role_permission` | role×permission 连接；租户归属经 `role.tenant_id` **回指** |
 * | `login_attempt` | 登录尝试流水；「租户未知 / 用户不存在」时也必须能落库，否则限速无数据源 |
 *
 * **白名单只此三处**（计划 `§2 数据模型落点`）。为了避免"只此三处"退化成口号，
 * 本基类做了两道运行时闸门：
 *
 * 1. 表名必须在 {@link UNSCOPED_WHITELIST} 里 —— 想给别的表建 unscoped 仓储，
 *    构造即抛 `ScopeError`（判红在构造函数，不在 code review）；
 * 2. 必须给出非空的 `purpose`（"为什么它可以没有 scope"）—— 逼着作者在**调用点**
 *    写下理由，而不是在某个文档里写一句然后被遗忘。
 *
 * 注意：白名单通道**不是**"可以随便查"。它们的领域方法必须自带限定：
 * `RolePermissionCatalog` 只接受**已由 `RoleRepo`（scoped）筛过的 role id**，
 * `LoginAttemptSink` 只按 `username` 查最近 N 条 —— 都不提供"全表列表"入口。
 */

import {
  asc,
  desc,
  getTableColumns,
  getTableName,
  type AnyColumn,
  type SQL,
  type Table,
} from "drizzle-orm";

import {
  resolveListLimit,
  ScopeError,
  type DrizzleDatabase,
  type ListOptions,
  type ScopedDb,
} from "./scoped-repo.js";

/**
 * 白名单登记表：键 = 表名，值 = 「为什么它可以没有 scope」的**强制理由**。
 *
 * 这张表就是代码里的台账。新增一项 = 在本文件 diff 里公开新增一条 unscoped 通道，
 * 评审时无法"顺手带过"。
 */
export const UNSCOPED_WHITELIST = Object.freeze({
  permission:
    "平台级权限码字典（`code` 全平台唯一一份）：不按租户复制，故无 tenant_id 列；" +
    "只读字典，不含任何租户私有数据。",
  role_permission:
    "role×permission 连接表：租户归属经 `role.tenant_id` 回指，连接行自身无 tenant_id；" +
    "本通道只接受**已由 RoleRepo（scoped）筛出的 role id 集合**，故不会跨租户扩散。",
  login_attempt:
    "登录尝试流水（限速唯一数据源）：登录**前**租户/用户可能都未知（用户名不存在、租户 slug 打错），" +
    "此时仍必须落库，否则「连续失败 5 次锁定」永远数不到那几次失败。故无 Scope。",
} as const);

/** 白名单表名联合类型。 */
export type UnscopedTableName = keyof typeof UNSCOPED_WHITELIST;

/** 白名单表名的运行时集合（用于闸门 1）。 */
const WHITELISTED_TABLE_NAMES: ReadonlySet<string> = new Set<string>(
  Object.keys(UNSCOPED_WHITELIST)
);

/**
 * 白名单通道基类。**只能**被 `permission` / `role_permission` / `login_attempt` 使用。
 *
 * 与 `ScopedRepo` 的差别只有两点：① 不注入 `tenant_id`（这几张表没有或不该由 scope 决定）；
 * ② 不 and `tenant_id` 谓词（没有该列）。除此之外的纪律一致：**不暴露裸 where**、
 * limit 规则同一套（`resolveListLimit`）、不返回可被拿去拼 SQL 的东西。
 */
export abstract class UnscopedTableRepo<TRow extends object> {
  readonly #db: ScopedDb;
  readonly #table: Table;
  readonly #tableName: string;
  readonly #columns: Record<string, AnyColumn>;

  /**
   * @param db drizzle 实例
   * @param table 表对象（必须是白名单三张之一）
   * @param purpose 「为什么它可以没有 scope」—— 非空，且必须与登记表口径一致
   */
  protected constructor(db: DrizzleDatabase, table: Table, purpose: string) {
    this.#tableName = getTableName(table);
    if (!WHITELISTED_TABLE_NAMES.has(this.#tableName)) {
      throw new ScopeError(
        `表 ${this.#tableName} 不在 unscoped 白名单内 —— 本项目只允许 ` +
          `${[...WHITELISTED_TABLE_NAMES].join(" / ")} 三张表无 scope 访问；` +
          "其余表一律经 ScopedRepo（跨租户 ⇒ 查不到 ⇒ 404）"
      );
    }
    if (typeof purpose !== "string" || purpose.trim() === "") {
      throw new ScopeError(`表 ${this.#tableName}：unscoped 通道必须写明理由（purpose 非空）`);
    }
    this.#db = db as unknown as ScopedDb;
    this.#table = table;
    this.#columns = getTableColumns(table) as Record<string, AnyColumn>;
  }

  get tableName(): string {
    return this.#tableName;
  }

  /** 该表上的列（只读快照）。 */
  protected get columns(): Record<string, AnyColumn> {
    return this.#columns;
  }

  protected get db(): ScopedDb {
    return this.#db;
  }

  /** 本通道豁免 scope 的理由（供审计/日志/测试断言，不在 UI 暴露）。 */
  protected get whitelistReason(): string {
    return UNSCOPED_WHITELIST[this.#tableName as UnscopedTableName];
  }

  // -------------------------------------------------------------------------
  // 受保护的查询/写入原语（子类只能经它们访问数据）
  // -------------------------------------------------------------------------

  /** 按条件列举；无 condition 时 `undefined` 表示「不加额外条件」（但仍受白名单约束）。 */
  protected async findManyWhere(
    condition: SQL | undefined,
    options: ListOptions = {}
  ): Promise<TRow[]> {
    const limit = resolveListLimit(this.#tableName, options.limit);
    const chain = this.#db.select().from(this.#table).where(condition);
    const orderColumn = this.#columns[options.orderBy ?? "created_at"];
    const ordered = orderColumn
      ? chain.orderBy(options.descending === false ? asc(orderColumn) : desc(orderColumn))
      : chain;
    return (await (ordered.limit(limit) as unknown as PromiseLike<TRow[]>)).slice();
  }

  /** 按条件取单行。 */
  protected async findOneWhere(condition: SQL | undefined): Promise<TRow | null> {
    const rows = await (this.#db
      .select()
      .from(this.#table)
      .where(condition)
      .limit(1) as unknown as PromiseLike<TRow[]>);
    return rows[0] ?? null;
  }

  /**
   * 插入一行（**不**注入任何租户列：这几张表没有或不由 scope 决定）。
   *
   * 入参是裸列映射而不是 `Partial<TRow>`：SQLite 档与 PG 档的时间列在运行时形状不同
   * （文本 vs `Date`），用行类型约束反而会逼调用方做无意义的类型断言（见 `dialect.ts`）。
   * 代价是"列名写错"由 SQL 报错兜底 —— 而本基类的使用者只有三处，评审可见。
   */
  protected async insertRow(row: Record<string, unknown>): Promise<TRow> {
    const rows = await (this.#db
      .insert(this.#table)
      .values(row)
      .returning() as unknown as PromiseLike<TRow[]>);
    const created = rows[0];
    if (!created) throw new ScopeError(`向 ${this.#tableName} 插入后没有返回行`);
    return created;
  }

  /** 按条件批量更新，返回被改到的行。 */
  protected async updateWhere(
    condition: SQL | undefined,
    patch: Record<string, unknown>
  ): Promise<TRow[]> {
    if ("id" in patch) {
      throw new ScopeError("patch 不得包含 id —— 主键不可改");
    }
    const rows = await (this.#db
      .update(this.#table)
      .set(patch)
      .where(condition)
      .returning() as unknown as PromiseLike<TRow[]>);
    return rows.slice();
  }
}
