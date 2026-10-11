import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { organizationService } from "@/services/organization";
import { settingsService } from "@/services/settings";
import { useAuthStore } from "@/stores/authStore";
import type { SaveCredentialRequest, UpdatePersonalSettingsRequest } from "@/types";

/** 系统设置（不含密钥）。 */
export function useSystemSettings() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.system,
    queryFn: () => settingsService.system(),
    enabled: isAuthenticated,
  });
}

/** 个人设置。 */
export function usePersonalSettings() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.personal,
    queryFn: () => settingsService.personal(),
    enabled: isAuthenticated,
  });
}

/** 更新个人设置 mutation。 */
export function useUpdatePersonalSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdatePersonalSettingsRequest) => settingsService.updatePersonal(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.personal });
      void queryClient.invalidateQueries({ queryKey: queryKeys.me });
    },
  });
}

/** 凭证列表（**仅掩码**）。 */
export function useCredentials() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.credentials,
    queryFn: () => settingsService.listCredentials(),
    enabled: isAuthenticated,
  });
}

/** 保存凭证 mutation（**仅掩码**返回）。 */
export function useSaveCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SaveCredentialRequest) => settingsService.saveCredential(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.credentials });
    },
  });
}

/** Feature Flag 观测（只读）。 */
export function useFeatureFlags() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.features,
    queryFn: () => settingsService.features(),
    enabled: isAuthenticated,
  });
}

/** 组织列表（Phase 0 最小）。 */
export function useOrganizations() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.organizations,
    queryFn: () => organizationService.list(),
    enabled: isAuthenticated,
  });
}
