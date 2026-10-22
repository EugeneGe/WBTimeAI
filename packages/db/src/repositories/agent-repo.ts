/**
 * B2 · `agent` 族仓储（`agent` + `agent_version`，**一文件两类表**）。
 *
 * 为什么 `agent_version` 不单独建类
 * --------------------------------
 * 同 `skill-repo` 的裁定 ③（`skill_version` 同风格）：「没有入口比入口抛错更强」。
 * `agent_version` 没有 `tenant_id`（DDL 实测）⇒ 独立建类只能走 `ChildScopedRepo`，
 * 而它的**全部**合法用法都必须先有一个"本 scope 可见的 agent"，那正是
 * {@link AgentRepo} 已经持有的东西（`agentRef` / `scope` / `dialect`）。多一个类只会
 * 多一个"可以绕过 agent 直接操作版本"的入口。
 *
 * ⚠️ 环状外键 ⇒ 插入序是**结构约束**，不是风格
 * ------------------------------------------
 * `agent.current_version_id → agent_version.id`
 * `agent_version.agent_id     → agent.id`
 * 两条 `FOREIGN KEY` 同时存在（两档等价，159/159），于是**唯一**可行的序列是：
 *
 *   1. `INSERT agent (current_version_id = NULL)` —— 先让 agent 存在但"无当前版本"
 *     （{@link AgentRepo.create} 把 `current_version_id` 做成**不可传**：新 agent
 *      不可能已有版本，传了必然被外键拒掉）；
 *   2. `INSERT agent_version (agent_id = 刚建的 agent)` —— 版本这时才能挂上去
 *      （{@link AgentRepo.publishVersion} 前置 `#assertVisibleAgent`）；
 *   3. `UPDATE agent SET current_version_id = 该版本` —— 最后把指针指过去。
 *
 * `tests/b2-agent.test.mjs` 用原生插入钉住"步骤 1 带非 NULL 指针必被外键拒"。
 *
 * 状态值域与迁移矩阵（**逐条给证据**；本层常量在 `packages/db` 复述而非 import
 * `packages/domain` —— db 不依赖 domain，同批次 A 偏差 #5 口径）
 * ------------------------------
 * | 值 | 证据 |
 * |---|---|
 * | `agent.status`: `DRAFT` / `ACTIVE` / `ARCHIVED` | py 线 oracle `constants.py:47-49`（`AGENT_STATUS_DRAFT/ACTIVE/ARCHIVED`）+ 前端 DTO `apps/web/src/types/phase1.ts:18` + 契约 `AgentResponse.status` default `DRAFT` |
 * | `agent_version.status`: `DRAFT` / `PUBLISHED` / `DEPRECATED` | py 线 oracle `constants.py:52-54`（`AGENT_VERSION_STATUS_*`）|
 * | `agent.type`: `PRIMARY` / `SUB_AGENT` / `WORKFLOW_AGENT` / `SCHEDULED_AGENT` / `EVENT_AGENT` | py 线 `constants.py:40-44` + 契约 `CreateAgentRequest.type` default `PRIMARY` |
 *
 * 迁移矩阵（`AGENT_STATUS_TRANSITIONS`，方向 = from → 允许的 to）：
 *
 *   - `DRAFT → ACTIVE`：py 线 `agent_service.publish_version` 发布即置
 *     `agent.status = AGENT_STATUS_ACTIVE`（`agent_service.py:128`）—— 发布路径实证；
 *   - `ARCHIVED → ACTIVE`：同一条 py 代码是**无条件**置 ACTIVE（不判当前状态）⇒
 *     归档 agent 再发布即复活 —— 同一行实证；
 *   - `DRAFT → ARCHIVED` / `ACTIVE → ARCHIVED`：py 线 `PUT /agents` 直接赋值不校验
 *     （`commands/agent.py:91-92`），本层按词表语义收紧为"弃置/下线走归档"并登记为
 *     施工期假设（见施工记录偏差表）—— py 的"任意赋值"不是可依赖的语义，是**缺校验**；
 *   - **没有任何迁移指向 `DRAFT`**（py 线不存在"撤回草稿"路径）⇒ `transition`
 *     对目标 `DRAFT` 直接抛（CAS 永不命中 ⇒ 调用即编程错误，fail loud）。
 *
 * 本层**不做**的判定（刻意）
 * ------------------------
 * * 不承接 `PublishRequest.tools` 的工具绑定（§13.8.7 挂账 #7：归 T3-05）；
 * * `agent_version` **不查重版本号**：DDL 对 `(agent_id, version)` **无唯一约束**
 *   （与 `uq_skill_version_skill_version` 不同，实测），py 线 `add()` 也不查 ⇒
 *   本层不擅自加严（契约外语义扩展禁令，同 §13.8.4 理由 ①）；
 * * 版本行**不可变**（py `version_repository` 头注「不可变快照」）⇒ 不提供任何
 *   版本 update / delete 入口。
 */

import {
  and,
  asc,
  desc,
  eq,
  getTableColumns,
  or,
  type AnyColumn,
  type InferSelectModel,
  type SQL,
  type Table,
} from "drizzle-orm";

import {
  agent as pgAgent,
  agent_version as pgAgentVersion,
} from "../schema/pg/agent.js";
import {
  agent as sqliteAgent,
  agent_version as sqliteAgentVersion,
} from "../schema/sqlite/agent.js";
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

/** `agent` 行。 */
export type AgentRow = InferSelectModel<typeof pgAgent>;

/** `agent_version` 行。 */
export type AgentVersionRow = InferSelectModel<typeof pgAgentVersion>;

// ---------------------------------------------------------------------------
// 值域（证据见文件头注；改值必须同步改测试的手写期望表）
// ---------------------------------------------------------------------------

/** agent 生命周期：草稿（创建即此态；契约 `AgentResponse.status` default）。 */
export const AGENT_STATUS_DRAFT = "DRAFT";
/** agent 生命周期：启用（发布路径实证：py `publish_version` 置 ACTIVE）。 */
export const AGENT_STATUS_ACTIVE = "ACTIVE";
/** agent 生命周期：归档（弃置/下线；无迁移出自它指向 DRAFT 的路径）。 */
export const AGENT_STATUS_ARCHIVED = "ARCHIVED";

/** agent 生命周期全集（顺序 = py 常量声明顺序，逐项同序）。 */
export const AGENT_STATUSES = [
  AGENT_STATUS_DRAFT,
  AGENT_STATUS_ACTIVE,
  AGENT_STATUS_ARCHIVED,
] as const;

/** 版本状态：草稿（py 词表成员；本层**没有**产生 DRAFT 版本的入口 —— 契约唯一
 * 创建路径 `POST /agents/{id}/publish` 恒产 PUBLISHED，见 `publishVersion`）。 */
export const AGENT_VERSION_STATUS_DRAFT = "DRAFT";
/** 版本状态：已发布（契约 `AgentVersionResponse.status` default；发布即冻结）。 */
export const AGENT_VERSION_STATUS_PUBLISHED = "PUBLISHED";
/** 版本状态：已废弃（py 词表第三值；本层无迁移入口 —— 没有对应端点）。 */
export const AGENT_VERSION_STATUS_DEPRECATED = "DEPRECATED";

/** 版本状态全集（成员既不是子集也不是超集关系，两端都要逐项校验）。 */
export const AGENT_VERSION_STATUSES = [
  AGENT_VERSION_STATUS_DRAFT,
  AGENT_VERSION_STATUS_PUBLISHED,
  AGENT_VERSION_STATUS_DEPRECATED,
] as const;

/** agent 类型：主 Agent（契约 `CreateAgentRequest.type` / `AgentResponse.type` default）。 */
export const AGENT_TYPE_PRIMARY = "PRIMARY";
/** agent 类型全集（顺序 = py 常量声明顺序）。 */
export const AGENT_TYPES = [
  AGENT_TYPE_PRIMARY,
  "SUB_AGENT",
  "WORKFLOW_AGENT",
  "SCHEDULED_AGENT",
  "EVENT_AGENT",
] as const;

/**
 * agent 状态迁移矩阵（**方向 = from → 允许的 to**；证据见文件头注）。
 *
 * 键集合必须恰好等于 {@link AGENT_STATUSES}（少一个状态 = 矩阵对它沉默，
 * 测试的手写期望表会红）；值集合 ⊆ {@link AGENT_STATUSES}。
 */
export const AGENT_STATUS_TRANSITIONS: Readonly<
  Record<(typeof AGENT_STATUSES)[number], readonly string[]>
> = {
  [AGENT_STATUS_DRAFT]: [AGENT_STATUS_ACTIVE, AGENT_STATUS_ARCHIVED],
  [AGENT_STATUS_ACTIVE]: [AGENT_STATUS_ARCHIVED],
  [AGENT_STATUS_ARCHIVED]: [AGENT_STATUS_ACTIVE],
};

/** 是否 agent 生命周期值。 */
export function isAgentStatus(status: string): boolean {
  return (AGENT_STATUSES as readonly string[]).includes(status);
}

/** 是否 agent 版本状态值。 */
export function isAgentVersionStatus(status: string): boolean {
  return (AGENT_VERSION_STATUSES as readonly string[]).includes(status);
}

/** 是否 agent 类型值。 */
export function isAgentType(type: string): boolean {
  return (AGENT_TYPES as readonly string[]).includes(type);
}

/** `from → to` 是否合法迁移（矩阵查表；from 不在矩阵里 ⇒ false）。 */
export function canTransitionStatus(from: string, to: string): boolean {
  return (AGENT_STATUS_TRANSITIONS[from as keyof typeof AGENT_STATUS_TRANSITIONS] ?? []).includes(to);
}

/** `GET /agents` 的分页口径（契约：`page` 默认 1；`page_size` 默认 20、上限 100）。 */
export const AGENT_LIST_DEFAULT_PAGE = 1;
export const AGENT_LIST_DEFAULT_PAGE_SIZE = 20;
export const AGENT_LIST_MAX_PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// 入参类型（`tenant_id` / `current_version_id` / 时间戳**故意不在**）
// ---------------------------------------------------------------------------

/** 创建 agent 的入参（对应契约 `CreateAgentRequest`；`status` 恒注入 DRAFT）。 */
export interface CreateAgentInput {
  /** 主键。双档 DDL 的 `id` 无默认值 ⇒ 必须显式给（uuid）。 */
  readonly id: string;
  readonly name: string;
  /** 缺省 {@link AGENT_TYPE_PRIMARY}（契约 default）。 */
  readonly type?: string;
  readonly description?: string | null;
  readonly organizationId?: string | null;
  /** 创建者用户 id（列 NOT NULL ⇒ 必填；`fk_agent_0` 指向 user）。 */
  readonly createdBy: string;
}

/** agent 元数据可改字段（= 契约 `UpdateAgentRequest` 去掉 `status`）。 */
export interface UpdateAgentMetadataPatch {
  readonly name?: string;
  readonly description?: string | null;
}

/** 发布版本的入参（对应契约 `PublishRequest`；`status` 恒注入 PUBLISHED）。 */
export interface PublishAgentVersionInput {
  /** 新版本行主键。双档 DDL 的 `id` 无默认值 ⇒ 必须显式给（uuid）。 */
  readonly id: string;
  /** 版本号；缺省按既有版本数自增为 `v{n+1}`（py `publish_version` 同口径）。 */
  readonly version?: string;
  /** 契约 `PublishRequest.system_prompt` default `""`。 */
  readonly systemPrompt?: string;
  /** 契约 `PublishRequest` 无 required 字段 ⇒ 缺省 `{}`（列 NOT NULL，不是 null）。 */
  readonly modelConfig?: Record<string, unknown>;
  /** 同上；缺省 `{}`。 */
  readonly runtimeConfig?: Record<string, unknown>;
  /** 发布者用户 id（列 NOT NULL ⇒ 必填）。 */
  readonly createdBy: string;
}

/** agent 列表选项（契约分页：`page` ≥ 1、`page_size` ∈ 1..100；非法值抛，不夹取）。 */
export interface AgentListOptions {
  readonly page?: number;
  readonly pageSize?: number;
}

/** 版本列表选项（版本表用 `created_at` 排序）。 */
export type AgentVersionListOptions = ListOptions;

/** 分页查询链（`findManyWhere` 没有 offset ⇒ 本类自己接一段，同 `ApprovalRepo.#page`）。 */
interface OffsetChain {
  offset(count: number): PromiseLike<Record<string, unknown>[]>;
}

export class AgentRepo extends ScopedRepo<AgentRow> {
  readonly #dialect: SqlDialect;
  readonly #table: Table;
  readonly #versionTable: Table;
  /** `agent_version` 的列（两表有同名列，传错会静默错配 ⇒ 只在此取一次）。 */
  readonly #versionColumns: Record<string, AnyColumn>;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    const table = resolveTable(dialect, pgAgent, sqliteAgent);
    super(db, table, scope);
    this.#dialect = dialect;
    this.#table = table;
    this.#versionTable = resolveTable(dialect, pgAgentVersion, sqliteAgentVersion);
    this.#versionColumns = getTableColumns(this.#versionTable) as Record<string, AnyColumn>;
  }

  /**
   * 本租户的 agent 列表（`GET /agents`：`page` / `page_size` 分页）。
   *
   * 排序跟 py 线 `list_by_tenant`（`created_at` 升序）；`created_at` 是
   * `CURRENT_TIMESTAMP`（**秒粒度**）⇒ 补 `id` 作次键（同 B1 P-4 结论，
   * py 无次键是既有不一致，登记不追随）。
   *
   * @throws {ScopeError} `page` / `pageSize` 非法（不静默夹取 —— 静默修正会少给行）。
   */
  list(options: AgentListOptions = {}): Promise<AgentRow[]> {
    const page = resolveAgentPage(options.page);
    const pageSize = resolveAgentPageSize(options.pageSize);
    return this.#page(undefined, (page - 1) * pageSize, pageSize);
  }

  /** 按类型取 agent 列表（同 `list` 的排序与分页口径）。 */
  listByType(type: string, options: AgentListOptions = {}): Promise<AgentRow[]> {
    const page = resolveAgentPage(options.page);
    const pageSize = resolveAgentPageSize(options.pageSize);
    return this.#page(eq(this.columns.type, type), (page - 1) * pageSize, pageSize);
  }

  /**
   * 创建 agent：`status` 恒注入 {@link AGENT_STATUS_DRAFT}、`current_version_id`
   * **恒为 `null`**（环状外键第一步，见文件头注）。
   *
   * 为什么这两个字段不给参数：契约 `POST /agents` 的描述原文「创建 Agent
   * （``DRAFT``，无当前版本）」—— 把它们做成参数只会让调用方写出契约外状态。
   */
  create(input: CreateAgentInput): Promise<AgentRow> {
    const type = input.type ?? AGENT_TYPE_PRIMARY;
    if (!isAgentType(type)) {
      throw new ScopeError(
        `agent.create：type 必须是 ${AGENT_TYPES.join(" | ")}，实测 ${JSON.stringify(type)}`,
      );
    }
    const now = instantLiteral(this.#dialect, new Date());
    const row: Record<string, unknown> = {
      id: input.id,
      organization_id: input.organizationId ?? null,
      name: input.name,
      description: input.description ?? null,
      type,
      status: AGENT_STATUS_DRAFT,
      current_version_id: null,
      created_by: input.createdBy,
      updated_at: now,
    };
    return this.insertRow(row as unknown as TenantScopedInsert<AgentRow>);
  }

  /**
   * 改元数据（= 契约 `PUT /agents/{id}` 的 `name` / `description`）。
   *
   * **`status` 刻意不收**：状态变更只能走 {@link AgentRepo.transition}（合法迁移
   * 矩阵 + CAS），否则 `updateMetadata` 就是绕过状态机的后门。
   * `name` 允许改（与 `skill` 不同：契约 `UpdateAgentRequest` 明确含 `name`，
   * 且 `agent` 无 `uq(tenant_id, name)` 约束，改名不换身份）。
   * `updated_at` 显式推进（SQLite 无 `ON UPDATE` 触发器，不写就"刚改过的仍沉底"）。
   */
  async updateMetadata(
    agentRef: ScopedRef,
    patch: UpdateAgentMetadataPatch,
  ): Promise<AgentRow | null> {
    this.assertOwnRef(agentRef, "agentRef");
    const allowed = new Set(["name", "description"]);
    for (const key of Object.keys(patch)) {
      if (!allowed.has(key)) {
        throw new ScopeError(
          `agent.updateMetadata：不支持的字段 ${key} —— 本层只收 ` +
            `${[...allowed].join(" / ")}（status 变更必须走 transition()，见状态机）`,
        );
      }
    }
    const values: Record<string, unknown> = {
      ...patch,
      updated_at: instantLiteral(this.#dialect, new Date()),
    };
    return this.update(agentRef, values as never);
  }

  /**
   * 状态迁移（状态机**唯一**入口）：合法迁移矩阵 + **原子 CAS**。
   *
   * 原子性：不"先查后写"（TOCTOU），而是把矩阵反查出 `to` 的全部合法来源，
   * 一条 `UPDATE ... WHERE status IN (来源集合)` 打出去 —— 命中即合法迁移，
   * 未命中（0 行）⇒ `null`。并发下两个迁移者最多一个命中。
   *
   * @returns 迁移后的行；行不存在、或当前状态不在 `to` 的合法来源集合 ⇒ `null`
   *          （调用方若需区分 404 / 409，先用 `findById` 判存在性 —— 同
   *          `ApprovalRepo.decide` 的口径，本层不猜错误码）。
   * @throws {ScopeError} 目标状态不在词表内；或目标状态无任何合法来源（现只可能是
   *          `DRAFT` —— 矩阵没有指向它的边，CAS 永不命中 ⇒ 调用即编程错误）。
   */
  transition(
    agentRef: ScopedRef,
    to: string,
    options: { at?: Date | string } = {},
  ): Promise<AgentRow | null> {
    if (!isAgentStatus(to)) {
      throw new ScopeError(
        `agent.transition：目标状态必须是 ${AGENT_STATUSES.join(" | ")}，实测 ${JSON.stringify(to)}`,
      );
    }
    const froms = sourcesOf(to);
    if (froms.length === 0) {
      throw new ScopeError(
        `agent.transition：目标状态 ${to} 没有任何合法来源（AGENT_STATUS_TRANSITIONS 无指向它的边）—— ` +
          "调用即编程错误，不发起注定未命中的 CAS",
      );
    }
    this.assertOwnRef(agentRef, "agentRef");
    const at = instantLiteral(this.#dialect, options.at ?? new Date());
    return this.#casTransition(agentRef, to, froms, at);
  }

  /**
   * 发布版本（`POST /agents/{id}/publish`）：**一次发布 = 一个新版本**（不可变快照），
   * 并把 `agent.current_version_id` 指向它、`agent.status` 推到 `ACTIVE`。
   *
   * 顺序即环状外键的第二、三步：版本行先落库（第 2 步），指针才能指过去（第 3 步）。
   * 状态推进复用 {@link AgentRepo.transition} 的 CAS（`DRAFT|ARCHIVED → ACTIVE`）；
   * agent 已是 `ACTIVE` 时 CAS 未命中属正常（py 的无条件赋值在此为同值幂等），
   * 不影响发布结果。
   *
   * @returns 新发布的版本行（`status` 恒 {@link AGENT_VERSION_STATUS_PUBLISHED}）。
   * @throws {ScopeError} 父 agent 不可见 / 版本号或配置非法。
   */
  async publishVersion(
    agentRef: ScopedRef,
    input: PublishAgentVersionInput,
  ): Promise<AgentVersionRow> {
    const parent = await this.#assertVisibleAgent(agentRef);

    // 版本号缺省：py `f"v{len(list_by_agent(agent_id)) + 1}"` 同口径。
    const label = input.version ?? `v${(await this.#countVersions(agentRef.id)) + 1}`;

    // 第 2 步：版本行落库（PUBLISHED 即冻结；agent_version 无 tenant_id 列 ⇒
    // 不能走 insertRow —— 那会注入本表不存在的租户列，同 skill-repo 的处理）。
    const values: Record<string, unknown> = {
      id: input.id,
      agent_id: agentRef.id,
      version: label,
      system_prompt: input.systemPrompt ?? "",
      model_config: input.modelConfig ?? {},
      runtime_config: input.runtimeConfig ?? {},
      status: AGENT_VERSION_STATUS_PUBLISHED,
      created_by: input.createdBy,
    };
    const inserted = await (this.db
      .insert(this.#versionTable)
      .values(values)
      .returning() as unknown as PromiseLike<AgentVersionRow[]>);
    const created = inserted[0];
    if (created === undefined) {
      throw new ScopeError(`向 agent_version 插入后没有返回行（agent ${agentRef.id}）`);
    }

    // 第 3 步：指针回写（无条件 —— py 发布对任何当前状态都换指针）。
    await this.update(agentRef, {
      current_version_id: created.id,
      updated_at: instantLiteral(this.#dialect, new Date()),
    } as never);

    // 状态推进（DRAFT|ARCHIVED → ACTIVE；已 ACTIVE ⇒ CAS 未命中，幂等跳过）。
    if (parent.status !== AGENT_STATUS_ACTIVE) {
      await this.transition(agentRef, AGENT_STATUS_ACTIVE);
    }
    return created;
  }

  /** 某 agent 的全部版本（不可变快照；`created_at` 升序 + `id` 兜底 —— py 同升序）。 */
  async listVersions(agentRef: ScopedRef, options: ListOptions = {}): Promise<AgentVersionRow[]> {
    await this.#assertVisibleAgent(agentRef);
    const limit = resolveListLimit(this.tableName, options.limit);
    const orderColumn = this.#versionColumns[options.orderBy ?? "created_at"];
    const primary: SQL[] =
      orderColumn === undefined ? [] : [options.descending === false ? asc(orderColumn) : desc(orderColumn)];
    const chain = this.db
      .select()
      .from(this.#versionTable)
      .where(eq(this.#versionColumns.agent_id, agentRef.id))
      .orderBy(...primary, asc(this.#versionColumns.id))
      .limit(limit);
    return (await chain).slice() as AgentVersionRow[];
  }

  /**
   * 按版本 id 取（父必须可见；版本不存在或**归属不符** ⇒ `null` —— py
   * `load_version` 的"版本不存在 / 归属不符"同形，服务层翻 404，本层不猜错误码）。
   */
  async findVersion(agentRef: ScopedRef, versionId: string): Promise<AgentVersionRow | null> {
    await this.#assertVisibleAgent(agentRef);
    const rows = await (this.db
      .select()
      .from(this.#versionTable)
      .where(
        and(
          eq(this.#versionColumns.agent_id, agentRef.id),
          eq(this.#versionColumns.id, versionId),
        ),
      )
      .limit(1));
    return (rows[0] as AgentVersionRow | undefined) ?? null;
  }

  // -------------------------------------------------------------------------
  // 私有
  // -------------------------------------------------------------------------

  /** CAS 迁移：`WHERE id = ? AND status IN (合法来源)`；命中 0 行 ⇒ `null`。 */
  async #casTransition(
    agentRef: ScopedRef,
    to: string,
    froms: readonly string[],
    at: Date | string,
  ): Promise<AgentRow | null> {
    const fromList = froms.map((from) => eq(this.columns.status, from));
    const rows = await (this.db
      .update(this.#table)
      .set({ status: to, updated_at: at })
      .where(
        this.scopedWhere(
          and(eq(this.columns.id, agentRef.id), fromList.length === 1 ? fromList[0] : or(...fromList)),
        ),
      )
      .returning() as unknown as PromiseLike<AgentRow[]>);
    return rows[0] ?? null;
  }

  /**
   * 父 agent 必须在本 scope 可见；返回该行（顺带把 `scope` 谓词打在最前面）。
   *
   * ⚠️ 行归属**只能**由这次带租户谓词的 `findById` 证明 —— `owns()` 只是铸造
   * 来源校验（mint provenance），`scopeA.ref(别家 agent id)` 一样通过 `owns()`。
   *
   * @throws {ScopeError} ref 非法 / 不可见（跨租户或不存在一律抛错，不返回空结果）。
   */
  async #assertVisibleAgent(agentRef: ScopedRef): Promise<AgentRow> {
    this.assertOwnRef(agentRef, "agentRef");
    const row = await this.findById(agentRef);
    if (row === null) {
      throw new ScopeError(
        `agent：父 agent ${agentRef.id} 在本 scope 下不可见（租户 ${this.scope.tenantId}）—— ` +
          "跨租户或不存在一律抛错，不返回空结果",
      );
    }
    return row;
  }

  /** 版本行计数（版本号缺省 `v{n+1}` 用；原生 count，不拉全行）。 */
  async #countVersions(agentId: string): Promise<number> {
    const rows = (await (this.db
      .select()
      .from(this.#versionTable)
      .where(eq(this.#versionColumns.agent_id, agentId)) as unknown as PromiseLike<
      Record<string, unknown>[]
    >)) as unknown as Record<string, unknown>[];
    return rows.length;
  }

  /**
   * 分页查询（`created_at` 升序 + `id` 兜底 + offset）。
   *
   * 为什么不用基类 `findManyWhere`：它没有 `offset`（V0.1.0 闭版基类不许动），
   * 而契约 `GET /agents` 是 `page` / `page_size` 语义 ⇒ 在本仓内实现
   * （同 `ApprovalRepo.#page` 的先例，接受局部重复）。
   */
  async #page(condition: SQL | undefined, offset: number, limit: number): Promise<AgentRow[]> {
    const chain = this.db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(condition))
      .orderBy(asc(this.columns.created_at), asc(this.columns.id))
      .limit(limit);
    const rows = await (chain as unknown as OffsetChain).offset(offset);
    return rows.slice() as AgentRow[];
  }
}

/** 反查：哪些状态可以迁移到 `to`（矩阵的方向是 from → to，CAS 需要 to 的来源集合）。 */
function sourcesOf(to: string): string[] {
  const froms: string[] = [];
  for (const [from, tos] of Object.entries(AGENT_STATUS_TRANSITIONS)) {
    if (tos.includes(to)) froms.push(from);
  }
  return froms;
}

/** `page` 解析（契约 ≥ 1 的整数，缺省 1；非法值抛，不夹取）。 */
function resolveAgentPage(page: number | undefined): number {
  if (page === undefined) return AGENT_LIST_DEFAULT_PAGE;
  if (!Number.isInteger(page) || page < 1) {
    throw new ScopeError(
      `agent.list：page 非法（实测 ${String(page)}），契约口径为 ≥ 1 的整数（缺省 ${AGENT_LIST_DEFAULT_PAGE}）`,
    );
  }
  return page;
}

/** `pageSize` 解析（契约 1..100，缺省 20；非法值抛，不夹取）。 */
function resolveAgentPageSize(pageSize: number | undefined): number {
  if (pageSize === undefined) return AGENT_LIST_DEFAULT_PAGE_SIZE;
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > AGENT_LIST_MAX_PAGE_SIZE) {
    throw new ScopeError(
      `agent.list：page_size 非法（实测 ${String(pageSize)}），` +
        `契约口径为 1..${AGENT_LIST_MAX_PAGE_SIZE} 的整数（缺省 ${AGENT_LIST_DEFAULT_PAGE_SIZE}）`,
    );
  }
  return pageSize;
}
