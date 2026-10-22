/**
 * T3-12 · 模型族视图（**契约响应形状的单一真相源**）。
 *
 * 为什么单独一个文件：`ModelProviderResponse` 的映射原本只存在于
 * `modules/credential/service.ts`（T2-07 的 4 个 op 用），而 T3-12 的 6 个新 op
 * （provider 目录 4 + model 目录 2）**用同一个形状**。若在 provider 服务里再写一份，
 * 两边会各自漂移 —— 契约键集合是逐字判据（`routes-invariants` / 对齐守卫都比对），
 * 一次漏键就是一条红灯。故在此抽成单一实现，两处 import。
 *
 * 两个"恒 null"的字段（**不是遗漏，是表结构决定**）
 * -------------------------------------------------
 *   - `ModelProviderResponse.created_at`：`model_provider` 表**没有 `created_at` 列**
 *     （实测列：id/tenant_id/organization_id/workspace_id/name/type/endpoint/
 *     credential_id/status/config）⇒ 恒 `null`，不为此改 DDL（J-1 红线）。
 *   - `ModelResponse.tenant_id` / `created_at`：`model` 表同样**没有**这两列
 *     （实测列：id/provider_id/name/type/context_window/capabilities/status）。
 *     py 侧的 `tenant_id` 取 `getattr(entity, "tenant_id", None)` 恒 `None`；
 *     `created_at` 取的是**内存实体构造时刻**而非库值 —— TS 不臆造，恒 `null`。
 *     登记为已知差异（见施工记录偏差表）。
 */

import type { ModelProviderRow, ModelRow } from "@wbtime/db";

import { toIsoOrNull } from "../agent/versioning.js";

/** 对外供应商视图（契约 `ModelProviderResponse`，10 键逐字对齐）。 */
export interface ModelProviderView {
  readonly id: string;
  readonly name: string;
  readonly type: string;
  readonly endpoint: string | null;
  readonly credential_id: string | null;
  readonly status: string;
  readonly config: Record<string, unknown>;
  readonly created_at: string | null;
  readonly tenant_id: string | null;
  readonly workspace_id: string | null;
}

/** 对外模型视图（契约 `ModelResponse`，9 键逐字对齐）。 */
export interface ModelView {
  readonly id: string;
  readonly tenant_id: string | null;
  readonly provider_id: string;
  readonly name: string;
  readonly type: string;
  readonly context_window: number | null;
  readonly capabilities: Record<string, unknown>;
  readonly status: string;
  readonly created_at: string | null;
}

/** 行 → 契约视图（`credential_id` **仅引用**，无密文 / 明文）。 */
export function toProviderView(row: ModelProviderRow): ModelProviderView {
  return {
    id: row.id,
    name: row.name,
    type: row.type,
    endpoint: row.endpoint ?? null,
    credential_id: row.credential_id ?? null,
    status: row.status,
    config: (row.config ?? {}) as Record<string, unknown>,
    // `model_provider` 没有 `created_at` 列 ⇒ 恒 null（见文件头注）。
    created_at: null,
    tenant_id: row.tenant_id ?? null,
    workspace_id: row.workspace_id ?? null,
  };
}

/** 行 → 契约视图。`capabilities` 列可空但契约是 `object` ⇒ 回落 `{}`（py `dict(... or {})`）。 */
export function toModelView(row: ModelRow): ModelView {
  return {
    id: row.id,
    // `model` 表无 `tenant_id` 列 ⇒ 恒 null（见文件头注，py 同形）。
    tenant_id: null,
    provider_id: row.provider_id,
    name: row.name,
    type: row.type,
    context_window: row.context_window ?? null,
    capabilities: (row.capabilities ?? {}) as Record<string, unknown>,
    status: row.status,
    // `model` 表无 `created_at` 列 ⇒ 恒 null（见文件头注）。
    created_at: toIsoOrNull(null),
  };
}
