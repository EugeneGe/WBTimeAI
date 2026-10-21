/**
 * T2-04 · 认证模块的错误载体（**唯一的构造入口**）。
 *
 * 为什么不在各处 `new HttpException(401, …)` 直接写数字（R-14）
 * ------------------------------------------------------------
 * 手写 `401 / 403 / 404 / 423` 是本项目最容易被静默改坏的一类数字：
 * 契约 `contracts/errors.json` 里每个码的 `http_status` 是唯一真源，代码里再抄一份
 * 就等于给自己发了第二份可以漂移的副本。所以本模块**只**经 {@link authError} 造错，
 * 状态一律由 {@link httpStatusOf} 从生成表派生。
 *
 * 为什么用 `HttpException` 而不是 `@wbtime/domain` 的 `DomainError`（R-14）
 * ---------------------------------------------------------------------
 * domain 的 `DomainError.code` 只收 `VALIDATION_ERROR | CONFIGURATION_ERROR` 两个码，
 * 而身份族要抛 `AUTH_INVALID_CREDENTIALS` / `AUTH_ACCOUNT_LOCKED` /
 * `AUTH_TOKEN_EXPIRED` / `AUTH_TOKEN_REVOKED` / `AUTH_TOKEN_INVALID` /
 * `USER_ALREADY_EXISTS` / `UNAUTHORIZED`。扩 domain 码域 = 改公共面（须裁定）；
 * 改用 `apps/api` 已有的 `HttpException(status, code, message, data)` 则天然满足
 * 「码值来自契约、状态来自契约」两条，且被统一错误出口**按实现类优先**识别（③ 分支）。
 *
 * 域层的 `DomainError` 仍然用于**纯域校验**（如口令策略），那条路走 ① 分支、
 * 状态查表（`VALIDATION_ERROR → 422`）—— 两条路互不干扰。
 */

import { ERROR_CODES } from "@wbtime/core";
import type { ErrorCode } from "@wbtime/core";

import { HttpException } from "../../http/error-handler.js";
import { httpStatusOf } from "../../http/status-map.js";

/**
 * 造一个认证错误：状态码由契约生成表派生，调用点只给码。
 *
 * @param code 契约错误码（30 码之一）。
 * @param message 人类可读信息（**不得**含口令 / 令牌 / 密钥明文）。
 * @param data 附加上下文；缺省空对象。
 * @returns 可直接 `throw` 的 `HttpException`。
 */
export function authError(
  code: ErrorCode,
  message: string,
  data: Record<string, unknown> = {}
): HttpException {
  return new HttpException(httpStatusOf(code), code, message, data);
}

/** 凭据无效（401）。文案恒定 —— 不区分"用户不存在"与"口令错"。 */
export function invalidCredentials(): HttpException {
  return authError(ERROR_CODES.AUTH_INVALID_CREDENTIALS, "用户名或密码错误");
}

/** 令牌已过期（401）。 */
export function tokenExpired(): HttpException {
  return authError(ERROR_CODES.AUTH_TOKEN_EXPIRED, "令牌已过期");
}

/** 令牌非法（401）：签名错 / 算法不在白名单 / 缺失必需声明 / 类型不符。 */
export function tokenInvalid(message = "令牌非法"): HttpException {
  return authError(ERROR_CODES.AUTH_TOKEN_INVALID, message);
}

/** 令牌已撤销（401）。 */
export function tokenRevoked(message = "令牌已撤销"): HttpException {
  return authError(ERROR_CODES.AUTH_TOKEN_REVOKED, message);
}

/** 未认证（401）。 */
export function unauthorized(message = "未认证"): HttpException {
  return authError(ERROR_CODES.UNAUTHORIZED, message);
}

/**
 * 注册时的重名 / 重邮箱（`USER_ALREADY_EXISTS`，状态由契约派生）。
 *
 * @param field 冲突字段（`"username"` | `"email"`），写进 `data.field` 供前端定位。
 * @param value 冲突值。**可以回显**：它来自请求体本身，不是服务端查询结果。
 */
export function userAlreadyExists(field: "username" | "email", value: string): HttpException {
  return authError(ERROR_CODES.USER_ALREADY_EXISTS, field === "username" ? "用户名已存在" : "邮箱已存在", {
    field,
    value,
  });
}
