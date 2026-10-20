/**
 * T1-03 · task 领域仓储（PG 档）。
 *
 * 只声明领域查询；scope 纪律（租户过滤 / 禁裸 id）由 {@link ScopedRepo} 继承而来，
 * 这里**没有**任何可以绕开它的入口。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { task } from "../schema/pg/index.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type TenantScopedInsert,
} from "./scoped-repo.js";

export type TaskRow = InferSelectModel<typeof task>;

export class TaskRepo extends ScopedRepo<TaskRow> {
  constructor(db: DrizzleDatabase, scope: Scope) {
    super(db, task, scope);
  }

  /** 幂等键在契约里带唯一索引 ``uq_task_idempotency_key``，因此查询必须落在 scope 内。 */
  findByIdempotencyKey(key: string): Promise<TaskRow | null> {
    return this.findOneWhere(eq(this.columns.idempotency_key, key));
  }

  listByStatus(status: string, options: ListOptions = {}): Promise<TaskRow[]> {
    return this.findManyWhere(eq(this.columns.status, status), options);
  }

  list(options: ListOptions = {}): Promise<TaskRow[]> {
    return this.findManyWhere(undefined, options);
  }

  create(row: TenantScopedInsert<TaskRow>): Promise<TaskRow> {
    return this.insertRow(row);
  }
}
