/**
 * B2 · `approval` 仓储（审批记录 · **独立租户域**）。
 *
 * 为什么是 `ScopedRepo`（而不是子表基类）
 * ------------------------------------
 * `approval` 有 `tenant_id NOT NULL`（DDL 实测）⇒ 租户直挂；DDL 里**没有** run / agent
 * 外键：`subject_type` + `subject_ref` 是 VARCHAR 多态（`tool` / `mcp` / `workflow_node`），
 * 契约路径也是平铺的 `/api/v1/approvals`。所以它不归属任何"父"，直接进 `ScopedRepo`。
 *
 * 四个状态值域**不是猜的**（证据）
 * ------------------------------
 * | 值 | 证据 |
 * |---|---|
 * | `PENDING` | 契约 `ApprovalResponse.status` 的 `default: "PENDING"` |
 * | `APPROVED` / `REJECTED` | 契约 `/approvals/{id}/approve` 描述：「决议**通过**（`PENDING → APPROVED`）」；reject 同形 |
 * | `EXPIRED` | 前端 DTO `apps/web/src/types/approval.ts::ApprovalStatus` 逐字声明 `PENDING / APPROVED / REJECTED / EXPIRED`，并注明与 py 线 `ApprovalStatus` 同口径 |
 *
 * 「终态三者不可再转移」也是同一份 DTO 的原文 ⇒ 本层用 **CAS**（`status='PENDING'`）
 * 把"只能从 PENDING 决议一次"做成结构性约束，而不是靠调用方记得先查。
 *
 * 本层**不做**的判定（刻意）
 * ------------------------
 * * 不判"决议人是否有权限"——那是服务层 / `resource_permission` 的事；
 * * 不判 `expires_at` 是否已过，也不提供 `expire()`：没有对应端点 ⇒ **没有入口比凭空
 *   造一个入口更强**（同裁定 ③ 的风格）。`EXPIRED` 仅作为 `decide()` 的合法目标值存在。
 */

import { and, asc, desc, eq, type InferSelectModel, type SQL, type Table } from "drizzle-orm";

import { approval as pgApproval } from "../schema/pg/conversation.js";
import { approval as sqliteApproval } from "../schema/sqlite/conversation.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  ScopeError,
  type DrizzleDatabase,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `approval` 行。 */
export type ApprovalRow = InferSelectModel<typeof pgApproval>;

// ---------------------------------------------------------------------------
// 值域（每个常量都写明证据，见文件头注；改值必须同步改测试的手写期望表）
// ---------------------------------------------------------------------------

/** 待决议（契约 `ApprovalResponse.status` 的 default）。 */
export const APPROVAL_STATUS_PENDING = "PENDING";

/** 决议通过（契约 `/approvals/{id}/approve`：`PENDING → APPROVED`）。 */
export const APPROVAL_STATUS_APPROVED = "APPROVED";

/** 决议驳回（`/approvals/{id}/reject`，与 approve 同形）。 */
export const APPROVAL_STATUS_REJECTED = "REJECTED";

/** 已过期（前端 DTO 与 py 线 `ApprovalStatus` 的第四值；本层无迁移入口，见文件头注）。 */
export const APPROVAL_STATUS_EXPIRED = "EXPIRED";

/** 审批状态全集（顺序 = 前端 DTO 的声明顺序，逐项同序）。 */
export const APPROVAL_STATUSES = [
  APPROVAL_STATUS_PENDING,
  APPROVAL_STATUS_APPROVED,
  APPROVAL_STATUS_REJECTED,
  APPROVAL_STATUS_EXPIRED,
] as const;

/** 终态（三者不可再转移 —— 前端 DTO 原文「终态三者不可再转移」）。 */
export const APPROVAL_TERMINAL_STATUSES = [
  APPROVAL_STATUS_APPROVED,
  APPROVAL_STATUS_REJECTED,
  APPROVAL_STATUS_EXPIRED,
] as const;

/** 是否审批终态。 */
export function isTerminalApprovalStatus(status: string): boolean {
  return (APPROVAL_TERMINAL_STATUSES as readonly string[]).includes(status);
}

/**
 * 主体类型（契约 `ApprovalResponse.subject_type` 的用例：`tool` / `mcp` / `workflow_node`）。
 *
 * 列是 `VARCHAR(20)` 无枚举（零 DDL ⇒ 不能加 CHECK）⇒ 这里只是一份**已知取值**清单，
 * 供服务层选择校验策略；本层**不**拒绝清单外的值（多态主体的扩展权留给服务层）。
 */
export const APPROVAL_SUBJECT_TYPES = ["tool", "mcp", "workflow_node"] as const;

/** `GET /approvals` 的分页口径（契约：`limit` ∈ [1,200] 默认 50，`offset` ≥ 0 默认 0）。 */
export const APPROVAL_LIST_DEFAULT_LIMIT = 50;
export const APPROVAL_LIST_MAX_LIMIT = 200;

/** 创建审批的入参（`status` / `decided_*` / `tenant_id` / 时间戳**故意不在**）。 */
export interface CreateApprovalInput {
  /** 主键。双档 DDL 的 `id` 无默认值 ⇒ 必须显式给（uuid）。 */
  readonly id: string;
  /** 主体类型（缺省 `""`，与契约 default 对齐）。 */
  readonly subjectType?: string;
  /** 主体标识；缺省 `""`（契约 default）。 */
  readonly subjectRef?: string;
  /** 发起人用户 id；可空（系统发起）。 */
  readonly requestedBy?: string | null;
  /** 审批载荷（列 NOT NULL ⇒ 缺省 `{}`，**不是** `null`）。 */
  readonly payload?: Record<string, unknown>;
  /** 过期时刻；缺省 `null` = 不过期。 */
  readonly expiresAt?: Date | string | null;
}

/** 决议入参：目标状态由调用方给（理由见 `decide`）。 */
export interface DecideApprovalInput {
  /** 决议后的状态（`APPROVED` / `REJECTED`；`EXPIRED` 也接受，留给过期任务复用）。 */
  readonly status: string;
  /** 决议人用户 id（契约：决议人取当前登录用户）。 */
  readonly decidedBy: string;
  /** 决议时刻；缺省"现在"（SQLite 档规整成文本，见 `instantLiteral`）。 */
  readonly decidedAt?: Date | string;
}

/** 分页查询链（`findManyWhere` 没有 offset ⇒ 本类自己接一段，见 `#page`）。 */
interface OffsetChain {
  offset(count: number): PromiseLike<Record<string, unknown>[]>;
}

export class ApprovalRepo extends ScopedRepo<ApprovalRow> {
  readonly #dialect: SqlDialect;
  readonly #table: Table;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    const table = resolveTable(dialect, pgApproval, sqliteApproval);
    super(db, table, scope);
    this.#dialect = dialect;
    // 基类不暴露表对象；本类的 CAS 与分页要自己拼式，故构造时留一份。
    this.#table = table;
  }

  /**
   * 待办审批列表（`GET /approvals`）。
   *
   * 契约口径：「`GET /approvals` **只返回 `PENDING`**；决议 / 过期记录仅经详情端点可取」
   * ⇒ 本方法**没有**"列出全部"的开关：不给状态参数，就不会出现"忘了过滤"的调用方。
   *
   * 分页走 `limit` / `offset`（与 `/agents` 的 `page` / `page_size` 是两套风格，
   * 施工记录已登记为既有不一致；本版按各端点自己的契约实现，不做统一）。
   *
   * @throws {ScopeError} `limit` / `offset` 非法（不静默夹取 —— 静默修正会少给行）。
   */
  listPending(options: { limit?: number; offset?: number } = {}): Promise<ApprovalRow[]> {
    const limit = resolveApprovalLimit(options.limit);
    const offset = resolveApprovalOffset(options.offset);
    return this.#page(eq(this.columns.status, APPROVAL_STATUS_PENDING), limit, offset);
  }

  /** 按主体取审批（同一主体可能有多条历史，时间倒序；`subjectType` 必须一并给）。 */
  listBySubject(
    subjectType: string,
    subjectRef: string,
    options: { limit?: number; offset?: number } = {},
  ): Promise<ApprovalRow[]> {
    const limit = resolveApprovalLimit(options.limit);
    const offset = resolveApprovalOffset(options.offset);
    return this.#page(
      and(eq(this.columns.subject_type, subjectType), eq(this.columns.subject_ref, subjectRef)),
      limit,
      offset,
    );
  }

  /**
   * 创建审批：注入 `status = PENDING`（契约 default）。
   *
   * `decided_by` / `decided_at` 一律显式落 `null`：让"PENDING 却有决议人"这种行
   * 从插入那一刻就不可能存在，而不是靠调用方记得别传。
   */
  create(input: CreateApprovalInput): Promise<ApprovalRow> {
    const now = instantLiteral(this.#dialect, new Date());
    const expiresAt =
      input.expiresAt === undefined || input.expiresAt === null
        ? null
        : instantLiteral(this.#dialect, input.expiresAt);
    const row: Record<string, unknown> = {
      id: input.id,
      subject_type: input.subjectType ?? "",
      subject_ref: input.subjectRef ?? "",
      requested_by: input.requestedBy ?? null,
      status: APPROVAL_STATUS_PENDING,
      decided_by: null,
      decided_at: null,
      payload: input.payload ?? {},
      expires_at: expiresAt,
      updated_at: now,
    };
    return this.insertRow(row as unknown as TenantScopedInsert<ApprovalRow>);
  }

  /**
   * 决议（`PENDING → 终态`）**唯一**入口：CAS 保证不可重复决议。
   *
   * 为什么目标状态由调用方给而不是本层写死：本层只承担"只能从 PENDING 迁出**一次**"
   * 这条不变量；是 APPROVED 还是 REJECTED 由端点语义决定（`approve()` / `reject()`
   * 两个便捷方法已封好），这样过期任务（`EXPIRED`）能复用同一入口而不用改仓储。
   *
   * @returns 决议后的行；行不存在、或已被决议（CAS 未命中）⇒ `null`。
   *          调用方若需区分 404 / 409，先用 `findById` 判存在性（本层不猜错误码）。
   * @throws {ScopeError} 目标状态不是终态值，或 `decidedBy` 为空。
   */
  decide(ref: ScopedRef, input: DecideApprovalInput): Promise<ApprovalRow | null> {
    if (!isTerminalApprovalStatus(input.status)) {
      throw new ScopeError(
        `approval.decide：决议后状态必须是终态（${APPROVAL_TERMINAL_STATUSES.join(" | ")}），` +
          `实测 ${JSON.stringify(input.status)} —— PENDING 只能是迁移起点，不能是终点`,
      );
    }
    if (typeof input.decidedBy !== "string" || input.decidedBy.trim() === "") {
      throw new ScopeError(
        "approval.decide：decidedBy 必须是非空用户 id（契约：决议人取当前登录用户）",
      );
    }
    this.assertOwnRef(ref, "approvalRef");
    return this.#decide(ref, input);
  }

  /** 决议通过（`PENDING → APPROVED`）。 */
  approve(
    ref: ScopedRef,
    decidedBy: string,
    decidedAt?: Date | string,
  ): Promise<ApprovalRow | null> {
    return this.decide(ref, { status: APPROVAL_STATUS_APPROVED, decidedBy, decidedAt });
  }

  /** 决议驳回（`PENDING → REJECTED`）。 */
  reject(
    ref: ScopedRef,
    decidedBy: string,
    decidedAt?: Date | string,
  ): Promise<ApprovalRow | null> {
    return this.decide(ref, { status: APPROVAL_STATUS_REJECTED, decidedBy, decidedAt });
  }

  // -------------------------------------------------------------------------
  // 私有
  // -------------------------------------------------------------------------

  /** CAS 决议：`WHERE id = ? AND status = 'PENDING'`；命中 0 行 ⇒ `null`。 */
  async #decide(ref: ScopedRef, input: DecideApprovalInput): Promise<ApprovalRow | null> {
    const decidedAt = instantLiteral(this.#dialect, input.decidedAt ?? new Date());
    const patch: Record<string, unknown> = {
      status: input.status,
      decided_by: input.decidedBy,
      decided_at: decidedAt,
      updated_at: decidedAt,
    };
    const rows = await (this.db
      .update(this.#table)
      .set(patch)
      .where(
        this.scopedWhere(
          and(eq(this.columns.id, ref.id), eq(this.columns.status, APPROVAL_STATUS_PENDING)),
        ),
      )
      .returning() as unknown as PromiseLike<ApprovalRow[]>);
    return rows[0] ?? null;
  }

  /**
   * 分页查询（时间列倒序 + `id` 兜底 + offset）。
   *
   * 为什么不用基类 `findManyWhere`：它没有 `offset`（V0.1.0 闭版基类不许动，裁定 ①）
   * ⇒ 在本仓内实现，接受与其它仓的局部重复。
   *
   * `id` 作第二排序键：`created_at` 是 `CURRENT_TIMESTAMP`（**秒粒度**），同秒创建的
   * 两行时间戳相同，只按时排序时翻页会重复/漏行（同 B1 的 P-4 结论）。
   */
  async #page(condition: SQL | undefined, limit: number, offset: number): Promise<ApprovalRow[]> {
    const chain = this.db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(condition))
      .orderBy(desc(this.columns.created_at), asc(this.columns.id))
      .limit(limit);
    const rows = await (chain as unknown as OffsetChain).offset(offset);
    return rows.slice() as ApprovalRow[];
  }
}

/** `limit` 解析（契约 1..200，缺省 50；非法值抛，不夹取）。 */
function resolveApprovalLimit(limit: number | undefined): number {
  if (limit === undefined) return APPROVAL_LIST_DEFAULT_LIMIT;
  if (!Number.isInteger(limit) || limit < 1 || limit > APPROVAL_LIST_MAX_LIMIT) {
    throw new ScopeError(
      `approval.list：limit 非法（实测 ${String(limit)}），契约口径为 1..${APPROVAL_LIST_MAX_LIMIT} 的整数（缺省 ${APPROVAL_LIST_DEFAULT_LIMIT}）`,
    );
  }
  return limit;
}

/** `offset` 解析（契约 ≥ 0，缺省 0；非法值抛）。 */
function resolveApprovalOffset(offset: number | undefined): number {
  if (offset === undefined) return 0;
  if (!Number.isInteger(offset) || offset < 0) {
    throw new ScopeError(
      `approval.list：offset 非法（实测 ${String(offset)}），契约口径为 ≥ 0 的整数`,
    );
  }
  return offset;
}
