/**
 * API DTO 类型（与后端 `/api/v1` 契约对齐，见施工方案 §2T.0.1；响应壳见总纲 §11.1）。
 *
 * 统一响应壳：`{ code, message, data, request_id }`（成功 `code=0`）。
 * `lib/api.ts` 拦截器对成功响应**解壳**（服务层拿到的即业务 DTO）；错误体保留壳形。
 */

/** 统一错误响应体（总纲 §11.1 失败壳）。 */
export interface ApiErrorBody {
  code: string;
  message: string;
  data?: Record<string, unknown>;
  request_id?: string;
}

/** 归一化后的前端错误对象。 */
export interface ApiError {
  code: string;
  message: string;
  data: Record<string, unknown>;
  status?: number;
}

/** 令牌响应。 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** 用户响应（不含敏感字段）。 */
export interface UserResponse {
  id: string;
  tenant_id: string | null;
  username: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string | null;
}

/** 设备会话响应。 */
export interface DeviceResponse {
  id: string;
  device: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

/** 组织响应。 */
export interface OrganizationResponse {
  id: string;
  tenant_id: string | null;
  name: string;
  slug: string;
}

/** 工作区响应。 */
export interface WorkspaceResponse {
  id: string;
  tenant_id: string | null;
  owner_id: string;
  name: string;
  workspace_type: string;
  settings: Record<string, unknown>;
  config: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

/** 凭证响应（**仅掩码**）。 */
export interface CredentialResponse {
  id: string;
  provider: string;
  key_type: string;
  masked_value: string;
  workspace_id: string | null;
  created_at: string | null;
}

/** 系统设置响应（不含密钥）。 */
export interface SystemSettingsResponse {
  mode: string;
  app_name: string;
  app_version: string;
}

/** 个人设置响应。 */
export interface PersonalSettingsResponse {
  user_id: string;
  username: string;
  email: string;
  display_name: string | null;
}

/** Feature Flag 观测响应。 */
export interface FeatureFlagsResponse {
  flags: Record<string, boolean>;
}

/** 简单消息响应。 */
export interface MessageResponse {
  message: string;
}

// -- 请求体 -----------------------------------------------------------------

/** 注册请求。 */
export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  display_name?: string | null;
}

/** 登录请求。 */
export interface LoginRequest {
  username: string;
  password: string;
}

/** 刷新令牌请求。 */
export interface RefreshRequest {
  refresh_token: string;
}

/** 更新本人信息请求。 */
export interface UpdateUserRequest {
  display_name?: string | null;
}

/** 更新个人设置请求。 */
export interface UpdatePersonalSettingsRequest {
  display_name?: string | null;
}

/** 创建工作区请求。 */
export interface CreateWorkspaceRequest {
  name: string;
  workspace_type?: string;
  settings?: Record<string, unknown>;
  config?: Record<string, unknown>;
}

/** 更新工作区设置请求。 */
export interface UpdateWorkspaceSettingsRequest {
  settings: Record<string, unknown>;
}

/** 保存凭证请求（`value` 为明文，仅传输）。 */
export interface SaveCredentialRequest {
  provider: string;
  key_type?: string;
  value: string;
  workspace_id?: string | null;
}
