/**
 * T2-07 · `model_provider` 仓储（模型供应商）。
 *
 * 绑定 / 解绑凭据的两个 op（`POST|DELETE /api/v1/models/providers/{provider_id}/credential`）
 * 落在这张表的 `credential_id` 列上 —— 契约 `ModelProviderResponse` 里就是这个字段，
 * 因此以它为准（`model_provider_credential` 连接表用于"一个 provider 挂多把 key 做权重
 * 轮换"，本版 19 op 没有读它的入口，故不在此维护，登记为遗留）。
 *
 * `credential_id` 可空：解绑 = 置回 `null`（**不是**删 provider）。
 */

import { eq, type InferSelectModel } from "drizzle-orm";

import { model_provider as pgModelProvider } from "../schema/pg/index.js";
import { model_provider as sqliteModelProvider } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `model_provider` 行。 */
export type ModelProviderRow = InferSelectModel<typeof pgModelProvider>;

export class ModelProviderRepo extends ScopedRepo<ModelProviderRow> {
  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgModelProvider, sqliteModelProvider), scope);
  }

  /** 本租户全部供应商。 */
  list(options: ListOptions = {}): Promise<ModelProviderRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /** 按名字取（运维面用；同名不唯一约束，故返回首个）。 */
  findByName(name: string): Promise<ModelProviderRow | null> {
    return this.findOneWhere(eq(this.columns.name, name));
  }

  /**
   * 绑定凭据：把 `credential_id` 指向给定凭据。
   *
   * @param providerRef 供应商在**本 scope** 下的引用（裸 id 在类型层不可达）。
   * @param credentialId 凭据 id（须已由 `ModelCredentialRepo` 校验存在性）。
   * @returns 更新后的行；供应商不存在或跨租户时返回 `null`（→ 调用方折 404）。
   */
  bindCredential(providerRef: ScopedRef, credentialId: string): Promise<ModelProviderRow | null> {
    this.assertOwnRef(providerRef, "providerRef");
    return this.update(providerRef, { credential_id: credentialId });
  }

  /**
   * 解绑凭据：`credential_id` 置回 `null`。
   *
   * @param providerRef 供应商引用。
   * @returns 更新后的行；不可见时 `null`（→ 404）。
   */
  unbindCredential(providerRef: ScopedRef): Promise<ModelProviderRow | null> {
    this.assertOwnRef(providerRef, "providerRef");
    return this.update(providerRef, { credential_id: null });
  }

  create(row: TenantScopedInsert<ModelProviderRow>): Promise<ModelProviderRow> {
    return this.insertRow(row);
  }
}
