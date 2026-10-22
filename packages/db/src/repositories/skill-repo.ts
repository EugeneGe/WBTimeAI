/**
 * B2 · `skill` 族仓储（`skill` + `skill_version`，**一文件两类表**）。
 *
 * 为什么 `skill_version` 不单独建类
 * ------------------------------
 * 同裁定 ③（`agent_version` / `tool_version` 同风格）：「没有入口比入口抛错更强」。
 * `skill_version` 没有 `tenant_id`（DDL 实测）⇒ 独立建类只能走 `ChildScopedRepo`，
 * 而它的**全部**合法用法都必须先有一个"本 scope 可见的 skill"，那正是
 * {@link SkillRepo} 已经持有的东西（`skillRef` / `scope` / `dialect`）。多一个类只会
 * 多一个"可以绕过 skill 直接操作版本"的入口。
 *
 * ⚠️ 环状外键 ⇒ 插入序是**结构约束**，不是风格
 * ------------------------------------------
 * `skill.current_version_id → skill_version.id`
 * `skill_version.skill_id     → skill.id`
 * 两条 `FOREIGN KEY` 同时存在（SQLite 内联 / PG `ALTER TABLE`，两档等价，159/159），
 * 于是**唯一**可行的序列是：
 *
 *   1. `INSERT skill (current_version_id = NULL)` —— 先让 skill 存在但"无当前版本"；
 *   2. `INSERT skill_version (skill_id = 刚建的 skill)` —— 版本这时才能挂上去；
 *   3. `UPDATE skill SET current_version_id = 该版本` —— 最后把指针指过去。
 *
 * 反过来（先插版本再插 skill）在**数据库层**就过不去：`skill_version.skill_id` 指向
 * 尚不存在的行。`tests/b2-skill.test.mjs` 用两条 raw 插入把两个方向都钉死。
 *
 * 不可变口径（裁定 ⑤）
 * ------------------
 * 「`skill_version` 不可变」= **内容列不可变**（`version` / `instructions` / `manifest` /
 * `skill_id` / `created_by`）+ `status` **单列可迁移**。所以本类只开
 * {@link SkillRepo.updateVersionStatus}（且只允许 `status` 这一个键），不开通用 `update`。
 *
 * 状态值域（证据）
 * --------------
 * | 值 | 证据 |
 * |---|---|
 * | `skill.status`: `DRAFT` / `ACTIVE` / `ARCHIVED` | 契约 `UpdateSkillRequest.status` 的描述原文「生命周期状态（DRAFT/ACTIVE/ARCHIVED）」；`SkillResponse.status` default `DRAFT` |
 * | `skill_version.status`: `DRAFT` / `PUBLISHED` | `CreateSkillVersionRequest` 无 status ⇒ 契约 default `DRAFT`；前端服务注释「发布：把最新 `DRAFT` 版本冻结为 `PUBLISHED`」 |
 *
 * 本层**不**在发布时改 `skill.status`：契约对 publish 只说了"冻结该版本 + 更新
 * `current_version_id`"，对 `skill.status` 无一字 ⇒ 不替它猜一个迁移（裁定：不造成对称）。
 */

import {
  and,
  asc,
  desc,
  eq,
  getTableColumns,
  type AnyColumn,
  type InferSelectModel,
  type SQL,
  type Table,
} from "drizzle-orm";

import { skill as pgSkill, skill_version as pgSkillVersion } from "../schema/pg/skill.js";
import { skill as sqliteSkill, skill_version as sqliteSkillVersion } from "../schema/sqlite/skill.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import {
  resolveListLimit,
  ScopedRepo,
  ScopeError,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `skill` 行。 */
export type SkillRow = InferSelectModel<typeof pgSkill>;

/** `skill_version` 行。 */
export type SkillVersionRow = InferSelectModel<typeof pgSkillVersion>;

// ---------------------------------------------------------------------------
// 值域（证据见文件头注）
// ---------------------------------------------------------------------------

/** skill 生命周期：草稿（`SkillResponse.status` 的 default）。 */
export const SKILL_STATUS_DRAFT = "DRAFT";
/** skill 生命周期：已启用。 */
export const SKILL_STATUS_ACTIVE = "ACTIVE";
/** skill 生命周期：已归档。 */
export const SKILL_STATUS_ARCHIVED = "ARCHIVED";

/** skill 生命周期全集（顺序 = 契约 `UpdateSkillRequest` 描述的书写顺序）。 */
export const SKILL_STATUSES = [
  SKILL_STATUS_DRAFT,
  SKILL_STATUS_ACTIVE,
  SKILL_STATUS_ARCHIVED,
] as const;

/** 版本状态：草稿（`SkillVersionResponse.status` 的 default）。 */
export const SKILL_VERSION_STATUS_DRAFT = "DRAFT";
/** 版本状态：已发布（发布即冻结，见文件头注）。 */
export const SKILL_VERSION_STATUS_PUBLISHED = "PUBLISHED";

/** 版本状态全集（成员既不是子集也不是超集关系，两端都要逐项校验）。 */
export const SKILL_VERSION_STATUSES = [
  SKILL_VERSION_STATUS_DRAFT,
  SKILL_VERSION_STATUS_PUBLISHED,
] as const;

/** 是否 skill 生命周期值。 */
export function isSkillStatus(status: string): boolean {
  return (SKILL_STATUSES as readonly string[]).includes(status);
}

/** 是否 skill 版本状态值。 */
export function isSkillVersionStatus(status: string): boolean {
  return (SKILL_VERSION_STATUSES as readonly string[]).includes(status);
}

/** 创建 skill 的入参（`status` / `current_version_id` / `tenant_id` / 时间戳**故意不在**）。 */
export interface CreateSkillInput {
  readonly id: string;
  readonly name: string;
  /** 契约 `CreateSkillRequest.display_name` default `""`。 */
  readonly displayName?: string;
  /** 契约 `CreateSkillRequest.category` default `""`。 */
  readonly category?: string;
  readonly description?: string | null;
  readonly organizationId?: string | null;
  /** 创建者用户 id（列 NOT NULL ⇒ 必填）。 */
  readonly createdBy: string;
  /** 生命周期状态；缺省 {@link SKILL_STATUS_DRAFT}。 */
  readonly status?: string;
}

/** `skill` 元数据可改字段（= 契约 `UpdateSkillRequest` 的四个键，**不含** `name`）。 */
export interface UpdateSkillMetadataPatch {
  readonly display_name?: string;
  readonly description?: string | null;
  readonly category?: string;
  readonly status?: string;
}

/** 创建版本的入参（`skill_id` / `status` / 时间戳**故意不在**：父由 ref 给、状态恒 DRAFT）。 */
export interface CreateSkillVersionInput {
  readonly id: string;
  readonly version: string;
  /** 契约 `CreateSkillVersionRequest.instructions` default `""`。 */
  readonly instructions?: string;
  /** 契约 `CreateSkillVersionRequest.manifest` 是 object ⇒ 缺省 `{}`。 */
  readonly manifest?: Record<string, unknown>;
  /** 创建者用户 id（列 NOT NULL ⇒ 必填）。 */
  readonly createdBy: string;
}

/** 版本列表选项（版本表用 `created_at` 排序）。 */
export type SkillVersionListOptions = ListOptions;

export class SkillRepo extends ScopedRepo<SkillRow> {
  readonly #dialect: SqlDialect;
  readonly #table: Table;
  readonly #versionTable: Table;
  /** `skill_version` 的列（两表有同名列，传错会静默错配 ⇒ 只在此取一次）。 */
  readonly #versionColumns: Record<string, AnyColumn>;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    const table = resolveTable(dialect, pgSkill, sqliteSkill);
    super(db, table, scope);
    this.#dialect = dialect;
    this.#table = table;
    this.#versionTable = resolveTable(dialect, pgSkillVersion, sqliteSkillVersion);
    this.#versionColumns = getTableColumns(this.#versionTable) as Record<string, AnyColumn>;
  }

  /** 本租户的 skill 列表（最近更新在前；`updated_at` 秒粒度 ⇒ `id` 兜底）。 */
  list(options: ListOptions = {}): Promise<SkillRow[]> {
    return this.#orderedSkills(undefined, options);
  }

  /** 按名字取（`uq_skill_tenant_name`：租户内唯一）。 */
  findByName(name: string): Promise<SkillRow | null> {
    return this.findOneWhere(eq(this.columns.name, name));
  }

  /**
   * 创建 skill：`status` 缺省 `DRAFT`、`current_version_id` **恒为 `null`**。
   *
   * 为什么 `current_version_id` 不给参数：环状外键决定了"新 skill 不可能已有当前版本"
   * （见文件头注的插入序）。把它做成参数只会让调用方写出一条必然被外键拒掉的 SQL。
   */
  create(input: CreateSkillInput): Promise<SkillRow> {
    const status = input.status ?? SKILL_STATUS_DRAFT;
    if (!isSkillStatus(status)) {
      throw new ScopeError(
        `skill.create：status 必须是 ${SKILL_STATUSES.join(" | ")}，实测 ${JSON.stringify(status)}`,
      );
    }
    const now = instantLiteral(this.#dialect, new Date());
    const row: Record<string, unknown> = {
      id: input.id,
      organization_id: input.organizationId ?? null,
      name: input.name,
      display_name: input.displayName ?? "",
      description: input.description ?? null,
      category: input.category ?? "",
      status,
      current_version_id: null,
      created_by: input.createdBy,
      updated_at: now,
    };
    return this.insertRow(row as unknown as TenantScopedInsert<SkillRow>);
  }

  /**
   * 改元数据（= 契约 `PUT /skills/{id}` 的四个键）。
   *
   * `name` 不可改（它是 `uq(tenant_id, name)` 的成员，改名等于换身份）；`updated_at`
   * 显式推进（SQLite 无 `ON UPDATE` 触发器，不写就"刚改过的仍沉底"）。
   */
  updateMetadata(skillRef: ScopedRef, patch: UpdateSkillMetadataPatch): Promise<SkillRow | null> {
    this.assertOwnRef(skillRef, "skillRef");
    const allowed = new Set(["display_name", "description", "category", "status"]);
    for (const key of Object.keys(patch)) {
      if (!allowed.has(key)) {
        throw new ScopeError(
          `skill.updateMetadata：不支持的字段 ${key} —— 契约 UpdateSkillRequest 只有 ` +
            `${[...allowed].join(" / ")}（name 不可改）`,
        );
      }
    }
    if (patch.status !== undefined && !isSkillStatus(patch.status)) {
      throw new ScopeError(
        `skill.updateMetadata：status 必须是 ${SKILL_STATUSES.join(" | ")}，实测 ${JSON.stringify(patch.status)}`,
      );
    }
    const values: Record<string, unknown> = { ...patch, updated_at: instantLiteral(this.#dialect, new Date()) };
    return this.update(skillRef, values as never);
  }

  /**
   * 为某 skill 建一个 `DRAFT` 版本（`POST /skills/{id}/versions`）。
   *
   * 父必须在本 scope 可见（`skill` 是租户直挂表，查不到 ⇒ 抛 `ScopeError`，不退化空结果）；
   * `(skill_id, version)` 由 `uq_skill_version_skill_version` 唯一 ⇒ 应用层**先查后插**，
   * 给出可读错误而不是把驱动层的唯一约束报错抛给调用方。
   */
  async createVersion(
    skillRef: ScopedRef,
    input: CreateSkillVersionInput,
  ): Promise<SkillVersionRow> {
    await this.#assertVisibleSkill(skillRef);
    const existing = await this.findVersion(skillRef, input.version);
    if (existing !== null) {
      throw new ScopeError(
        `skill.createVersion：版本 ${input.version} 已存在于 skill ${skillRef.id}` +
          "（uq_skill_version_skill_version）—— 版本号不可复用",
      );
    }
    const values: Record<string, unknown> = {
      id: input.id,
      skill_id: skillRef.id,
      version: input.version,
      instructions: input.instructions ?? "",
      manifest: input.manifest ?? {},
      status: SKILL_VERSION_STATUS_DRAFT,
      created_by: input.createdBy,
    };
    const rows = await (this.db
      .insert(this.#versionTable)
      .values(values)
      .returning() as unknown as PromiseLike<SkillVersionRow[]>);
    const created = rows[0];
    if (created === undefined) {
      throw new ScopeError(`向 skill_version 插入后没有返回行（skill ${skillRef.id}）`);
    }
    return created;
  }

  /** 某 skill 的全部版本（新的在前；`created_at` 秒粒度 ⇒ `id` 兜底）。 */
  async listVersions(skillRef: ScopedRef, options: ListOptions = {}): Promise<SkillVersionRow[]> {
    await this.#assertVisibleSkill(skillRef);
    const limit = resolveListLimit(this.tableName, options.limit);
    const chain = this.db
      .select()
      .from(this.#versionTable)
      .where(eq(this.#versionColumns.skill_id, skillRef.id))
      .orderBy(desc(this.#versionColumns.created_at), asc(this.#versionColumns.id))
      .limit(limit);
    return (await chain).slice() as SkillVersionRow[];
  }

  /** 按版本号取（父必须可见；不存在 ⇒ `null`）。 */
  async findVersion(skillRef: ScopedRef, version: string): Promise<SkillVersionRow | null> {
    await this.#assertVisibleSkill(skillRef);
    const rows = await (this.db
      .select()
      .from(this.#versionTable)
      .where(
        and(
          eq(this.#versionColumns.skill_id, skillRef.id),
          eq(this.#versionColumns.version, version),
        ),
      )
      .limit(1));
    return (rows[0] as SkillVersionRow | undefined) ?? null;
  }

  /**
   * 按版本 **id** 取（T3-06 补：`resolveSkill` 需按 `skill.current_version_id` 指针
   * 反查版本行；既有 `findVersion` 只收版本号，指针是 id 对不上）。
   *
   * @param skillRef 父 skill 引用（必须可见；不可见 ⇒ `ScopeError`，同 {@link findVersion}）。
   * @param versionId 版本行 id。
   * @returns 版本行；不存在 / 归属不符（属于别的 skill）⇒ `null`。
   */
  async findVersionById(skillRef: ScopedRef, versionId: string): Promise<SkillVersionRow | null> {
    await this.#assertVisibleSkill(skillRef);
    const rows = await (this.db
      .select()
      .from(this.#versionTable)
      .where(
        and(
          eq(this.#versionColumns.skill_id, skillRef.id),
          eq(this.#versionColumns.id, versionId),
        ),
      )
      .limit(1));
    return (rows[0] as SkillVersionRow | undefined) ?? null;
  }

  /**
   * 只改版本 `status`（**不可变口径的唯一出口**，裁定 ⑤）。
   *
   * 为什么必须限定"只能改 status"：内容列一旦可变，"已发布快照"就不再是快照，
   * 历史 run 的复现性直接失效。所以这里不收 patch 对象，只收一个状态值，
   * 调用方连"顺手改 instructions"的写法都写不出来。
   *
   * @throws {ScopeError} 父不可见 / 状态值非法 / 版本不属于该 skill。
   */
  async updateVersionStatus(
    skillRef: ScopedRef,
    versionId: string,
    status: string,
  ): Promise<SkillVersionRow | null> {
    if (!isSkillVersionStatus(status)) {
      throw new ScopeError(
        `skill.updateVersionStatus：status 必须是 ${SKILL_VERSION_STATUSES.join(" | ")}，实测 ${JSON.stringify(status)}`,
      );
    }
    await this.#assertVisibleSkill(skillRef);
    const rows = await (this.db
      .update(this.#versionTable)
      .set({ status })
      .where(
        and(
          eq(this.#versionColumns.skill_id, skillRef.id),
          eq(this.#versionColumns.id, versionId),
        ),
      )
      .returning() as unknown as PromiseLike<SkillVersionRow[]>);
    return rows[0] ?? null;
  }

  /**
   * 发布（`POST /skills/{id}/publish`）：把**最新** `DRAFT` 版本冻结为 `PUBLISHED`，
   * 并把 `skill.current_version_id` 指向它。
   *
   * 顺序即环状外键的第三步：版本行早已存在（第 2 步），此时才能把指针指过去。
   *
   * @returns 被发布的版本行；**没有 DRAFT 版本可发** ⇒ `null`（调用方翻 409/404，
   *          本层不猜错误码 —— 同 `ApprovalRepo.decide` 的口径）。
   */
  async publish(skillRef: ScopedRef): Promise<SkillVersionRow | null> {
    await this.#assertVisibleSkill(skillRef);
    const drafts = await (this.db
      .select()
      .from(this.#versionTable)
      .where(
        and(
          eq(this.#versionColumns.skill_id, skillRef.id),
          eq(this.#versionColumns.status, SKILL_VERSION_STATUS_DRAFT),
        ),
      )
      .orderBy(desc(this.#versionColumns.created_at), desc(this.#versionColumns.id))
      .limit(1));
    const draft = drafts[0] as SkillVersionRow | undefined;
    if (draft === undefined) return null;

    const published = await this.updateVersionStatus(
      skillRef,
      draft.id,
      SKILL_VERSION_STATUS_PUBLISHED,
    );
    if (published === null) return null;

    // 指针最后指过去（第三步）。`updated_at` 显式写：SQLite 无 ON UPDATE。
    await this.update(skillRef, {
      current_version_id: published.id,
      updated_at: instantLiteral(this.#dialect, new Date()),
    } as never);
    return published;
  }

  // -------------------------------------------------------------------------
  // 私有
  // -------------------------------------------------------------------------

  /**
   * 父 skill 必须在本 scope 可见；返回该行（顺带把 `scope` 谓词打在最前面）。
   *
   * @throws {ScopeError} ref 非法 / 不可见（跨租户或不存在）。
   */
  async #assertVisibleSkill(skillRef: ScopedRef): Promise<SkillRow> {
    this.assertOwnRef(skillRef, "skillRef");
    const row = await this.findById(skillRef);
    if (row === null) {
      throw new ScopeError(
        `skill：父 skill ${skillRef.id} 在本 scope 下不可见（租户 ${this.scope.tenantId}）—— ` +
          "跨租户或不存在一律抛错，不返回空结果",
      );
    }
    return row;
  }

  /** skill 列表（`updated_at` 倒序 + `id` 兜底）。 */
  async #orderedSkills(condition: SQL | undefined, options: ListOptions): Promise<SkillRow[]> {
    const limit = resolveListLimit(this.tableName, options.limit);
    const orderColumn = this.columns[options.orderBy ?? "updated_at"];
    const primary: SQL[] =
      orderColumn === undefined
        ? []
        : [options.descending === false ? asc(orderColumn) : desc(orderColumn)];
    const chain = this.db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(condition))
      .orderBy(...primary, asc(this.columns.id))
      .limit(limit);
    return (await chain).slice() as SkillRow[];
  }
}
