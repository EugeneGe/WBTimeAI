// @wbtime/core · 错误码门面。
//
// 错误码本体在 `./generated/errors.generated.ts`，由 scripts/gen_platform_contracts.mjs
// 从 contracts/errors.json 逐字生成 —— **不手抄、不推导**。本文件只做再导出，
// 不在此处新增任何码值。

export {
  ERROR_CODES,
  ERROR_CODE_LIST,
  ERROR_DESCRIPTIONS,
  ERROR_HTTP_STATUS,
  UNKNOWN_ERROR_CODE,
  httpStatusFor,
} from "./generated/errors.generated.js";
export type { ErrorCode } from "./generated/errors.generated.js";
