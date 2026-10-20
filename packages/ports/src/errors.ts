// @wbtime/ports · 端口层错误。
//
// 错误码 **实测取自** `contracts/errors.json` → `codes.CONFIGURATION_ERROR`：
//   - `code` = "CONFIGURATION_ERROR"（enum_index 9）
//   - `description` = "配置非法或缺失。"
//   - `http_status` = 422
// 本包 **零运行时依赖**（不得引入 Redis / BullMQ / arq 等真实队列依赖），
// 故此处内联该码；待 `@wbtime/contracts`（T1-04）产出统一枚举后改为 re-export。

export const PORTS_ERROR_CODES = {
  CONFIGURATION_ERROR: "CONFIGURATION_ERROR",
} as const;

export type PortsErrorCode = (typeof PORTS_ERROR_CODES)[keyof typeof PORTS_ERROR_CODES];

/** `CONFIGURATION_ERROR` 的 HTTP 状态（实测 contracts/errors.json: http_status）。 */
export const CONFIGURATION_ERROR_HTTP_STATUS = 422;

/**
 * 端口能力未启用错误。
 *
 * 语义（对齐旧线 `_UnsupportedBase._raise`）：**接口齐备、应用可启动**，
 * 但**首次调用即抛**，绝不静默返回 `undefined` / 空成功。
 */
export class PortsNotEnabledError extends Error {
  readonly code: PortsErrorCode = PORTS_ERROR_CODES.CONFIGURATION_ERROR;
  readonly httpStatus: number = CONFIGURATION_ERROR_HTTP_STATUS;
  readonly data: Readonly<Record<string, unknown>>;

  constructor(operation: string, feature: string, availableIn: string) {
    super(
      `能力「${feature}」在 V0.1.0 未启用（真实实现目标版本：${availableIn}）；当前调用：${operation}。`,
    );
    this.name = "PortsNotEnabledError";
    this.data = Object.freeze({ feature, availableIn, operation });
  }
}
