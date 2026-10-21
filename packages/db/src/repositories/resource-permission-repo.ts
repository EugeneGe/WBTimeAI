/**
 * T2-03 · `resource_permission` 仓储（**实例级** 主体 × 资源 × 动作 判决）。
 *
 * 关键列语义（计划 §2）：`subject_type`(`agent`/`user`) · `resource_type` ·
 * `resource_id`(`NULL` = 类型级) · `action` · `effect`(`ALLOW`/`DENY`) · `scope`。
 *
 * ⚠️ 判权**不在仓储里**（计划 §4.3）
 * ---------------------------------
 * 仓储只能表达「看不见」（→404），不能表达「拒绝」（→403）；把判权下推进 repo，
 * 跨租户就会从 404 变成 403，直接破 I-1。因此本文件分成两半：
 *
 * * {@link ResourcePermissionRepo} —— 只取「适用行」，不判；
 * * {@link decideResourcePermission} —— **纯函数**，无 IO、可直接单测，由 Router/Service
 *   在拿到适用行之后调用。纯函数放在这里只是因为它是这张表的语义，不代表「仓储判权」。
 *
 * 判决规则（计划 §4.2 原文）：`DENY` **优先于** `ALLOW`；无显式 `ALLOW` ⇒ 默认拒绝。
 * 粒度优先（实例级 vs 类型级谁先）计划**未定义**，故本版按字面合并所有适用行，
 * 不发明优先级（已在施工记录登记为遗留）。
 */

import { and, eq, isNull, or, type InferSelectModel } from "drizzle-orm";

import { resource_permission as pgResourcePermission } from "../schema/pg/index.js";
import { resource_permission as sqliteResourcePermission } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `resource_permission` 行。 */
export type ResourcePermissionRow = InferSelectModel<typeof pgResourcePermission>;

/** 判决效果。列宽 `varchar(10)` 已固定，取值域只在代码层枚举（不改 DDL，见计划 U-5）。 */
export type PermissionEffect = "ALLOW" | "DENY";

/** 主体类型。本版不扩取值域（扩 = 改约束 = DDL 变更）。 */
export type PermissionSubjectType = "agent" | "user";

/** 一次判决查询的坐标。`resourceId = null` 表示「只要类型级」。 */
export interface ResourcePermissionQuery {
  readonly subjectType: PermissionSubjectType | string;
  readonly subjectId: string;
  readonly resourceType: string;
  readonly resourceId: string | null;
  readonly action: string;
}

/** 一次判决的结论。`matchedId` 命中的行 id（默认拒绝时为 `null`），便于审计。 */
export interface ResourceDecision {
  readonly allowed: boolean;
  readonly effect: PermissionEffect;
  /** 决定该结论的行 id；`DENY` 优先命中时指向那条 `DENY` 行。 */
  readonly matchedId: string | null;
}

export class ResourcePermissionRepo extends ScopedRepo<ResourcePermissionRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgResourcePermission, sqliteResourcePermission), scope);
  }

  /**
   * 取**适用**的判决行（不判、不排序偏好）。
   *
   * 适用 = 主体一致 + 资源类型一致 + 动作一致 + （行是类型级 `NULL` **或** 指向该实例）。
   * 全部条件经 `findManyWhere` → 租户谓词恒在。
   */
  listApplicable(
    query: ResourcePermissionQuery,
    options: ListOptions = {}
  ): Promise<ResourcePermissionRow[]> {
    const instanceOrTypeLevel =
      query.resourceId === null
        ? isNull(this.columns.resource_id)
        : or(isNull(this.columns.resource_id), eq(this.columns.resource_id, query.resourceId));
    return this.findManyWhere(
      and(
        eq(this.columns.subject_type, query.subjectType),
        eq(this.columns.subject_id, query.subjectId),
        eq(this.columns.resource_type, query.resourceType),
        eq(this.columns.action, query.action),
        instanceOrTypeLevel
      ),
      options
    );
  }

  /** 取某主体在某资源类型下的全部判决行（管理面列表用）。 */
  listBySubject(
    subjectType: string,
    subjectId: string,
    resourceType: string,
    options: ListOptions = {}
  ): Promise<ResourcePermissionRow[]> {
    return this.findManyWhere(
      and(
        eq(this.columns.subject_type, subjectType),
        eq(this.columns.subject_id, subjectId),
        eq(this.columns.resource_type, resourceType)
      ),
      options
    );
  }

  /** 新增判决行（`scope` 列 `NOT NULL`，由调用方给出 JSON 值）。 */
  create(row: TenantScopedInsert<ResourcePermissionRow>): Promise<ResourcePermissionRow> {
    return this.insertRow(row);
  }
}

/**
 * 纯函数判决：`DENY` 优先于 `ALLOW`，无显式 `ALLOW` ⇒ 默认拒绝（计划 §4.2）。
 *
 * @param grants 已由 {@link ResourcePermissionRepo.listApplicable} 取出的适用行
 * @param query 判决坐标（用于再筛一遍；纯函数不信任调用方已筛干净）
 */
export function decideResourcePermission(
  grants: readonly ResourcePermissionRow[],
  query: ResourcePermissionQuery
): ResourceDecision {
  const applicable = grants.filter(
    (row) =>
      row.subject_type === query.subjectType &&
      row.subject_id === query.subjectId &&
      row.resource_type === query.resourceType &&
      row.action === query.action &&
      (row.resource_id === null || row.resource_id === query.resourceId)
  );

  // ① DENY 优先：只要存在一条适用 DENY，结论就是拒绝 —— 与 ALLOW 的条数无关。
  const deny = applicable.find((row) => row.effect === "DENY");
  if (deny) return { allowed: false, effect: "DENY", matchedId: deny.id };

  // ② 有显式 ALLOW 才允许。
  const allow = applicable.find((row) => row.effect === "ALLOW");
  if (allow) return { allowed: true, effect: "ALLOW", matchedId: allow.id };

  // ③ 无适用行（或行内 effect 取值非法）⇒ 默认拒绝，不回显任何 id。
  return { allowed: false, effect: "DENY", matchedId: null };
}
