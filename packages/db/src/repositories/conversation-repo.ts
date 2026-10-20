/** T1-03 · conversation 领域仓储（PG 档）。 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { conversation } from "../schema/pg/index.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

export type ConversationRow = InferSelectModel<typeof conversation>;

export class ConversationRepo extends ScopedRepo<ConversationRow> {
  constructor(db: DrizzleDatabase, scope: Scope) {
    super(db, conversation, scope);
  }

  /** 按 agent 列举会话：agent 也必须以 ``ScopedRef`` 传入（不能是裸 id）。 */
  listByAgent(agentRef: ScopedRef, options: ListOptions = {}): Promise<ConversationRow[]> {
    this.assertOwnRef(agentRef, "agentRef");
    return this.findManyWhere(eq(this.columns.agent_id, agentRef.id), options);
  }

  listByUser(userRef: ScopedRef, options: ListOptions = {}): Promise<ConversationRow[]> {
    this.assertOwnRef(userRef, "userRef");
    return this.findManyWhere(eq(this.columns.user_id, userRef.id), options);
  }

  create(row: TenantScopedInsert<ConversationRow>): Promise<ConversationRow> {
    return this.insertRow(row);
  }
}
