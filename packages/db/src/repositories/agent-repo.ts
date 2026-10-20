/** T1-03 · agent 领域仓储（PG 档）。 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { agent } from "../schema/pg/index.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type TenantScopedInsert,
} from "./scoped-repo.js";

export type AgentRow = InferSelectModel<typeof agent>;

export class AgentRepo extends ScopedRepo<AgentRow> {
  constructor(db: DrizzleDatabase, scope: Scope) {
    super(db, agent, scope);
  }

  listByType(type: string, options: ListOptions = {}): Promise<AgentRow[]> {
    return this.findManyWhere(eq(this.columns.type, type), options);
  }

  listActive(options: ListOptions = {}): Promise<AgentRow[]> {
    return this.findManyWhere(eq(this.columns.status, "active"), options);
  }

  create(row: TenantScopedInsert<AgentRow>): Promise<AgentRow> {
    return this.insertRow(row);
  }
}
