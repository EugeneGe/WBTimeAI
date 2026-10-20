import { api } from "@/lib/api";
import type { InstallPluginRequest, PluginResponse } from "@/types";

/**
 * 插件服务（`/plugins/*` API，W3 / T2-17；设计 §2.14）。
 *
 * - `GET /plugins` → 已装插件列表（**全局**，非租户隔离）；
 * - `POST /plugins` （201）→ 安装；**重名 → 409**（`CONFLICT`）；
 * - `DELETE /plugins/{id}` → **204 无响应体**（幂等：不存在不报错）。
 *
 * 🔴 `204` **无响应体**：删除必须 `.then(() => undefined)`，**不得**读 `r.data`
 *    （响应壳拦截器不会解壳空体，读到的将是 `""`）。
 */
export const pluginService = {
  /** 已装插件列表（全局）。 */
  list(): Promise<PluginResponse[]> {
    return api.get<PluginResponse[]>("/plugins").then((r) => r.data);
  },
  /** 安装插件（重名 → 409）。 */
  install(payload: InstallPluginRequest): Promise<PluginResponse> {
    return api.post<PluginResponse>("/plugins", payload).then((r) => r.data);
  },
  /** 卸载插件（幂等 204，无响应体）。 */
  remove(pluginId: string): Promise<void> {
    return api.delete<void>(`/plugins/${pluginId}`).then(() => undefined);
  },
};
