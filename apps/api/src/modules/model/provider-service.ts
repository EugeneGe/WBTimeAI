/**
 * T3-12 · 模型目录服务（**6 op**：供应商目录 4 + 模型目录 2）。
 *
 * 6 op 与错误语义（**py oracle：`wbtime_ai_api/routers/v1/models.py` + `catalog_service.py`
 * 逐条对齐**）
 * ------------------------------------------------------------------------------
 * | # | op | 成功码 | 错误 |
 * |---|---|---|---|
 * | 1 | `GET /models/providers` | 200 数组 | ——（scope 谓词天然隔离） |
 * | 2 | `POST /models/providers` | **201** | `name` 空 ⇒ 422；`provider_type` 非法 ⇒ 422 |
 * | 3 | `GET /models/providers/{id}` | 200 | 不存在 / 跨租户 ⇒ **404** |
 * | 4 | `DELETE /models/providers/{id}` | 200 | 404（**软删**：`status = DISABLED`） |
 * | 5 | `GET /models/providers/{id}/models` | 200 数组 | 供应商不可见 ⇒ 404 |
 * | 6 | `POST /models/providers/{id}/models` | **201** | 供应商不可见 ⇒ 404 |
 *
 * ⚠️ `provider_type` 白名单与 `PROVIDER_KINDS` **不是同一个集合**（刻意不合并）
 * ------------------------------------------------------------------------
 *   - 本文件的 {@link PROVIDER_TYPES} = **py `MODEL_PROVIDER_TYPES` 逐字复制**
 *     （`catalog_service.py:39`）：`openai / anthropic / gemini / deepseek / qwen /
 *     ollama / openai_compatible`。它是 `model_provider.type` 这列**目录标签**的合法值域，
 *     也是 py `register_provider` 的 422 判据（`data={"field":"type","allowed":[...]}`）。
 *   - `modules/model/providers/factory.ts` 的 `PROVIDER_KINDS` 是**适配器实现**的枚举
 *     （`openai / anthropic / google / openai-compatible / fake`），描述"网关怎么调"。
 *   - 两者**语义不同、值域不同**（`gemini` vs `google`、`openai_compatible` vs
 *     `openai-compatible`，且各自有对方没有的项）。合并任何一边都会破坏另一边的判据：
 *     把 `PROVIDER_KINDS` 拿来当白名单 ⇒ py 合法的 `deepseek` 在 TS 侧 422（行为不等价）；
 *     把本表拿去喂 factory ⇒ `gemini` 没有适配器分支（启动期 fail loud）。
 *   - **两边的映射关系归 T3-09**（网关装配必然触碰 `factory.ts`，且 F-7 的穷尽映射
 *     挂账本就在那里）。本卡只负责目录 CRUD，不解决适配器映射 —— 已登记为遗留。
 *
 * 为什么 `DELETE` 是软删
 * ----------------------
 * 契约该 op 成功响应 **200 + `ModelProviderResponse`**（不是 204 零字节）⇒ 删行不成立；
 * `model.provider_id` 有 FK，删行会让模型变悬空引用，而契约没有任何级联声明。
 * py `disable_provider` 同样只改 `status = DISABLED`。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  ModelProviderRepo,
  ModelRepo,
  PROVIDER_STATUS_ACTIVE,
  Scope,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";

import { authError } from "../auth/errors.js";
import { toModelView, toProviderView, type ModelProviderView, type ModelView } from "./view.js";

/**
 * `model_provider.type` 的合法值域 —— **py `MODEL_PROVIDER_TYPES` 逐字复制**。
 *
 * 顺序也照抄（`allowed` 数组会被 422 的 `data` 原样带出，顺序不同就是响应不同）。
 * 与 `PROVIDER_KINDS` 的区别见文件头注。
 */
export const PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "gemini",
  "deepseek",
  "qwen",
  "ollama",
  "openai_compatible",
] as const;

/** 注册供应商的入参（契约 `RegisterProviderRequest`）。 */
export interface RegisterProviderInput {
  readonly name: string;
  readonly providerType: string;
  readonly endpoint?: string | null;
  readonly credentialId?: string | null;
  readonly config?: Record<string, unknown> | null;
  readonly workspaceId?: string | null;
}

/** 注册模型的入参（契约 `RegisterModelRequest`）。 */
export interface RegisterModelInput {
  readonly name: string;
  readonly modelType?: string;
  readonly contextWindow?: number | null;
  readonly capabilities?: Record<string, unknown> | null;
}

/** 供应商列表的取数上限（契约该 op 无分页参数 ⇒ 同 T3-07 口径取仓内允许的最大值）。 */
export const PROVIDERS_LIST_LIMIT = 500;

/** 模型列表的取数上限（同上）。 */
export const MODELS_LIST_LIMIT = 500;

/** 模型目录服务的依赖。 */
export interface ModelProviderServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
}

/** 模型目录服务（6 op）。 */
export class ModelProviderService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(deps: ModelProviderServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
  }

  /** 本租户全部供应商（py `list_providers` 无分页 ⇒ 取仓内上限）。 */
  async listProviders(tenantId: string): Promise<ModelProviderView[]> {
    const repo = new ModelProviderRepo(this.#db, new Scope(tenantId), this.#dialect);
    const rows = await repo.list({ limit: PROVIDERS_LIST_LIMIT });
    return rows.map(toProviderView);
  }

  /**
   * 注册供应商。
   *
   * 两条服务层校验（**契约不约束，py 才是判据**）：
   *   ① `name` trim 后为空 ⇒ 422 `VALIDATION_ERROR` + `{field:"name"}`
   *      （schema 只挡长度，`"   "` 能过 schema）；
   *   ② `providerType` 不在 {@link PROVIDER_TYPES} ⇒ 422 + `{field:"type", allowed:[...]}`。
   *      ⚠️ `data` 的键是 **`type`** 而不是 `provider_type` —— py 原文如此，改了就与 oracle 不同。
   *
   * `credential_id` **只存引用**，不校验存在性（py `register_provider` 同样不校验；
   * 悬空引用由 T3-02 的 `resolveKeyCarrier` 在网关解析时暴露成 `missing` 状态）。
   */
  async registerProvider(
    tenantId: string,
    input: RegisterProviderInput
  ): Promise<ModelProviderView> {
    const name = (input.name ?? "").trim();
    if (name === "") {
      throw authError(ERROR_CODES.VALIDATION_ERROR, "提供方名称不能为空", { field: "name" });
    }
    const providerType = (input.providerType ?? "").trim();
    if (!(PROVIDER_TYPES as readonly string[]).includes(providerType)) {
      throw authError(ERROR_CODES.VALIDATION_ERROR, `提供方类型非法：${JSON.stringify(input.providerType)}`, {
        field: "type",
        allowed: [...PROVIDER_TYPES],
      });
    }

    const repo = new ModelProviderRepo(this.#db, new Scope(tenantId), this.#dialect);
    const row = await repo.create({
      id: randomUUID(),
      organization_id: null,
      workspace_id: input.workspaceId ?? null,
      name,
      type: providerType,
      endpoint: input.endpoint ?? null,
      credential_id: input.credentialId ?? null,
      status: PROVIDER_STATUS_ACTIVE,
      // py `dict(config) if config else {}` ⇒ 缺省落 `{}` 而不是 `null`（列可空，但同形）。
      config: (input.config ?? {}) as never,
    } as never);
    return toProviderView(row);
  }

  /**
   * 供应商详情。
   *
   * @throws {HttpException} `NOT_FOUND`(404)（不存在 / 跨租户同一形态）。
   */
  async getProvider(tenantId: string, providerId: string): Promise<ModelProviderView> {
    return toProviderView(await this.#requireProvider(tenantId, providerId));
  }

  /**
   * 禁用供应商（**软删**，重复禁用幂等）。
   *
   * @throws {HttpException} `NOT_FOUND`(404)。
   */
  async disableProvider(tenantId: string, providerId: string): Promise<ModelProviderView> {
    const scope = new Scope(tenantId);
    const repo = new ModelProviderRepo(this.#db, scope, this.#dialect);
    const updated = await repo.disable(scope.ref(providerId));
    if (updated === null) {
      throw notFoundProvider(providerId);
    }
    return toProviderView(updated);
  }

  /**
   * 某供应商下的模型清单。
   *
   * **先验供应商可见**再列：若直接 `ModelRepo.list()`，父不存在时 `ensureParent()` 抛
   * `ScopeError`（未映射 ⇒ 500），而 py 是显式 404。这一步把错误形态拉回契约面。
   *
   * @throws {HttpException} `NOT_FOUND`(404)。
   */
  async listModels(tenantId: string, providerId: string): Promise<ModelView[]> {
    await this.#requireProvider(tenantId, providerId);
    const repo = this.#models(tenantId, providerId);
    const rows = await repo.list({ limit: MODELS_LIST_LIMIT });
    return rows.map(toModelView);
  }

  /**
   * 在某供应商下注册模型。
   *
   * @throws {HttpException} `NOT_FOUND`(404)（供应商不可见；**先查**，不让 `ensureParent`
   *   的 `ScopeError` 冒成 500）。
   */
  async registerModel(
    tenantId: string,
    providerId: string,
    input: RegisterModelInput
  ): Promise<ModelView> {
    await this.#requireProvider(tenantId, providerId);
    const repo = this.#models(tenantId, providerId);
    const row = await repo.create({
      name: input.name,
      ...(input.modelType === undefined ? {} : { modelType: input.modelType }),
      ...(input.contextWindow === undefined ? {} : { contextWindow: input.contextWindow }),
      ...(input.capabilities === undefined ? {} : { capabilities: input.capabilities }),
    });
    return toModelView(row);
  }

  /** scope 内取供应商；不可见 ⇒ 404。 */
  async #requireProvider(tenantId: string, providerId: string) {
    const scope = new Scope(tenantId);
    const repo = new ModelProviderRepo(this.#db, scope, this.#dialect);
    const row = await repo.findById(scope.ref(providerId));
    if (row === null) {
      throw notFoundProvider(providerId);
    }
    return row;
  }

  /** 子表仓储（父引用由本 scope 铸造；父归属由 `#requireProvider` 先验过）。 */
  #models(tenantId: string, providerId: string): ModelRepo {
    const scope = new Scope(tenantId);
    return new ModelRepo(this.#db, scope, scope.ref(providerId), this.#dialect);
  }
}

/** 404（供应商不存在 / 跨租户）。 */
function notFoundProvider(providerId: string) {
  return authError(ERROR_CODES.NOT_FOUND, "供应商不存在", { provider_id: providerId });
}
