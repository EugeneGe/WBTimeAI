/**
 * 插件 DTO（`/plugins` API，W3 / T2-17；设计 §2.14 / §2.12）。
 *
 * 契约对齐后端 `wbtime_ai_api.schemas.plugin`（**逐字** snake_case）：
 *
 * - `GET /plugins` → `PluginResponse[]`（**全局**，非租户隔离）；
 * - `POST /plugins` （201）body `InstallPluginRequest`；重名 → **409**；
 * - `DELETE /plugins/{id}` → **204 无响应体**（幂等）。
 *
 * ⚠️ `core_compat`（设计稿列的「兼容内核版本」列）**不在** `PluginResponse` 顶层字段里，
 *    只能从 `manifest.core_compat` 读取（见 `components/settings/PluginSection.tsx`）。
 */

/**
 * 已知插件状态取值（后端 `status` 为**自由字符串**，缺省 `"installed"`）。
 *
 * 其余取值（如第三方自定义态）按原样展示，**不视为错误**。
 */
export type PluginStatus = "installed" | "degraded" | "disabled" | "failed";

/** 「正常」状态字面值（后端 `PLUGIN_STATUS_INSTALLED`）。 */
export const PLUGIN_STATUS_INSTALLED = "installed";

/** 已装插件响应。 */
export interface PluginResponse {
  /** 插件标识。 */
  id: string;
  /** 插件名（**全局唯一**：重名安装返回 409）。 */
  name: string;
  /** 版本号。 */
  version: string;
  /** 种类（`connector` / `tool` / ...，后端为自由字符串）。 */
  kind: string;
  /** 入口点（可空）。 */
  entry_point: string | null;
  /** 声明权限。 */
  permissions: string[];
  /** 插件清单（扩展字段，如 `core_compat` / `status_reason`）。 */
  manifest: Record<string, unknown>;
  /** 状态（缺省 `installed`；非 `installed` 在 UI 上降级为琥珀 warn tag）。 */
  status: string;
  /** 安装时间（ISO8601；可空）。 */
  installed_at: string | null;
}

/** 安装插件请求（对齐后端 `InstallPluginRequest` 字段约束）。 */
export interface InstallPluginRequest {
  /** 插件名（必填，1–150 字符，全局唯一）。 */
  name: string;
  /** 版本（必填，1–50 字符）。 */
  version: string;
  /** 种类（必填，1–50 字符，如 `connector` / `tool`）。 */
  kind: string;
  /** 入口点（可选，≤255 字符）。 */
  entry_point?: string | null;
  /** 声明权限（可选，缺省空数组）。 */
  permissions?: string[];
  /** 插件清单（可选，缺省空对象）。 */
  manifest?: Record<string, unknown>;
}
