// @wbtime/domain · 域错误。
//
// 错误码字面量 **逐字取自** `contracts/errors.json` → `codes[*].code`（实测核对，
// 非手抄推导）。本包刻意 **零运行时依赖**（R1：域层零 ORM / 零 Web import），
// 因此不引 `@wbtime/core`；待 `@wbtime/contracts`（T1-04）产出统一错误码枚举后，
// 此处应改为 re-export 单一真源（已登记为遗留项）。

/** 本域用到的错误码（值必须与 contracts/errors.json 一致）。 */
export const DOMAIN_ERROR_CODES = {
  VALIDATION_ERROR: "VALIDATION_ERROR",
  CONFIGURATION_ERROR: "CONFIGURATION_ERROR",
} as const;

export type DomainErrorCode =
  (typeof DOMAIN_ERROR_CODES)[keyof typeof DOMAIN_ERROR_CODES];

/** 域错误：携带契约错误码 + 结构化 data（沿用旧线 DomainError 的三段形态）。 */
export class DomainError extends Error {
  readonly code: DomainErrorCode;
  readonly data: Readonly<Record<string, unknown>>;

  constructor(message: string, code: DomainErrorCode, data: Record<string, unknown> = {}) {
    super(message);
    this.name = "DomainError";
    this.code = code;
    this.data = Object.freeze({ ...data });
  }
}

/**
 * 断言条件成立，否则抛 VALIDATION_ERROR。
 *
 * 注：刻意 **不用** `asserts condition` 签名 —— 断言签名要求调用目标具备显式类型
 * 标注，跨模块使用时易触发 TS2775；本域的校验不依赖类型收窄。
 */
export function invariant(
  condition: unknown,
  message: string,
  data: Record<string, unknown> = {},
): void {
  if (!condition) {
    throw new DomainError(message, DOMAIN_ERROR_CODES.VALIDATION_ERROR, data);
  }
}
