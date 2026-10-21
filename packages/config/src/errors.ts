// @wbtime/config · 配置层错误类型。
//
// 为什么单独成文件（而不是留在 config.ts 里）
// ------------------------------------------
// `env.ts` 的取值原语（`envAsInt` / `envAsBool`）遇到非法值时也必须抛
// `ConfigError`：否则启动期会同时存在 `TypeError` 与 `ConfigError` 两套错误形态，
// 调用方（启动器 / CLI）无法统一按 `code` 判态，只能写 `instanceof` 双分支。
// 但 `config.ts` 已经 import `env.ts`，若 `env.ts` 反过来从 `config.ts` 取
// `ConfigError` 就构成循环依赖（ESM 下"有时能跑"、打包器换一种解析顺序就炸）。
// 因此把错误类型下沉到本文件：方向变成
//
//   env.ts ──┐
//            ├──▶ errors.ts ──▶ @wbtime/core
//   config.ts┘
//
// 单向无环，且 `config.ts` 通过 re-export 保证公共导出面不变。

import { ERROR_CODES, httpStatusFor } from "@wbtime/core";
import type { ErrorCode } from "@wbtime/core";

/** 配置缺失 / 非法。错误码与 HTTP 状态均来自 contracts/errors.json。 */
export class ConfigError extends Error {
  readonly name = "ConfigError";
  readonly code: ErrorCode = ERROR_CODES.CONFIGURATION_ERROR;
  /** 缺失的环境变量键（可能是多个，一次性报全，逐个补太慢）。 */
  readonly missingKeys: readonly string[];

  constructor(message: string, missingKeys: readonly string[] = []) {
    super(message);
    this.missingKeys = missingKeys;
  }

  /** 该错误对应的 HTTP 状态码（契约：CONFIGURATION_ERROR → 422）。 */
  get httpStatus(): number {
    return httpStatusFor(this.code);
  }
}
