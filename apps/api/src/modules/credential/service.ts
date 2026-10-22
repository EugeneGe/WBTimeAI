/**
 * T2-07 · 凭据服务（5 个 op 里的 4 个：列 / 存 / 删 / 绑 / 解绑）。
 *
 * 明文只在本文件的两个瞬间存在：**入参**（`save` 的 `value`）与**掩码生成**。
 * 落库值永远是 `encryptValue()` 的信封；出参永远只有 `masked_value`。
 *
 * 为什么 `list` 不解密
 * -------------------
 * 列凭据时若对每行解密，明文会在每次列表请求时进一次内存 —— 白白扩大暴露面，
 * 而列表只需要"认出是哪把 key"。因此 `save` 时把掩码写进 `metadata.masked_value`，
 * `list` 直接读它（读不到就 `****`，**不**回退去解密）。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  ModelCredentialRepo,
  ModelProviderRepo,
  Scope,
  instantLiteral,
  type CredentialRow,
  type DrizzleDatabase,
  type ModelProviderRow,
  type SqlDialect,
} from "@wbtime/db";

import { authError } from "../auth/errors.js";
import { toProviderView, type ModelProviderView } from "../model/view.js";
import { deriveCredentialKey, encryptValue, maskValue } from "./crypto.js";

/** 对外凭据视图（契约 `CredentialResponse`，键集合逐字对齐）。 */
export interface CredentialView {
  readonly id: string;
  readonly provider: string;
  readonly key_type: string;
  readonly masked_value: string;
  readonly created_at: string | null;
  readonly workspace_id: string | null;
}

/**
 * 对外供应商视图（契约 `ModelProviderResponse`）。
 *
 * **定义已迁至 `../model/view.js`**（T3-12：provider 目录的 6 个新 op 用同一形状，
 * 两份实现必然漂移）。此处 re-export 只为不打断 T2-07 既有 import 面。
 */
export type { ModelProviderView } from "../model/view.js";

/** 保存凭据的入参（契约 `SaveCredentialRequest`）。 */
export interface SaveCredentialInput {
  readonly provider: string;
  readonly value: string;
  readonly key_type?: string;
  readonly workspace_id?: string | null;
}

/** 凭据服务的依赖。 */
export interface CredentialServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  /** 主密钥（装配入口经 `requireSecretKey()` 取到的那一把）。 */
  readonly secretKey: string;
  /** 时钟（测试注入；缺省真实时钟）。 */
  readonly now?: () => Date;
}

/** 凭据 / 供应商服务。 */
export class CredentialService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #key: Buffer;
  readonly #now: () => Date;

  constructor(deps: CredentialServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#key = deriveCredentialKey(deps.secretKey);
    this.#now = deps.now ?? (() => new Date());
  }

  /** 列本租户凭据（新的在前）。 */
  async list(tenantId: string): Promise<CredentialView[]> {
    const scope = new Scope(tenantId);
    const repo = new ModelCredentialRepo(this.#db, scope, this.#dialect);
    const rows = await repo.list({ limit: 500 });
    return rows.map(toCredentialView);
  }

  /**
   * 保存凭据（**加密后落库**）。
   *
   * @param tenantId 租户（来自主体）。
   * @param input 契约 `SaveCredentialRequest`。
   * @throws {RangeError} `provider` / `value` 为空（schema 已先挡；此处是纵深防御）。
   */
  async save(tenantId: string, input: SaveCredentialInput): Promise<CredentialView> {
    if (typeof input.provider !== "string" || input.provider === "") {
      throw new RangeError("save：provider 必须非空");
    }
    if (typeof input.value !== "string" || input.value === "") {
      // 空值绝不能落库：`encryptValue("")` 会抛，但那是一句"加密失败"，语义离根因很远。
      throw new RangeError("save：value 必须非空");
    }

    const scope = new Scope(tenantId);
    const repo = new ModelCredentialRepo(this.#db, scope, this.#dialect);
    const now = this.#now();
    const row = await repo.create({
      id: randomUUID(),
      provider: input.provider,
      key_type: input.key_type ?? "api_key",
      encrypted_value: encryptValue(input.value, this.#key),
      // 只存展示用掩码；**不存**明文、不存明文任何前后缀片段（末 4 位除外）。
      metadata: { masked_value: maskValue(input.value) },
      name: null,
      status: "ACTIVE",
      organization_id: null,
      workspace_id: input.workspace_id ?? null,
      last_used_at: null,
      ...auditStamps(this.#dialect, now),
    });
    return toCredentialView(row);
  }

  /**
   * 删除凭据。
   *
   * @param tenantId 租户。
   * @param credentialId 凭据 id。
   * @throws {HttpException} `CREDENTIAL_NOT_FOUND`（404）—— 不存在与跨租户同码，
   *   不区分（否则 404/403 差异会泄露"别的租户有这条"）。
   */
  async remove(tenantId: string, credentialId: string): Promise<void> {
    const scope = new Scope(tenantId);
    const repo = new ModelCredentialRepo(this.#db, scope, this.#dialect);
    const removed = await repo.remove(scope.ref(credentialId));
    if (!removed) {
      throw authError(ERROR_CODES.CREDENTIAL_NOT_FOUND, "凭据不存在", {
        credential_id: credentialId,
      });
    }
  }

  /**
   * 绑定凭据到供应商。
   *
   * 两道存在性检查都必须是 scoped 的：供应商与凭据**任一**不可见 ⇒ 404。
   * 检查顺序与实现一致（V0.2.0 审计 #26 订正：原 JSDoc 写反了方向）：
   * **供应商先查**（`NOT_FOUND`），**再查凭据**（更具体的码 `CREDENTIAL_NOT_FOUND`）
   * —— 该顺序对齐 py（依据见方法体内注释）。
   *
   * @param tenantId 租户。
   * @param providerId 供应商 id。
   * @param credentialId 凭据 id。
   * @throws {HttpException} `CREDENTIAL_NOT_FOUND` / `NOT_FOUND`（均 404）。
   */
  async bind(tenantId: string, providerId: string, credentialId: string): Promise<ModelProviderView> {
    const scope = new Scope(tenantId);

    // **顺序对齐 py**：先查供应商，再查凭据。
    // 依据：J-11 的 oracle 里 `bind_credential` 那条 provider 与 credential **同时**不存在，
    // py 回的是 `NOT_FOUND` + `data={provider_id}`（不是 CREDENTIAL_NOT_FOUND）。顺序反过来
    // 会让 `data` 的键集合与 py 不同 ⇒ J-11 当场红。这不是风格问题。
    const providers = new ModelProviderRepo(this.#db, scope, this.#dialect);
    if ((await providers.findById(scope.ref(providerId))) === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "供应商不存在", { provider_id: providerId });
    }

    const credentials = new ModelCredentialRepo(this.#db, scope, this.#dialect);
    if ((await credentials.findById(scope.ref(credentialId))) === null) {
      throw authError(ERROR_CODES.CREDENTIAL_NOT_FOUND, "凭据不存在", {
        credential_id: credentialId,
      });
    }

    const updated = await providers.bindCredential(scope.ref(providerId), credentialId);
    if (updated === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "供应商不存在", { provider_id: providerId });
    }
    return toProviderView(updated);
  }

  /**
   * 解绑供应商凭据（`credential_id` 置回 `null`，**不删**供应商）。
   *
   * @param tenantId 租户。
   * @param providerId 供应商 id。
   * @throws {HttpException} `NOT_FOUND`(404)。
   */
  async unbind(tenantId: string, providerId: string): Promise<ModelProviderView> {
    const scope = new Scope(tenantId);
    const providers = new ModelProviderRepo(this.#db, scope, this.#dialect);
    const updated = await providers.unbindCredential(scope.ref(providerId));
    if (updated === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "供应商不存在", { provider_id: providerId });
    }
    return toProviderView(updated);
  }
}

/** `created_at` / `updated_at`：PG 档 `Date`、SQLite 档 `YYYY-MM-DD HH:MM:SS`（T2-03 D-6）。 */
function auditStamps(dialect: SqlDialect, at: Date): { created_at: Date; updated_at: Date } {
  const stamp = instantLiteral(dialect, at) as unknown as Date;
  return { created_at: stamp, updated_at: stamp };
}

/** 行 → 契约视图（掩码取自 `metadata.masked_value`，**不解密**）。 */
function toCredentialView(row: CredentialRow): CredentialView {
  const metadata = (row.metadata ?? {}) as Record<string, unknown>;
  const masked = typeof metadata.masked_value === "string" ? metadata.masked_value : "****";
  return {
    id: row.id,
    provider: row.provider,
    key_type: row.key_type,
    masked_value: masked,
    created_at: toIsoOrNull(row.created_at),
    workspace_id: row.workspace_id ?? null,
  };
}

/** 行 → 契约视图。供货商形状的定义已迁至 `../model/view.js`（T3-12），此处不再复述。 */

/**
 * 时间 → 契约要求的 `string | null`。
 *
 * SQLite 档的 `created_at` 是 `YYYY-MM-DD HH:MM:SS` 文本（空格分隔），而契约示例是
 * ISO-8601。这里统一转成 ISO（`T` 分隔 + `Z`）后再输出 —— 否则同一个接口在两种
 * 部署档下会给出两种时间形状，前端得写两套解析。
 */
function toIsoOrNull(value: unknown): string | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.toISOString();
  if (typeof value !== "string" || value.trim() === "") return null;
  const text = value.trim();
  const sqliteShape = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/.exec(text);
  if (sqliteShape) {
    const [, y, mo, d, h, mi, s, ms] = sqliteShape;
    return new Date(
      Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), ms === undefined ? 0 : Number(ms.padEnd(3, "0")))
    ).toISOString();
  }
  const parsed = Date.parse(text);
  return Number.isNaN(parsed) ? null : new Date(parsed).toISOString();
}
