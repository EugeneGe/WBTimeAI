/**
 * T3-12 · `model` 仓储（模型目录 · 某供应商下的模型清单）。
 *
 * 表**没有 `tenant_id`**（父 = `model_provider`）⇒ `extends ChildScopedRepo`（R3-22），
 * 父列 = `provider_id`。隔离口径两条：
 *   1. 父引用必须是本 scope 的 `model_provider` `ScopedRef`（`parentExists` 走
 *      **scoped** 的 `ModelProviderRepo.findById`）⇒ 跨租户的 provider 下查不到模型；
 *   2. 所有查询经基类 `scopedWhere()`，父谓词恒在 —— 同租户的**另一个 provider**
 *      也看不见。`Scope#owns()` 只是 mint provenance，不是行归属（T3-03 §16.5 纪律）。
 *
 * 为什么本卡才建这个文件
 * ---------------------
 * 契约 `GET|POST /models/providers/{id}/models`（2 op）一直有，但 T2-07 只落了
 * 凭据族 5 op，`model` 表**没有仓储**（实测 `packages/db/src/repositories/` 下只有
 * `model-provider-repo.ts` / `model-credential-repo.ts`）。本卡补 6 个 models op
 * 必须先补这一层，属**卡面外文件域扩张**，已在施工记录登记（同 T3-07 的
 * `message-repo.ts` 先例）。
 *
 * 本层**不做**的校验（刻意）
 * ------------------------
 * `type` / `status` 是 `VARCHAR(50)` 无枚举、`capabilities` 是自由 JSON、
 * `context_window` 可空 —— 契约 `ModelResponse` 对它们也**没有**枚举/范围约束
 * （只有 `id` / `provider_id` / `name` 必填）。在仓储层擅自加枚举 = 把服务层策略
 * 提前焊死，故一律留给服务层。
 */

import { randomUUID } from "node:crypto";

import type { InferSelectModel } from "drizzle-orm";

import { model as pgModel } from "../schema/pg/model.js";
import { model as sqliteModel } from "../schema/sqlite/model.js";
import {
  ChildScopedRepo,
  type ChildRepoOptions,
  type ChildScopedInsert,
} from "./child-scoped-repo.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import { ModelProviderRepo } from "./model-provider-repo.js";
import type { DrizzleDatabase, ListOptions, Scope, ScopedRef } from "./scoped-repo.js";

/** `model` 行。 */
export type ModelRow = InferSelectModel<typeof pgModel>;

/**
 * 模型「可用」状态值。
 *
 * 与 `apps/api/src/modules/model/provider-service.ts` 写入的值同源，但本包不得
 * import apps（depcruiser `no-package-imports-app`）⇒ 在此显式复述并指向来源，
 * 避免两边各自漂移（`PROVIDER_STATUS_ACTIVE` 同款先例）。
 */
export const MODEL_STATUS_ACTIVE = "ACTIVE";

/** 模型类型的契约缺省值（`ModelResponse.type` 的 `default: "CHAT"`）。 */
export const MODEL_TYPE_CHAT = "CHAT";

/** 注册模型的入参（父 `provider_id` 由基类注入，调用方传不进来）。 */
export interface CreateModelInput {
  /** 模型名（契约 required）。 */
  readonly name: string;
  /** 模型类型；缺省 `CHAT`（契约 default）。 */
  readonly modelType?: string;
  /** 上下文窗口；缺省 `null`（契约 `integer | null`）。 */
  readonly contextWindow?: number | null;
  /** 能力声明；缺省 `null`（契约 `object`，视图层回落 `{}`）。 */
  readonly capabilities?: Record<string, unknown> | null;
}

export class ModelRepo extends ChildScopedRepo<ModelRow, "provider_id"> {
  constructor(
    db: DrizzleDatabase,
    scope: Scope,
    providerRef: ScopedRef,
    dialect: SqlDialect = "pg",
  ) {
    const providers = new ModelProviderRepo(db, scope, dialect);
    const options: ChildRepoOptions = {
      parentColumn: "provider_id",
      parentLabel: "provider",
      parentExists: (ref) => providers.findById(ref).then((row) => row !== null),
    };
    super(db, resolveTable(dialect, pgModel, sqliteModel), scope, providerRef, options);
  }

  /**
   * 本供应商下的全部模型。
   *
   * 契约 `GET /models/providers/{id}/models` 的 `parameters` **只有 path 参数**
   * （无 limit / offset）⇒ 不自造分页；取数走 `resolveListLimit` 的仓内约定上限。
   * 父谓词由基类 and 上 ⇒ 本方法的取数范围**被它锁在本供应商**。
   */
  list(options: ListOptions = {}): Promise<ModelRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /**
   * 注册模型（父存在性在 `insertRow` 内经 `ensureParent()` 校验）。
   *
   * @throws {ScopeError} 父供应商在本 scope 下不可见（不存在 / 跨租户）。
   */
  create(input: CreateModelInput): Promise<ModelRow> {
    const row: Record<string, unknown> = {
      id: randomUUID(),
      name: input.name,
      type: input.modelType ?? MODEL_TYPE_CHAT,
      context_window: input.contextWindow ?? null,
      capabilities: input.capabilities ?? null,
      status: MODEL_STATUS_ACTIVE,
    };
    return this.insertRow(row as unknown as ChildScopedInsert<ModelRow, "provider_id">);
  }
}
