/**
 * T2-07 · `model_provider` 仓储（模型供应商）。
 *
 * 绑定 / 解绑凭据的两个 op（`POST|DELETE /api/v1/models/providers/{provider_id}/credential`）
 * 落在这张表的 `credential_id` 列上 —— 契约 `ModelProviderResponse` 里就是这个字段，
 * 因此以它为准（`model_provider_credential` 连接表用于"一个 provider 挂多把 key 做权重
 * 轮换"，本版 19 op 没有读它的入口，故不在此维护，登记为遗留）。
 *
 * `credential_id` 可空：解绑 = 置回 `null`（**不是**删 provider）。
 *
 * **T3-02 补读（本轮）**：`ModelGateway` 装配需要「按 provider / credential 解析」，
 * 新增四个读方法（{@link ModelProviderRepo.findByType} / `listByStatus` /
 * `findActiveByType` / `resolveKeyCarrier`），**零 DDL**（不加列、不加索引），
 * 全部落在既有列上；ORM import 仍只在本目录内。
 */

import { and, eq, type InferSelectModel } from "drizzle-orm";

import { model_provider as pgModelProvider } from "../schema/pg/index.js";
import { model_provider as sqliteModelProvider } from "../schema/sqlite/index.js";
import { ModelCredentialRepo, type CredentialRow } from "./model-credential-repo.js";
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

/**
 * 凭据的「可用」状态值。
 *
 * 与 `apps/api/src/modules/credential/service.ts` 写入 `credential.status` 的值同源
 * （该处常量 `"ACTIVE"` 在 service 层，本包不得 import apps —— depcruiser
 * `no-package-imports-app`），故在此**显式复述**并指向来源，避免两边各自漂移。
 */
export const CREDENTIAL_STATUS_ACTIVE = "ACTIVE";

/** 供应商的「可用」状态值（同上：与 service 层写入值同源，`model_provider.status`）。 */
export const PROVIDER_STATUS_ACTIVE = "ACTIVE";

/**
 * 供应商的「已禁用」状态值（T3-12 · `DELETE /models/providers/{id}` 是**软删**）。
 *
 * py `catalog_service.py:136` 的 `MODEL_PROVIDER_STATUS_DISABLED` 同值；
 * 端点语义也是「禁用」而不是删行（契约 `DELETE` 回 **200 + ModelProviderResponse**，
 * 204 才是零字节删除 —— 这条成功码本身就是软删的证据）。
 */
export const PROVIDER_STATUS_DISABLED = "DISABLED";

/** 凭据载体的解析结果：**为什么 `null` 必须说清原因**。 */
export type CredentialState =
  /** 已绑定且状态可用 ⇒ `credential` 非 null。 */
  | "bound"
  /** `credential_id` 为空 ⇒ 未绑定（解绑后的正常态）。 */
  | "unbound"
  /** `credential_id` 有值但库里查不到 ⇒ 悬空引用（**数据不一致**，必须可见）。 */
  | "missing"
  /** 查到但状态不是可用 ⇒ 已被禁用（不得当"没绑"静默处理）。 */
  | "inactive";

/** 一个供应商当前可用于出网的 key 载体。 */
export interface ProviderKeyCarrier {
  readonly provider: ModelProviderRow;
  /** 可用凭据；`null` 时见 {@link ProviderKeyCarrier.credentialState} 的原因。 */
  readonly credential: CredentialRow | null;
  readonly credentialState: CredentialState;
}

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

  // -------------------------------------------------------------------------
  // T3-02 · Gateway 解析供应商需要的读（**零 DDL**：全部落在既有列上）
  //
  // `providers/factory.ts` 建适配器只需要三样东西：`kind` / `apiKey` / `baseURL`。
  // 落到这两张表上就是：`model_provider.type` → kind、`model_provider.endpoint` →
  // baseURL、`model_provider.credential_id → credential.id` → key 载体（密文，
  // 解密在 service 层，本仓储**只搬运信封**）。
  // -------------------------------------------------------------------------

  /**
   * 按 `type`（= provider kind，取值集合与 `apps/api` 的 `PROVIDER_KINDS` 对齐）
   * 取本租户的供应商；同 type 不唯一（无唯一约束），故返回首个。
   */
  async findByType(type: string, options: ListOptions = {}): Promise<ModelProviderRow | null> {
    const rows = await this.findManyWhere(eq(this.columns.type, type), { ...options, limit: 1 });
    return rows[0] ?? null;
  }

  /** 按状态列举（典型用法：只取 `ACTIVE`）。 */
  listByStatus(status: string, options: ListOptions = {}): Promise<ModelProviderRow[]> {
    return this.findManyWhere(eq(this.columns.status, status), options);
  }

  /**
   * 按 kind + 状态取首个**可用**供应商（Gateway 冷启动解析的默认入口）。
   *
   * @param activeStatus 可用状态值，缺省 {@link PROVIDER_STATUS_ACTIVE}。
   */
  async findActiveByType(
    type: string,
    options: { readonly activeStatus?: string } = {},
  ): Promise<ModelProviderRow | null> {
    const rows = await this.findManyWhere(
      and(
        eq(this.columns.type, type),
        eq(this.columns.status, options.activeStatus ?? PROVIDER_STATUS_ACTIVE),
      ),
      { limit: 1 },
    );
    return rows[0] ?? null;
  }

  /**
   * 解析该供应商当前可用的 key 载体（**跨租户 ⇒ 抛 `ScopeError`，不是空结果**）。
   *
   * 为什么 `credential` 为 `null` 时要带 {@link CredentialState}：
   * 「没绑」「绑了个不存在的 id」「绑了但被禁用」三种情形的处置完全不同 ——
   * 前两种是配置/数据问题（fail loud），最后一种是运维动作。混成一个 `null`
   * 会让上层只能"当作没配"，把悬空引用变成哑失败。
   *
   * @param providerRef 供应商在**本 scope** 下的引用。
   * @param credentials 凭据仓储；其 scope 必须同租户，否则 `findById` 抛 `ScopeError`。
   * @returns 供应商不可见 ⇒ `null`；可见 ⇒ 载体（含原因）。
   */
  async resolveKeyCarrier(
    providerRef: ScopedRef,
    credentials: ModelCredentialRepo,
    options: { readonly activeStatus?: string } = {},
  ): Promise<ProviderKeyCarrier | null> {
    this.assertOwnRef(providerRef, "providerRef");
    const provider = await this.findById(providerRef);
    if (provider === null) return null;

    const credentialId = provider.credential_id;
    if (credentialId === null || credentialId === undefined || credentialId.trim() === "") {
      return { provider, credential: null, credentialState: "unbound" };
    }

    // 同一 scope ⇒ 租户谓词恒在；跨租户的 credentials 仓储会在这里抛 ScopeError。
    const credential = await credentials.findById(this.scope.ref(credentialId));
    if (credential === null) {
      return { provider, credential: null, credentialState: "missing" };
    }
    if (credential.status !== (options.activeStatus ?? CREDENTIAL_STATUS_ACTIVE)) {
      return { provider, credential: null, credentialState: "inactive" };
    }
    return { provider, credential, credentialState: "bound" };
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

  /**
   * 禁用供应商（T3-12 · `DELETE /api/v1/models/providers/{provider_id}` 的实现）。
   *
   * **不是删行**：契约该 op 的成功响应是 **200 + `ModelProviderResponse`**（不是 204），
   * py `catalog_service.disable_provider` 也只改 `status = DISABLED` 后 `update`。
   * 删行会让该供应商下的模型（`model.provider_id` FK）变成悬空引用，而契约没有任何
   * 级联删除的声明 —— 软删是唯一与契约自洽的形态。
   *
   * 幂等性：重复禁用 ⇒ 仍返回同一行（`status` 已是 `DISABLED`），不报错。
   * 这一点与 py 同形（py 只 `_require_provider` 后再赋值，不看当前状态）。
   *
   * @param providerRef 供应商在本 scope 下的引用。
   * @returns 更新后的行；供应商不存在或跨租户时 `null`（→ 调用方折 404）。
   */
  disable(providerRef: ScopedRef): Promise<ModelProviderRow | null> {
    this.assertOwnRef(providerRef, "providerRef");
    return this.update(providerRef, { status: PROVIDER_STATUS_DISABLED });
  }

  create(row: TenantScopedInsert<ModelProviderRow>): Promise<ModelProviderRow> {
    return this.insertRow(row);
  }
}
