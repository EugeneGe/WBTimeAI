/**
 * T1-03 · ScopedRepo —— **签名层面**强制 scope 过滤的泛型仓储基类。
 *
 * 为什么要有这个文件
 * ------------------
 * 本项目纪律 I-2：**禁止裸 id 查询**。多租户系统里 ``WHERE id = ?`` 少写一个
 * ``tenant_id`` 就是跨租户数据泄漏，而且这类 bug 在单租户的测试数据上永远是绿的。
 * 运行时 if 检查挡不住它（总有人新写一个方法忘了调），所以本基类把「没有 scope
 * 就构造不出查询」做成**类型约束**：
 *
 * 1. 构造函数是 ``protected``，第三个参数 ``scope: Scope`` **没有默认值** ——
 *    子类不传 scope 连 ``super()`` 都编译不过；
 * 2. 公开方法里**没有任何一个接受裸 id**：``findById`` 收的是 ``ScopedRef``，
 *    而 ``ScopedRef`` 带一个未导出的 ``unique symbol`` 品牌，外部无法伪造，
 *    只能由 ``Scope#ref(id)`` 生产；
 * 3. 所有查询都经 ``#scopedWhere()``，它**永远**把 ``tenant_id``（以及可选的
 *    ``workspace_id``）and 进条件里 —— 没有「不过滤」的分支；
 * 4. ``insert`` 的入参类型把 ``tenant_id`` 设成 ``never``，租户由 scope 注入，
 *    调用方连传都传不进来。
 *
 * 运行时另有一层品牌校验（``ref.tenantId !== scope.tenantId`` 直接抛），
 * 那是纵深防御，不是主要手段。
 *
 * 分层：drizzle-orm 的查询 API 只允许在 ``src/repositories/`` 里 import。
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

/** 品牌键：**不导出**。没有它就无法构造出合法的 ``ScopedRef``。 */
const REF_BRAND: unique symbol = Symbol.for("wbtime.db.ScopedRef");

/** 只能在某个 ``Scope`` 名下存在的实体引用。 */
export interface ScopedRef {
  readonly id: string;
  readonly tenantId: string;
  readonly [REF_BRAND]: true;
}

/** scope 相关的用法错误（与业务错误区分开：这是**编程错误**，不该被 try/catch 吞掉）。 */
export class ScopeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ScopeError";
  }
}

/**
 * 租户作用域。**所有**数据访问都必须先有它。
 *
 * ``workspaceId`` 给了就同时锁定工作区（多工作区表）；不给表示「该租户下全部工作区」。
 */
export class Scope {
  readonly tenantId: string;
  readonly workspaceId: string | null;

  constructor(tenantId: string, workspaceId?: string | null) {
    if (typeof tenantId !== "string" || tenantId.trim() === "") {
      throw new ScopeError("Scope 必须带非空 tenantId —— 空 scope 等于没有 scope");
    }
    this.tenantId = tenantId;
    this.workspaceId = workspaceId ?? null;
  }

  /** 把一个 id 提升为带 scope 的引用。**唯一**的 ``ScopedRef`` 生产入口。 */
  ref(id: string): ScopedRef {
    if (typeof id !== "string" || id.trim() === "") {
      throw new ScopeError("ScopedRef 需要非空 id");
    }
    return Object.freeze({ id, tenantId: this.tenantId, [REF_BRAND]: true as const });
  }

  /** 该引用是否属于本 scope（纵深防御用，正常代码不需要调）。 */
  owns(ref: ScopedRef): boolean {
    return isScopedRef(ref) && ref.tenantId === this.tenantId;
  }
}

function isScopedRef(value: unknown): value is ScopedRef {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<symbol, unknown>)[REF_BRAND] === true &&
    typeof (value as { id?: unknown }).id === "string"
  );
}

// ---------------------------------------------------------------------------
// drizzle 的最小结构端口（PG / SQLite 两档共用；只声明本基类用到的那些方法）
// ---------------------------------------------------------------------------

/** 任意 drizzle 数据库实例（``PgDatabase`` / ``BaseSQLiteDatabase`` 都结构化满足它）。 */
export interface DrizzleDatabase {
  readonly select: (...args: never[]) => unknown;
  readonly insert: (...args: never[]) => unknown;
  readonly update: (...args: never[]) => unknown;
  readonly delete: (...args: never[]) => unknown;
}

/**
 * 查询链的最小结构端口。
 *
 * 为什么 export：`./unscoped-repo.ts`（三个白名单通道的基类）需要**同一个**端口，
 * 若各自再声明一份，两处形状就会漂移（改了这里忘了那里，直到运行时才发现）。
 * 单一来源比"不导出内部类型"更重要。**不从 `repositories/index.ts` 再导出**，
 * 故不构成对外的公共 API 扩张。
 */
export interface QueryChain extends PromiseLike<Record<string, unknown>[]> {
  where(condition: SQL | undefined): QueryChain;
  limit(count: number): QueryChain;
  orderBy(...columns: (AnyColumn | SQL)[]): QueryChain;
  returning(): QueryChain;
}

/** 任意 drizzle 数据库实例的最小查询端口（见 {@link QueryChain} 的导出说明）。 */
export interface ScopedDb {
  select(): { from(table: Table): QueryChain };
  insert(table: Table): { values(row: Record<string, unknown>): QueryChain };
  update(table: Table): { set(patch: Record<string, unknown>): QueryChain };
  delete(table: Table): QueryChain;
}

/** 插入入参：``tenant_id`` 交给 scope 注入，调用方**传不进来**。 */
export type TenantScopedInsert<TRow> = Omit<TRow, "tenant_id"> & { readonly tenant_id?: never };

/** 更新入参：主键与租户列不可改。 */
export type TenantScopedPatch<TRow> = Partial<Omit<TRow, "id" | "tenant_id">>;

/** 列表查询的公共选项（刻意**不**暴露裸 where —— 过滤条件只能经 scope 拼接）。 */
export interface ListOptions {
  /** 上限条数。缺省 100，合法区间 1..500；**非法值抛 ScopeError，不静默修正**。 */
  readonly limit?: number;
  readonly orderBy?: "created_at" | "updated_at" | "id";
  readonly descending?: boolean;
}

const DEFAULT_LIMIT = 100;
const MAX_LIMIT = 500;

/**
 * 解析 list limit：显式传入必须是 `1..MAX_LIMIT` 的整数，否则抛错。
 *
 * 为什么不再 `Math.min(Math.max(...))` 静默夹取：
 * 静默修正会把调用方的**编程错误**变成「行为看起来正常、结果却少了行」。
 * 典型后果是 `limit: 0` 被夹成 1（少查）、`limit: 9999` 被夹成 500（悄悄截断
 * 分页）——两种都不会报错，只会安静地给出不完整数据，正是本项目要消灭的哑失败。
 * 缺省（未传）仍走 DEFAULT_LIMIT，那是**约定值**而非对非法值的兜底。
 *
 * 导出原因：`./unscoped-repo.ts` 的白名单通道要**同一条**规则；各写一份必然漂移。
 */
export function resolveListLimit(tableName: string, limit: number | undefined): number {
  if (limit === undefined) return DEFAULT_LIMIT;
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    throw new ScopeError(
      `表 ${tableName}：list limit 非法（实测 ${String(limit)}，类型 ${typeof limit}），` +
        `合法区间为 1..${MAX_LIMIT} 的整数 —— 非法值直接拒绝，不静默夹取`
    );
  }
  return limit;
}

/**
 * 基类构造选项（**只为一处例外开的口子**，默认全关）。
 *
 * 背景：`tenant` 表是隔离顶点的**自身**（行 `id` 就是租户 id），它没有也不可能有
 * `tenant_id` 列。若不给一个显式开关，`TenantRepo` 就只能绕过 `ScopedRepo` 自己拼
 * where —— 那才是真正的纪律破口。因此这里把「哪一列承载 scope 谓词」做成**显式声明**：
 *
 * * 默认（`selfScoped` 缺省 / `false`）：`tenant_id` 承载谓词，且 insert 时由 scope 注入；
 * * `selfScoped: true`（**仅 `tenant` 一张表**）：`id` 承载谓词，insert 时不注入 `tenant_id`。
 *
 * 两种模式下 `scopedWhere()` 都**恒** and 一个 scope 谓词，没有「不过滤」的分支，
 * 因此 I-1/I-2 的实质不变：跨 scope 查询依然查不到行（→ 404），而非返 403。
 */
export interface ScopedRepoOptions {
  /** 该表的 scope 谓词由 `id` 列承载（行 id 即租户 id）。仅供 `TenantRepo` 使用。 */
  readonly selfScoped?: boolean;
}

/**
 * 泛型仓储基类。子类只声明「哪张表、哪些领域方法」，scope 纪律继承。
 */
export abstract class ScopedRepo<TRow extends object> {
  readonly #db: ScopedDb;
  readonly #table: Table;
  readonly #tableName: string;
  readonly #scope: Scope;
  readonly #columns: Record<string, AnyColumn>;
  readonly #tenantColumn: AnyColumn;
  readonly #workspaceColumn: AnyColumn | null;
  readonly #injectsTenantId: boolean;

  protected constructor(
    db: DrizzleDatabase,
    table: Table,
    scope: Scope,
    options: ScopedRepoOptions = {}
  ) {
    if (!(scope instanceof Scope)) {
      throw new ScopeError(
        "ScopedRepo 必须用 Scope 实例构造 —— 本项目 I-2：禁裸 id 查询，没有 scope 就没有仓储"
      );
    }
    this.#db = db as unknown as ScopedDb;
    this.#table = table;
    this.#tableName = getTableName(table);
    this.#scope = scope;
    this.#columns = getTableColumns(table) as Record<string, AnyColumn>;
    this.#injectsTenantId = options.selfScoped !== true;

    const tenantColumn = options.selfScoped === true ? this.#columns.id : this.#columns.tenant_id;
    if (!tenantColumn) {
      throw new ScopeError(
        `表 ${this.#tableName} 没有 tenant_id 列 —— 子表（如 agent_event）不得直接建仓储，` +
          "必须经父表的 scope 查询"
      );
    }
    this.#tenantColumn = tenantColumn;
    this.#workspaceColumn = this.#columns.workspace_id ?? null;
  }

  get scope(): Scope {
    return this.#scope;
  }

  get tableName(): string {
    return this.#tableName;
  }

  /** 该表上的列（只读快照，避免子类各自 getTableColumns 一遍）。 */
  protected get columns(): Record<string, AnyColumn> {
    return this.#columns;
  }

  protected get db(): ScopedDb {
    return this.#db;
  }

  // -------------------------------------------------------------------------
  // 查询
  // -------------------------------------------------------------------------

  /**
   * 把 scope 谓词 and 到调用方条件里。**所有**查询都必须经过它。
   *
   * ``workspace_id`` 仅在 scope 指定了 workspace 时参与过滤；表没有该列时自动跳过。
   */
  protected scopedWhere(...conditions: (SQL | undefined)[]): SQL {
    const predicates: (SQL | undefined)[] = [eq(this.#tenantColumn, this.#scope.tenantId)];
    if (this.#scope.workspaceId !== null && this.#workspaceColumn !== null) {
      predicates.push(eq(this.#workspaceColumn, this.#scope.workspaceId));
    }
    predicates.push(...conditions);
    const combined = and(...predicates);
    if (!combined) {
      // 理论上不可达（tenant 谓词恒存在），但绝不允许「没条件 ⇒ 全表」的退化路径。
      throw new ScopeError(`表 ${this.#tableName} 的 scope 谓词为空 —— 拒绝生成无限定查询`);
    }
    return combined;
  }

  /** 按 scope 内引用取单行。**不接受裸 id**。 */
  async findById(ref: ScopedRef): Promise<TRow | null> {
    this.#assertRef(ref);
    const rows = await (this.#db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(eq(this.#columns.id, ref.id)))
      .limit(1) as unknown as PromiseLike<TRow[]>);
    return rows[0] ?? null;
  }

  /** 在 scope 内按附加条件取单行。 */
  protected async findOneWhere(condition: SQL | undefined): Promise<TRow | null> {
    const rows = await (this.#db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(condition))
      .limit(1) as unknown as PromiseLike<TRow[]>);
    return rows[0] ?? null;
  }

  /** 在 scope 内列举。 */
  protected async findManyWhere(condition: SQL | undefined, options: ListOptions = {}): Promise<TRow[]> {
    const limit = resolveListLimit(this.#tableName, options.limit);
    let chain = this.#db.select().from(this.#table).where(this.scopedWhere(condition));
    const orderColumn = this.#columns[options.orderBy ?? "created_at"];
    if (orderColumn) {
      chain = chain.orderBy(options.descending === false ? asc(orderColumn) : desc(orderColumn));
    }
    return (await (chain.limit(limit) as unknown as PromiseLike<TRow[]>)).slice();
  }

  // -------------------------------------------------------------------------
  // 写入
  // -------------------------------------------------------------------------

  /** 插入：``tenant_id`` / ``workspace_id`` 由 scope 注入，调用方传不进来。 */
  protected async insertRow(row: TenantScopedInsert<TRow>): Promise<TRow> {
    const values: Record<string, unknown> = { ...row };
    // 自作用域表（tenant）没有 tenant_id 列，注入即 SQL 报错 —— 故由选项显式关闭。
    if (this.#injectsTenantId) values.tenant_id = this.#scope.tenantId;
    if (this.#scope.workspaceId !== null && this.#workspaceColumn !== null) {
      values.workspace_id = this.#scope.workspaceId;
    }
    const rows = await (this.#db
      .insert(this.#table)
      .values(values)
      .returning() as unknown as PromiseLike<TRow[]>);
    const created = rows[0];
    if (!created) throw new ScopeError(`向 ${this.#tableName} 插入后没有返回行`);
    return created;
  }

  /** 按 scope 内引用更新。 */
  async update(ref: ScopedRef, patch: TenantScopedPatch<TRow>): Promise<TRow | null> {
    this.#assertRef(ref);
    if ("id" in patch || "tenant_id" in patch) {
      throw new ScopeError("patch 不得包含 id / tenant_id —— 主键与租户归属不可改");
    }
    const rows = await (this.#db
      .update(this.#table)
      .set(patch as Record<string, unknown>)
      .where(this.scopedWhere(eq(this.#columns.id, ref.id)))
      .returning() as unknown as PromiseLike<TRow[]>);
    return rows[0] ?? null;
  }

  /**
   * 在 scope 内按附加条件**批量**更新，返回被改到的行。
   *
   * 为「撤销会话 / 撤销 refresh / 全端退出」这类需要 `WHERE ... AND revoked_at IS NULL`
   * 的幂等写入而开：没有它，子类只能自己 `db.update(table)` 拼 where —— 一旦忘了
   * 带上 scope 谓词就是跨租户写入。这里把条件与 scope 谓词的 and 固化在基类。
   *
   * 条件**不含 id** 属正常用法（批量），但 scope 谓词恒在，故最多命中本租户的行。
   */
  protected async updateManyWhere(
    condition: SQL | undefined,
    patch: TenantScopedPatch<TRow>
  ): Promise<TRow[]> {
    if ("id" in patch || "tenant_id" in patch) {
      throw new ScopeError("patch 不得包含 id / tenant_id —— 主键与租户归属不可改");
    }
    const rows = await (this.#db
      .update(this.#table)
      .set(patch as Record<string, unknown>)
      .where(this.scopedWhere(condition))
      .returning() as unknown as PromiseLike<TRow[]>);
    return rows.slice();
  }

  /** 按 scope 内引用删除；返回是否真的删掉了一行。 */
  async remove(ref: ScopedRef): Promise<boolean> {
    this.#assertRef(ref);
    const rows = await (this.#db
      .delete(this.#table)
      .where(this.scopedWhere(eq(this.#columns.id, ref.id)))
      .returning() as unknown as PromiseLike<TRow[]>);
    return rows.length > 0;
  }

  /**
   * 子类要把**外部**传入的 ``ScopedRef`` 用于跨表过滤（如「按 agent 列举会话」）时，
   * 必须先过这一关：确认它确实由 ``Scope#ref()`` 产出、且属于本 scope。
   */
  protected assertOwnRef(ref: ScopedRef, label = "ref"): void {
    try {
      this.#assertRef(ref);
    } catch (error) {
      throw new ScopeError(`${label} 不合法：${(error as Error).message}`);
    }
  }

  #assertRef(ref: ScopedRef): void {
    if (!isScopedRef(ref)) {
      throw new ScopeError(
        `表 ${this.#tableName}：findById/update/remove 只接受 Scope#ref(id) 产出的 ScopedRef，` +
          "裸 id 字符串在类型层就不该通过 —— 拿到运行时说明绕过了类型系统"
      );
    }
    if (ref.tenantId !== this.#scope.tenantId) {
      throw new ScopeError(
        `表 ${this.#tableName}：ref 属于租户 ${ref.tenantId}，仓储 scope 是 ${this.#scope.tenantId}`
      );
    }
  }
}
