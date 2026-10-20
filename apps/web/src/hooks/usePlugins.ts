import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { pluginService } from "@/services/plugin";
import { useAuthStore } from "@/stores/authStore";
import type { InstallPluginRequest } from "@/types";

/**
 * 插件 hooks（TanStack Query；W3 / T2-17；设计 §2.14）。
 *
 * queryKey **内联在本文件**（不扩 `lib/query.ts` 的冻结工厂）：
 * `/plugins` 为**全局**列表，无租户 / 过滤维度，故 key 恒定。
 */

/** 插件列表 query key（安装 / 卸载后统一失效）。 */
export const PLUGINS_QUERY_KEY = ["plugins"] as const;

/** 已装插件列表（`GET /plugins`，全局）。 */
export function usePlugins() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: PLUGINS_QUERY_KEY,
    queryFn: () => pluginService.list(),
    enabled: isAuthenticated,
  });
}

/** 安装插件 mutation（成功后失效列表；409 由调用方展示后端 message）。 */
export function useInstallPlugin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: InstallPluginRequest) => pluginService.install(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
    },
  });
}

/** 卸载插件 mutation（204 幂等；成功后失效列表）。 */
export function useUninstallPlugin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pluginId: string) => pluginService.remove(pluginId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PLUGINS_QUERY_KEY });
    },
  });
}
