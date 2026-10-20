/**
 * ExtensionPoint ① `auth_provider`（认证提供者）—— interface 声明（纯类型，无 loader）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/auth_provider.py:20`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/auth_provider.py:24-37`（`AuthProvider` Protocol）
 *
 * 🔴 成员名沿用旧线 snake_case —— ABI 保真优先于 TS 命名风格（V0.7.0 是插件 ABI 唯一窗口）。
 * 🔴 本文件**不含**任何运行面：无 loader / 无注册 / 无签名校验（归 V0.7.0）。
 */

import type { AuthCredential, ExtensionContext, Principal } from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const AUTH_PROVIDER_VERSION = "auth_provider/v1";

/** 认证提供者扩展点（外部身份源 → 平台 `Principal`）。 */
export interface AuthProvider {
  /** 是否支持给定认证方案（如 `local` / `oidc` / `saml`）。 */
  supports(scheme: string): boolean;
  /** 校验凭证并返回主体；失败抛 `DomainError(UNAUTHORIZED)`。 */
  authenticate(credential: AuthCredential, ctx: ExtensionContext): Principal;
  /** 登出（撤销会话 / 令牌）；幂等。 */
  logout(principal: Principal): void;
}
