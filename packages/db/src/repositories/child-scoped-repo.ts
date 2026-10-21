/**
 * T3-03 · ChildScopedRepo —— **父引用强制**的子资源仓储基类（**R3-22**）。
 *
 * 为什么必须有这个文件
 * --------------------
 * 运行时有三张表**没有 `tenant_id`**：`agent_event`（父 = `agent_run`）、
 * `tool_call`（父 = `agent_run`）、`message`（父 = `conversation`）。而
 * `ScopedRepo` 的构造函数在表缺少 `tenant_id` 列时**直接抛 `ScopeError`**
 * （头注原话：「子表不得直接建仓储，必须经父表的 scope 查询」）。
 *
 * 于是只剩两条路：扩 `UNSCOPED_WHITELIST`，或新开一个「父引用强制」的基类。
 * R3-22 明确选后者 —— 白名单一旦扩到这三张表，"没有 scope 也能查"就会被放给
 * 运行时最有价值的三张表（事件流 / 工具结果 / 对话消息）。
 *
 * 本基类把「没有父就查不到子」做成**结构约束**，而不是靠作者记得写 where：
 *
 *   1. 构造函数的第四个参数 `parentRef: ScopedRef` **没有默认值**，且必须是
 *      `Scope#ref()` 产出的带品牌引用 —— 裸 id 在类型层就传不进来；
 *   2. 父引用必须**属于本 scope**（`Scope#owns`），跨租户父 ref ⇒ 构造即抛
 *      `ScopeError`（**不是**返回空数组 —— 空数组会让"拿错租户的 run"看起来
 *      像"这个 run 没有事件"）；
 *   3. **首次使用前**再校验一次父行在本 scope 下真的可见（R3-22 原文要求）：
 *      父被删了 / 父属别的租户 ⇒ `ScopeError`。该检查在实例内**只做一次**
 *      （"首次使用"，不是每次查询都多打一条 SQL）；
 *   4. 所有查询都经 `#scopedWhere()`，它**永远**把父 id and 进条件 ——
 *      没有"不过滤"的分支，也没有"全表列表"入口。
 *
 * 与 `ScopedRepo` 的分工
 * ----------------------
 * `ScopedRepo` = 表有 `tenant_id`（租户直挂）；`ChildScopedRepo` = 表没有
 * `tenant_id`、靠父行回指租户。二者互斥：本基类在构造时**拒绝**带 `tenant_id`
 * 的表（那种表应当直接用 `ScopedRepo`，混用会让两套 scope 谓词同时出现）。
 *
 * 分层：drizzle-orm 的查询 API 只允许在 `src/repositories/` 里 import。
 */

import {
  and,
  asc,
  desc,
  eq,
  getTableColumns,
  getTableName,
  type AnyColumn,
  type SQL,
  type Table,
} from "drizzle-orm";

import {
  resolveListLimit,
  Scope,
  ScopeError,
  type DrizzleDatabase,
  type ListOptions,
  type ScopedDb,
  type ScopedRef,
} from "./scoped-repo.js";

/**
 * 子资源的**不变量冲突**（典型：`(run_id, seq)` 重复）。
 *
 * 为什么不是 `ScopeError`：那是 scope 用法错误，这是"约束缺失处的应用层护栏"
 * （R3-05：`agent_event.seq` 无唯一索引，重复必须由**代码**发现）。混成一个错误
 * 类型会让调用方无法区分「我用错了 scope」与「有人在并写得重复了」。
 *
 * 不是契约错误码：本类只在数据层抛出，由服务层翻译成相应错误（本版不新增码）。
 */
export class ChildConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChildConflictError";
  }
}

/** 子表插入入参：父列由基类注入，调用方**传不进来**。 */
export type ChildScopedInsert<TRow, TParentColumn extends string> = Omit<TRow, TParentColumn> & {
  readonly [K in TParentColumn]?: never;
};

/** 子表更新入参：主键与父列不可改。 */
export type ChildScopedPatch<TRow, TParentColumn extends string> = Partial<
  Omit<TRow, "id" | TParentColumn>
>;

/**
 * 子表列表选项：比 {@link ListOptions} 多一个 `seq`。
 *
 * 为什么不在 `ListOptions` 里加：`orderBy` 是**基类共享**的排序白名单，为一张子表
 * 的 `seq` 去放宽它，等于让所有 `ScopedRepo` 都能按一个多数表没有的列排序。
 * 这里只给子表开，且列不存在时基类同样**跳过排序**（不会生成非法 SQL）。
 */
export interface ChildListOptions extends Omit<ListOptions, "orderBy"> {
  readonly orderBy?: ListOptions["orderBy"] | "seq";
}

/** 基类构造选项。 */
export interface ChildRepoOptions {
  /** 父外键列名（`agent_event` / `tool_call` = `run_id`，`message` = `conversation_id`）。 */
  readonly parentColumn: string;
  /** 父的语义名（仅用于报错文案，如 `"run"`）。缺省取 {@link ChildRepoOptions.parentColumn}。 */
  readonly parentLabel?: string;
  /**
   * 「父在本 scope 下是否存在」的查询（由子类用**父表的 scoped 仓储**实现）。
   *
   * 为什么是回调而不是让基类自己查：基类不知道父表是哪张、也不知道父仓储怎么
   * 构造；把父表查询交给基类等于让它反过来依赖所有父仓储（成环）。子类各写一行
   * 闭包即可，且父查询**天然带 scope**（R3-22 的实质）。
   */
  readonly parentExists: (ref: ScopedRef) => Promise<boolean>;
}

/**
 * 子资源仓储基类。子类只声明「哪张表、哪些领域方法」，父引用纪律继承。
 */
export abstract class ChildScopedRepo<TRow extends object, TParentColumn extends string = string> {
  readonly #db: ScopedDb;
  readonly #table: Table;
  readonly #tableName: string;
  readonly #scope: Scope;
  readonly #parentRef: ScopedRef;
  readonly #parentColumn: AnyColumn;
  readonly #parentColumnName: string;
  readonly #parentLabel: string;
  readonly #parentExists: (ref: ScopedRef) => Promise<boolean>;
  readonly #columns: Record<string, AnyColumn>;
  #parentCheck: Promise<void> | null = null;

  protected constructor(
    db: DrizzleDatabase,
    table: Table,
    scope: Scope,
    parentRef: ScopedRef,
    options: ChildRepoOptions,
  ) {
    if (!(scope instanceof Scope)) {
      throw new ScopeError(
        "ChildScopedRepo 必须用 Scope 实例构造 —— 子表没有 tenant_id，租户归属全靠父引用的 scope",
      );
    }

    this.#db = db as unknown as ScopedDb;
    this.#table = table;
    this.#tableName = getTableName(table);
    this.#scope = scope;
    this.#parentRef = parentRef;
    this.#columns = getTableColumns(table) as Record<string, AnyColumn>;
    this.#parentColumnName = options.parentColumn;
    this.#parentLabel = options.parentLabel ?? options.parentColumn;
    this.#parentExists = options.parentExists;

    if (this.#columns.tenant_id !== undefined) {
      throw new ScopeError(
        `表 ${this.#tableName} 有 tenant_id 列 ⇒ 应当直接用 ScopedRepo（租户直挂）；` +
          "ChildScopedRepo 只服务无 tenant_id、靠父行回指租户的子表（R3-22）"
      );
    }

    const parentColumn = this.#columns[options.parentColumn];
    if (parentColumn === undefined) {
      throw new ScopeError(
        `表 ${this.#tableName} 没有父列 ${options.parentColumn} —— ` +
          "构造子仓储时必须给出正确的 parentColumn，否则每行都会变成孤儿"
      );
    }
    this.#parentColumn = parentColumn;

    // 闸门 2：父引用必须属于本 scope（跨租户 ⇒ 当场抛，不返回空数组）。
    if (!this.#scope.owns(parentRef)) {
      throw new ScopeError(
        `表 ${this.#tableName}：父 ${this.#parentLabel} 引用不是本 scope 产出的 ScopedRef，` +
          `或属于别的租户（仓储 scope = ${this.#scope.tenantId}）—— ` +
          "裸 id / 跨租户 ref 一律抛错（R3-22），绝不退化成空结果"
      );
    }
  }

  get scope(): Scope {
    return this.#scope;
  }

  /** 构造时传入的父引用（只读）。 */
  get parentRef(): ScopedRef {
    return this.#parentRef;
  }

  get tableName(): string {
    return this.#tableName;
  }

  /** 父行 id（子类拼业务查询时可用；**不是**可替换的构造参数）。 */
  protected get parentId(): string {
    return this.#parentRef.id;
  }

  protected get columns(): Record<string, AnyColumn> {
    return this.#columns;
  }

  protected get db(): ScopedDb {
    return this.#db;
  }

  // -------------------------------------------------------------------------
  // 父属主校验（R3-22：「首次使用前校验父属主」）
  // -------------------------------------------------------------------------

  /**
   * 校验父行在本 scope 下可见；**每个**对外方法都先过这一关。
   *
   * 只查一次（结果缓存在实例上）：仓储实例的生命周期通常与一次 run / 一次请求
   * 同长，反复查父表没有意义。父在实例创建之后被删除的情形，由数据库外键拦住
   * （`node:sqlite` 与 PG 均启用外键），不会静默产生孤儿行。
   */
  protected async ensureParent(): Promise<void> {
    this.#parentCheck ??= this.#checkParent();
    await this.#parentCheck;
  }

  async #checkParent(): Promise<void> {
    const exists = await this.#parentExists(this.#parentRef);
    if (!exists) {
      throw new ScopeError(
        `表 ${this.#tableName}：父 ${this.#parentLabel} ${this.#parentRef.id} 在本 scope 下不可见` +
          `（租户 ${this.#scope.tenantId}）—— 父不存在或父属别的租户，` +
          "一律抛 ScopeError，不返回空数组（R3-22）"
      );
    }
  }

  // -------------------------------------------------------------------------
  // 查询（父谓词恒在）
  // -------------------------------------------------------------------------

  /** 把父谓词 and 到调用方条件里。**所有**查询都必须经过它。 */
  protected scopedWhere(...conditions: (SQL | undefined)[]): SQL {
    const combined = and(
      eq(this.#parentColumn, this.#parentRef.id),
      ...conditions,
    );
    if (!combined) {
      // 理论上不可达（父谓词恒存在），但绝不允许「没条件 ⇒ 全表」的退化路径。
      throw new ScopeError(`表 ${this.#tableName} 的父谓词为空 —— 拒绝生成无限定查询`);
    }
    return combined;
  }

  /** 按父 + 子行 id 取单行（子行 id 是普通 uuid，父谓词由基类补上）。 */
  async findById(id: string): Promise<TRow | null> {
    await this.ensureParent();
    const rows = await (this.#db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(eq(this.#columns.id, id)))
      .limit(1) as unknown as PromiseLike<TRow[]>);
    return rows[0] ?? null;
  }

  protected async findOneWhere(condition: SQL | undefined): Promise<TRow | null> {
    await this.ensureParent();
    const rows = await (this.#db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(condition))
      .limit(1) as unknown as PromiseLike<TRow[]>);
    return rows[0] ?? null;
  }

  protected async findManyWhere(
    condition: SQL | undefined,
    options: ChildListOptions = {},
  ): Promise<TRow[]> {
    await this.ensureParent();
    const limit = resolveListLimit(this.#tableName, options.limit);
    let chain = this.#db.select().from(this.#table).where(this.scopedWhere(condition));
    const orderColumn = this.#columns[options.orderBy ?? "created_at"];
    if (orderColumn !== undefined) {
      chain = chain.orderBy(options.descending === false ? asc(orderColumn) : desc(orderColumn));
    }
    return (await (chain.limit(limit) as unknown as PromiseLike<TRow[]>)).slice();
  }

  // -------------------------------------------------------------------------
  // 写入（父列由基类注入）
  // -------------------------------------------------------------------------

  protected async insertRow(row: ChildScopedInsert<TRow, TParentColumn>): Promise<TRow> {
    await this.ensureParent();
    const values: Record<string, unknown> = { ...row };
    if (values[this.#parentColumnName] !== undefined) {
      throw new ScopeError(
        `表 ${this.#tableName}：插入入参不得自带 ${this.#parentColumnName} —— 父由构造时的 ScopedRef 注入`
      );
    }
    values[this.#parentColumnName] = this.#parentRef.id;
    const rows = await (this.#db
      .insert(this.#table)
      .values(values)
      .returning() as unknown as PromiseLike<TRow[]>);
    const created = rows[0];
    if (created === undefined) {
      throw new ScopeError(`向 ${this.#tableName} 插入后没有返回行`);
    }
    return created;
  }

  /** 按父 + 子行 id 更新；返回更新后的行（不可见 ⇒ `null`）。 */
  async update(id: string, patch: ChildScopedPatch<TRow, TParentColumn>): Promise<TRow | null> {
    await this.ensureParent();
    if ("id" in patch || this.#parentColumnName in patch) {
      throw new ScopeError(
        `表 ${this.#tableName}：patch 不得包含 id / ${this.#parentColumnName} —— 主键与父归属不可改`
      );
    }
    const rows = await (this.#db
      .update(this.#table)
      .set(patch as Record<string, unknown>)
      .where(this.scopedWhere(eq(this.#columns.id, id)))
      .returning() as unknown as PromiseLike<TRow[]>);
    return rows[0] ?? null;
  }

  /** 在父内按附加条件**批量**更新（父谓词恒在）。 */
  protected async updateManyWhere(
    condition: SQL | undefined,
    patch: ChildScopedPatch<TRow, TParentColumn>,
  ): Promise<TRow[]> {
    await this.ensureParent();
    if ("id" in patch || this.#parentColumnName in patch) {
      throw new ScopeError(
        `表 ${this.#tableName}：patch 不得包含 id / ${this.#parentColumnName} —— 主键与父归属不可改`
      );
    }
    const rows = await (this.#db
      .update(this.#table)
      .set(patch as Record<string, unknown>)
      .where(this.scopedWhere(condition))
      .returning() as unknown as PromiseLike<TRow[]>);
    return rows.slice();
  }

  /** 按父 + 子行 id 删除；返回是否真的删掉了一行。 */
  async remove(id: string): Promise<boolean> {
    await this.ensureParent();
    const rows = await (this.#db
      .delete(this.#table)
      .where(this.scopedWhere(eq(this.#columns.id, id)))
      .returning() as unknown as PromiseLike<TRow[]>);
    return rows.length > 0;
  }
}
