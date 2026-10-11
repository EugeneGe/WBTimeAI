import { api } from "@/lib/api";
import type {
  CredentialResponse,
  FeatureFlagsResponse,
  PersonalSettingsResponse,
  SaveCredentialRequest,
  SystemSettingsResponse,
  UpdatePersonalSettingsRequest,
} from "@/types";

/**
 * 设置服务（系统 / 个人 / 凭证 / Feature Flag 观测）。
 *
 * 🔴 凭证响应**仅掩码**；明文不落库 / 不回显。
 */
export const settingsService = {
  /** 系统设置（不含密钥）。 */
  system(): Promise<SystemSettingsResponse> {
    return api.get<SystemSettingsResponse>("/settings/system").then((r) => r.data);
  },
  /** 个人设置。 */
  personal(): Promise<PersonalSettingsResponse> {
    return api.get<PersonalSettingsResponse>("/settings/personal").then((r) => r.data);
  },
  /** 更新个人设置（Phase 0 仅 `display_name`）。 */
  updatePersonal(payload: UpdatePersonalSettingsRequest): Promise<PersonalSettingsResponse> {
    return api.put<PersonalSettingsResponse>("/settings/personal", payload).then((r) => r.data);
  },
  /** 保存凭证（API Key；需 `settings:update` 权限，返回**仅掩码**）。 */
  saveCredential(payload: SaveCredentialRequest): Promise<CredentialResponse> {
    return api.post<CredentialResponse>("/settings/credentials", payload).then((r) => r.data);
  },
  /** 凭证列表（**仅掩码**）。 */
  listCredentials(): Promise<CredentialResponse[]> {
    return api.get<CredentialResponse[]>("/settings/credentials").then((r) => r.data);
  },
  /** Feature Flag 观测（只读，验收 §3-#14）。 */
  features(): Promise<FeatureFlagsResponse> {
    return api.get<FeatureFlagsResponse>("/settings/features").then((r) => r.data);
  },
};
