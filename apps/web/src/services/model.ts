import { api } from "@/lib/api";
import type {
  BindCredentialRequest,
  CredentialResponse,
  ModelProviderResponse,
  ModelResponse,
  RegisterModelRequest,
  RegisterProviderRequest,
  SaveCredentialRequest,
} from "@/types";

/**
 * Model 服务（`/models/*` API，W7 / T1-34）。
 *
 * - Provider 目录（列表 / 注册 / 详情 / 禁用）；
 * - 模型目录（某 Provider 下）；
 * - 凭证**仅掩码**（C-07）：列表 / 保存（返回掩码）/ 删除 / 绑定；前端**不请求明文**。
 */
export const modelService = {
  /** 模型提供方列表。 */
  listProviders(): Promise<ModelProviderResponse[]> {
    return api.get<ModelProviderResponse[]>("/models/providers").then((r) => r.data);
  },
  /** 注册模型提供方（`credential_id` 仅存引用）。 */
  registerProvider(payload: RegisterProviderRequest): Promise<ModelProviderResponse> {
    return api.post<ModelProviderResponse>("/models/providers", payload).then((r) => r.data);
  },
  /** 模型提供方详情。 */
  getProvider(id: string): Promise<ModelProviderResponse> {
    return api.get<ModelProviderResponse>(`/models/providers/${id}`).then((r) => r.data);
  },
  /** 禁用模型提供方（软删除）。 */
  disableProvider(id: string): Promise<ModelProviderResponse> {
    return api.delete<ModelProviderResponse>(`/models/providers/${id}`).then((r) => r.data);
  },
  /** 某提供方下的模型列表。 */
  listModels(providerId: string): Promise<ModelResponse[]> {
    return api.get<ModelResponse[]>(`/models/providers/${providerId}/models`).then((r) => r.data);
  },
  /** 在某提供方下注册模型。 */
  registerModel(providerId: string, payload: RegisterModelRequest): Promise<ModelResponse> {
    return api
      .post<ModelResponse>(`/models/providers/${providerId}/models`, payload)
      .then((r) => r.data);
  },
  /** 绑定凭证到提供方（仅存引用）。 */
  bindCredential(
    providerId: string,
    payload: BindCredentialRequest,
  ): Promise<ModelProviderResponse> {
    return api
      .post<ModelProviderResponse>(`/models/providers/${providerId}/credential`, payload)
      .then((r) => r.data);
  },
  /** 解绑提供方凭证。 */
  unbindCredential(providerId: string): Promise<ModelProviderResponse> {
    return api
      .delete<ModelProviderResponse>(`/models/providers/${providerId}/credential`)
      .then((r) => r.data);
  },
  /** 凭证列表（**仅掩码**）。 */
  listCredentials(): Promise<CredentialResponse[]> {
    return api.get<CredentialResponse[]>("/models/credentials").then((r) => r.data);
  },
  /** 保存凭证（API Key；提交明文仅传输，返回**仅掩码**）。 */
  saveCredential(payload: SaveCredentialRequest): Promise<CredentialResponse> {
    return api.post<CredentialResponse>("/models/credentials", payload).then((r) => r.data);
  },
  /** 删除凭证（幂等）。 */
  deleteCredential(id: string): Promise<void> {
    return api.delete<void>(`/models/credentials/${id}`).then(() => undefined);
  },
};
