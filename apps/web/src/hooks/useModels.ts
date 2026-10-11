import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { modelService } from "@/services/model";
import { useAuthStore } from "@/stores/authStore";
import type {
  BindCredentialRequest,
  RegisterModelRequest,
  RegisterProviderRequest,
  SaveCredentialRequest,
} from "@/types";

/** 模型提供方列表。 */
export function useProviders() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.providers,
    queryFn: () => modelService.listProviders(),
    enabled: isAuthenticated,
  });
}

/** 某提供方下的模型列表（`providerId` 为空时不请求）。 */
export function useProviderModels(providerId: string | null) {
  return useQuery({
    queryKey: queryKeys.providerModels(providerId ?? ""),
    queryFn: () => modelService.listModels(providerId as string),
    enabled: Boolean(providerId),
  });
}

/** 注册模型提供方 mutation。 */
export function useRegisterProvider() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RegisterProviderRequest) => modelService.registerProvider(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.providers });
    },
  });
}

/** 注册模型 mutation（失效对应提供方的模型目录）。 */
export function useRegisterModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { providerId: string; payload: RegisterModelRequest }) =>
      modelService.registerModel(input.providerId, input.payload),
    onSuccess: (_model, input) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.providerModels(input.providerId),
      });
    },
  });
}

/** 凭证列表（**仅掩码**）。 */
export function useCredentials() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.credentials,
    queryFn: () => modelService.listCredentials(),
    enabled: isAuthenticated,
  });
}

/** 保存凭证 mutation（提交明文仅传输，返回**仅掩码**）。 */
export function useSaveCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SaveCredentialRequest) => modelService.saveCredential(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.credentials });
    },
  });
}

/** 删除凭证 mutation。 */
export function useDeleteCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => modelService.deleteCredential(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.credentials });
    },
  });
}

/** 绑定凭证到提供方 mutation。 */
export function useBindCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { providerId: string; payload: BindCredentialRequest }) =>
      modelService.bindCredential(input.providerId, input.payload),
    onSuccess: (provider) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.providers });
      void queryClient.invalidateQueries({ queryKey: queryKeys.provider(provider.id) });
    },
  });
}

/** 解绑提供方凭证 mutation。 */
export function useUnbindCredential() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (providerId: string) => modelService.unbindCredential(providerId),
    onSuccess: (provider) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.providers });
      void queryClient.invalidateQueries({ queryKey: queryKeys.provider(provider.id) });
    },
  });
}
