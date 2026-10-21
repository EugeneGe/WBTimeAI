/**
 * T2-07 · `credential` 仓储（模型供应商凭据存根）。
 *
 * 表名是 **`credential`**（不是任务卡猜的 `model_credential`）—— 实测
 * `packages/db/src/schema/pg/model.ts:12`。该表**不在** T2-03 的 11 张身份表内，因此
 * 本文件是 T2-07 新增的；实现方式与身份族完全一致（`ScopedRepo` + `dialect` 参数化）。
 *
 * 🔴 安全红线（计划 §7.1-2）：本仓储**只搬运已加密的串**。
 * `encrypted_value` 列里存的是 AES-256-GCM 密文（`apps/api/src/modules/credential/crypto.ts`），
 * 明文**永不**进入这一层，也永不进入本文件任何方法的入参/返回值签名（签名里只有
 * `encrypted_value: string`，语义上是"不透明信封"）。加密与解密都在 service 层，
 * 这样"有没有漏掉某一处加密"只需要审一个文件。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { credential as pgCredential } from "../schema/pg/index.js";
import { credential as sqliteCredential } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `credential` 行。 */
export type CredentialRow = InferSelectModel<typeof pgCredential>;

export class ModelCredentialRepo extends ScopedRepo<CredentialRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgCredential, sqliteCredential), scope);
  }

  /** 本租户全部凭据（新的在前）。 */
  list(options: ListOptions = {}): Promise<CredentialRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /** 按供应商过滤（同一 provider 可有多把 key 轮换）。 */
  listByProvider(provider: string, options: ListOptions = {}): Promise<CredentialRow[]> {
    return this.findManyWhere(eq(this.columns.provider, provider), options);
  }

  /** 建档：`encrypted_value` 必须是**密文**（加密在 service 层）。 */
  create(row: TenantScopedInsert<CredentialRow>): Promise<CredentialRow> {
    return this.insertRow(row);
  }
}
