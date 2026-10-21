// @wbtime/domain · 口令**策略**（纯函数，零运行时依赖）。
//
// 这里放什么 / 不放什么
// --------------------
// **放**：口令的格式与强度判定（长度下/上界、是否可接受），以及"不合格"时的
// 错误形态。它是**域规则**——与用哪种哈希算法、哈希参数取多少无关，也和 HTTP
// 无关，因此可以被注册、改密、管理后台重置三处复用。
//
// **不放**：哈希与校验。`argon2id` 由 `@node-rs/argon2` 这样的**原生模块**提供，
// 本包 `dependencies` 为 `{}` 且要求"能在没有任何原生依赖的机器上被测试"（R1）。
// 一旦在这里 import 原生模块，整个域层就装不起来了 —— 这是本包最硬的一条边界。
// 哈希实现在 `apps/api/src/modules/auth/password.ts`。
//
// 数值口径（不发明）
// ----------------
// 上下界原样继承 py 线 `apps/api/src/wbtime_ai_api/schemas/auth.py` 的
// `RegisterRequest.password = Field(min_length=6, max_length=256)`。
// **没有**复杂度要求（大小写/数字/符号）——py 线没有，本版也不加：
// 加一条就是"同入参不同结果"，直接破 J-11 跨语言等价，而且会把弱口令的责任
// 从"检测泄漏"转移到"为难用户"。

import { DOMAIN_ERROR_CODES, DomainError } from "./errors.js";

/** 口令长度下界（字符数，按 Unicode 码点计）。 */
export const MIN_PASSWORD_LENGTH = 6;

/** 口令长度上界（字符数，按 Unicode 码点计）。 */
export const MAX_PASSWORD_LENGTH = 256;

/**
 * 口令是否满足策略。
 *
 * @param password 明文口令（仅内存中短暂存在）。
 * @returns 满足返回 `true`；非字符串、过短、过长一律 `false`。
 */
export function isAcceptablePassword(password: unknown): boolean {
  if (typeof password !== "string") return false;
  const length = codePointLength(password);
  return length >= MIN_PASSWORD_LENGTH && length <= MAX_PASSWORD_LENGTH;
}

/**
 * 断言口令满足策略，否则抛 `DomainError(VALIDATION_ERROR)`。
 *
 * 返回 `void` 而不是"清洗后的口令"：策略只判不改。任何"顺手 trim / 截断 /
 * 大小写归一"都会让 `hash(注册口令)` 与 `verify(登录口令)` 用上不同的字符串，
 * 表现为"注册成功但永远登不进去"——这类 bug 极难定位，故在类型层就不给机会。
 *
 * @param password 明文口令。
 * @param field 写入错误 `data.field` 的字段名（缺省 `"password"`）。
 * @throws {DomainError} 不满足策略（`VALIDATION_ERROR`，`data = {field, reason, min, max}`）。
 *   `data` **不含口令本身**（错误体会进日志与响应）。
 */
export function assertAcceptablePassword(password: unknown, field = "password"): void {
  if (typeof password !== "string") {
    throw new DomainError("口令必须是字符串", DOMAIN_ERROR_CODES.VALIDATION_ERROR, {
      field,
      reason: "not_a_string",
    });
  }
  const length = codePointLength(password);
  if (length < MIN_PASSWORD_LENGTH) {
    throw new DomainError(
      `口令长度不足：至少 ${MIN_PASSWORD_LENGTH} 个字符`,
      DOMAIN_ERROR_CODES.VALIDATION_ERROR,
      { field, reason: "too_short", min: MIN_PASSWORD_LENGTH, max: MAX_PASSWORD_LENGTH },
    );
  }
  if (length > MAX_PASSWORD_LENGTH) {
    throw new DomainError(
      `口令长度超出：最多 ${MAX_PASSWORD_LENGTH} 个字符`,
      DOMAIN_ERROR_CODES.VALIDATION_ERROR,
      { field, reason: "too_long", min: MIN_PASSWORD_LENGTH, max: MAX_PASSWORD_LENGTH },
    );
  }
}

/**
 * 按 Unicode **码点**计长。
 *
 * 为什么不是 `.length`：Python 的 `len(str)` 计码点，而 JS 的 `.length` 计 UTF-16
 * 编码单元。`"😀😀😀😀😀😀"`（6 个 emoji）在 py 侧是 6（合格），在 JS 侧 `.length`
 * 是 12（也合格），但 3 个 emoji + 3 个 ASCII 就会分叉（py=6 合格 / JS=9 合格），
 * 边界值处必然出现"同入参不同判定"。按码点对齐后两侧一致。
 *
 * @param text 文本。
 * @returns 码点个数。
 */
export function codePointLength(text: string): number {
  let length = 0;
  for (const _ of text) length += 1;
  return length;
}
