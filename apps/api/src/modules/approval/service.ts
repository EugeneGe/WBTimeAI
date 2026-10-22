/**
 * T3-12 · Approval 服务（**4 op** 的全部主体：列表 / 详情 / 通过 / 驳回）。
 *
 * 4 op 与错误语义（**py oracle：`wbtime_ai_api/routers/v1/approvals.py` 逐条对齐**）
 * ------------------------------------------------------------------------------
 * | # | op | 成功码 | 错误 |
 * |---|---|---|---|
 * | 1 | `GET /approvals` | 200 数组 | `limit`/`offset` 越界 ⇒ 422（schema） |
 * | 2 | `GET /approvals/{id}` | 200 | 不存在 / 跨租户 ⇒ **404** `NOT_FOUND`（I-1，不是 403） |
 * | 3 | `POST /approvals/{id}/approve` | 200 | 404；已决议 ⇒ **409 `CONFLICT`** |
 * | 4 | `POST /approvals/{id}/reject` | 200 | 404；已决议 ⇒ **409 `CONFLICT`** |
 *
 * 三条硬口径（都有 py 原文依据）
 * -----------------------------
 *   ① **列表只返 `PENDING`**：契约口径「决议 / 过期记录仅经详情端点可取」。
 *      仓储的 `listPending` 干脆没有"列出全部"的开关 —— 不给状态参数，
 *      就不会出现"某个调用方忘了过滤"。
 *   ② **二次决议 ⇒ 409 而不是幂等返回**：py `_decide` 先 `is_pending` 判定，
 *      非 `PENDING` 抛 `ErrorCode.CONFLICT, status_code=409, data={approval_id, status}`。
 *      **不得**自造错误码，也**不得**把二次决议做成"返回原行"（那会让调用方
 *      无法区分"我刚批的"与"别人早批的"）。
 *   ③ **决议只改状态与时间戳，不触发执行**（卡面验收 ④）：本服务**不** import
 *      `ToolExecutor` / 沙箱 / `AgentLoop` 的任何东西，`decide` 只落
 *      `status / decided_by / decided_at / updated_at` 四列。执行属 T3-08 的
 *      恢复路径（`approval.decided` 事件 → run 续跑），那条链**不在本层**。
 *      反例「approve 直接调执行器 ⇒ 必红」由 `routes-approvals.test.mjs` 的
 *      静态断言（本文件不得出现执行器 import）+ 行为断言（决议后工具调用表零增长）
 *      双向钉住。
 *
 * 并发语义（CAS 兜底）
 * -------------------
 * `ApprovalRepo.decide` 自带 CAS：`WHERE id = ? AND status = 'PENDING'`，命中 0 行返
 * `null`。所以"两个请求同时批准"不会双写：一个成功、另一个拿到 `null`。
 * 拿到 `null` 时本层**重新读一次**：行还在 ⇒ 409（带最新 `status`，与前置检查同形）；
 * 行不见了 ⇒ 404（理论上不可能，但比"静默成功"诚实）。
 */

import { ERROR_CODES } from "@wbtime/core";
import {
  APPROVAL_STATUS_PENDING,
  ApprovalRepo,
  Scope,
  type ApprovalRow,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";

import { toIsoOrNull } from "../agent/versioning.js";
import { authError } from "../auth/errors.js";

/** 列表取数缺省 / 上限（契约 `limit` 的 `default: 50` / `maximum: 200`）。 */
export const APPROVALS_LIST_DEFAULT_LIMIT = 50;
export const APPROVALS_LIST_MAX_LIMIT = 200;

/** 对外审批视图（契约 `ApprovalResponse`，12 键逐字对齐）。 */
export interface ApprovalView {
  readonly id: string;
  readonly tenant_id: string | null;
  readonly subject_type: string;
  readonly subject_ref: string;
  readonly requested_by: string | null;
  readonly status: string;
  readonly decided_by: string | null;
  readonly decided_at: string | null;
  readonly payload: Record<string, unknown>;
  readonly expires_at: string | null;
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

/** 列表分页入参（契约 `limit` / `offset`）。 */
export interface ListApprovalsOptions {
  readonly limit?: number;
  readonly offset?: number;
}

/** 审批服务的依赖。 */
export interface ApprovalServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  /** 时钟（决议时刻；测试注入，缺省真实时钟）。 */
  readonly now?: () => Date;
}

/** 审批服务（4 op）。 */
export class ApprovalService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #now: () => Date;

  constructor(deps: ApprovalServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#now = deps.now ?? (() => new Date());
  }

  /**
   * 待办审批（**只返 `PENDING`**，分页）。
   *
   * @param tenantId 租户（来自主体）。
   * @param options `limit`（1..200，缺省 50）/ `offset`（≥0，缺省 0）。
   */
  async listPending(tenantId: string, options: ListApprovalsOptions = {}): Promise<ApprovalView[]> {
    const repo = this.#repo(tenantId);
    const rows = await repo.listPending({
      ...(options.limit === undefined ? {} : { limit: options.limit }),
      ...(options.offset === undefined ? {} : { offset: options.offset }),
    });
    return rows.map(toApprovalView);
  }

  /**
   * 审批详情。
   *
   * @throws {HttpException} `NOT_FOUND`(404)（不存在 / 跨租户 — 同一形态，不泄漏存在性）。
   */
  async getById(tenantId: string, approvalId: string): Promise<ApprovalView> {
    return toApprovalView(await this.#require(tenantId, approvalId));
  }

  /** 决议**通过**（`PENDING → APPROVED`）。 */
  approve(tenantId: string, approvalId: string, decidedBy: string): Promise<ApprovalView> {
    return this.decide(tenantId, approvalId, APPROVED_STATUS, decidedBy);
  }

  /** 决议**驳回**（`PENDING → REJECTED`）。 */
  reject(tenantId: string, approvalId: string, decidedBy: string): Promise<ApprovalView> {
    return this.decide(tenantId, approvalId, REJECTED_STATUS, decidedBy);
  }

  /**
   * 决议（两个 op 的共同主体）。
   *
   * 顺序对齐 py `_decide`：**先** 404（不存在 / 跨租户），**再** 409（已决议），
   * **最后**才写库。顺序反了会让"跨租户 + 已决议"的行回 409 —— 那泄漏了存在性。
   *
   * @throws {HttpException} `NOT_FOUND`(404) / `CONFLICT`(409)。
   */
  async decide(
    tenantId: string,
    approvalId: string,
    status: string,
    decidedBy: string
  ): Promise<ApprovalView> {
    const repo = this.#repo(tenantId);
    const current = await this.#require(tenantId, approvalId);
    if (current.status !== APPROVAL_STATUS_PENDING) {
      throw conflictError(approvalId, current.status);
    }

    const updated = await repo.decide(rowRef(tenantId, approvalId), {
      status,
      decidedBy,
      decidedAt: this.#now(),
    });
    if (updated !== null) {
      return toApprovalView(updated);
    }

    // CAS 未命中 ⇒ 前置检查与写之间被别人抢先决议了。重读一次给出诚实结论：
    // 行还在 ⇒ 409（带**最新** status，不是快照里的旧值）；行没了 ⇒ 404。
    const reread = await repo.findById(rowRef(tenantId, approvalId));
    if (reread === null) {
      throw notFoundError(approvalId);
    }
    throw conflictError(approvalId, reread.status);
  }

  /** scope 内取一行；不可见 ⇒ 404。 */
  async #require(tenantId: string, approvalId: string): Promise<ApprovalRow> {
    const repo = this.#repo(tenantId);
    const row = await repo.findById(rowRef(tenantId, approvalId));
    if (row === null) {
      throw notFoundError(approvalId);
    }
    return row;
  }

  #repo(tenantId: string): ApprovalRepo {
    return new ApprovalRepo(this.#db, new Scope(tenantId), this.#dialect);
  }
}

/** 决议终态：`APPROVED`（与 `ApprovalRepo.approve` 同值；此处保留字面量供 `decide` 复用）。 */
const APPROVED_STATUS = "APPROVED";
/** 决议终态：`REJECTED`。 */
const REJECTED_STATUS = "REJECTED";

/**
 * 审批行的 scope 引用。
 *
 * `Scope#ref()` 只把 `tenantId` 盖成本 scope 的（mint provenance），**不校验行归属**
 * —— 行归属由随后的 scoped `findById` 保证（T3-03 §16.5 注释纪律）。
 */
function rowRef(tenantId: string, approvalId: string) {
  return new Scope(tenantId).ref(approvalId);
}

/** 404（不存在 / 跨租户同一形态）。 */
function notFoundError(approvalId: string) {
  return authError(ERROR_CODES.NOT_FOUND, "审批不存在", { approval_id: approvalId });
}

/** 409（已决议，不可重复决议）—— `data` 键集合与 py `_decide` 逐字一致。 */
function conflictError(approvalId: string, status: string) {
  return authError(ERROR_CODES.CONFLICT, "审批已决议，不可重复决议", {
    approval_id: approvalId,
    status,
  });
}

/** 行 → 契约视图（12 键逐字对齐）。 */
function toApprovalView(row: ApprovalRow): ApprovalView {
  return {
    id: row.id,
    tenant_id: row.tenant_id ?? null,
    // `subject_type` / `subject_ref` 列 NOT NULL，但契约给了 `default: ""` 且非必填
    // ⇒ 保持"空串而非 null"的形状（py `str(... or "")` 同口径）。
    subject_type: row.subject_type ?? "",
    subject_ref: row.subject_ref ?? "",
    requested_by: row.requested_by ?? null,
    status: row.status,
    decided_by: row.decided_by ?? null,
    decided_at: toIsoOrNull(row.decided_at),
    // `payload` 列 NOT NULL ⇒ 恒为对象；仍然 `?? {}` 兜底，避免历史行的 `null` 把契约面打穿。
    payload: (row.payload ?? {}) as Record<string, unknown>,
    expires_at: toIsoOrNull(row.expires_at),
    created_at: toIsoOrNull(row.created_at),
    updated_at: toIsoOrNull(row.updated_at),
  };
}
