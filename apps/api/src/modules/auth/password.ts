/**
 * T2-04 · 口令哈希（argon2id，`@node-rs/argon2` 2.2.2）。
 *
 * 参数原样继承（**不许"调优"**，计划 §3.1）
 * ---------------------------------------
 * `time_cost=3` · `memory_cost=65536`(KiB) · `parallelism=4` · `hash_len=32` ·
 * `salt_len=16`。依据：py 线 `packages/security/src/wbtime_ai_security/password.py`。
 * 改任一个参数都会让 PHC 串里的 `$m=…,t=…,p=…` 变化 —— 跨语言互验（J-2）当场红，
 * 已存量用户的哈希也会集体 `needsRehash`。
 *
 * 三处刻意的实现选择
 * ----------------
 * 1. **显式传 16 字节盐**：`@node-rs/argon2` 的默认盐恰好也是 16 字节，但"默认值"
 *    不是契约。自己生成 16 字节随机盐，`saltLen=16` 才是**代码保证**而不是库的
 *    实现细节；`parseOptions()` 也能在 `needsRehash` 里验证它。
 * 2. **`verify()` 永不抛**：非法哈希串（空 / 被截断 / 别的算法）必须返回 `false`。
 *    抛错会让"口令错"和"库里哈希坏了"在 API 层变成两种响应，前者 401 后者 500 ——
 *    后者等于给攻击者一个"这个账号的哈希是坏的"探针。py 侧同样只返回 bool。
 * 3. **本文件是唯一 import 原生模块的地方**：域层（`@wbtime/domain`）只放纯策略，
 *    它必须能在没有原生二进制的机器上安装与测试（R1）。
 */

import { randomBytes } from "node:crypto";

// `@node-rs/argon2` 把 `Algorithm` / `Version` 声明为 **ambient const enum**，
// 在 `verbatimModuleSyntax` 下**不能**做值访问（TS2748）。因此这里只把它们当**类型**用，
// 具体取值以字面量形式落在下面两个常量上（值来自该包的 d.ts：
// `Argon2id = 2`、`Version.V0x13 = 19`），并让类型系统保证"仍是这两个枚举的成员"。
import type { Algorithm, Version } from "@node-rs/argon2";
import {
  hash as argon2Hash,
  parseOptions,
  verify as argon2Verify,
} from "@node-rs/argon2";

/** `Algorithm.Argon2id` 的取值（= 2）。 */
export const ARGON2ID_ALGORITHM: Algorithm = 2;

/**
 * `Version.V0x13` 的取值（= **1**）。
 *
 * 注意别被名字骗了：该枚举的数值是**版本编号**而不是 PHC 串里的数字 ——
 * `V0x10 = 0`、`V0x13 = 1`，而 PHC 串里对应的是 `$v=19$`（十六进制 0x13）。
 * 用 19 会直接编译不过（TS2322），这正是"别手写魔数"的价值。
 */
export const ARGON2_VERSION: Version = 1;

/** 继承的 argon2id 参数（计划 §3.1；顺序与 py 构造参一致）。 */
export const ARGON2_PARAMS = Object.freeze({
  algorithm: ARGON2ID_ALGORITHM,
  timeCost: 3,
  memoryCost: 65536,
  parallelism: 4,
  outputLen: 32,
});

/** 盐长度（字节）。py `salt_len=16`。 */
export const ARGON2_SALT_LENGTH = 16;

/** PHC 串的前缀断言串：`$argon2id$v=19$m=65536,t=3,p=4$`。 */
export const ARGON2_PHC_PREFIX = "$argon2id$v=19$m=65536,t=3,p=4$";

/**
 * 口令哈希器。
 *
 * 无状态（每次 `hash` 自取随机盐），因此可以安全地作为单例注入。
 */
export class PasswordHasher {
  /**
   * 计算口令哈希（argon2id PHC 串）。
   *
   * @param password 明文口令（仅内存中短暂存在，**不落库 / 不落日志**）。
   * @returns 形如 `$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>` 的字符串。
   */
  hash(password: string): Promise<string> {
    return argon2Hash(password, {
      ...ARGON2_PARAMS,
      salt: randomBytes(ARGON2_SALT_LENGTH),
    });
  }

  /**
   * 校验口令与已存哈希是否匹配。
   *
   * **永不抛**：非法哈希、空哈希、参数不合法一律 `false`（理由见文件头注 2）。
   *
   * @param password 明文口令。
   * @param storedHash 库里的 PHC 串。
   * @returns 匹配 `true`，否则 `false`。
   */
  async verify(password: string, storedHash: string): Promise<boolean> {
    if (typeof password !== "string" || password === "") return false;
    if (typeof storedHash !== "string" || storedHash === "") return false;
    try {
      return await argon2Verify(storedHash, password);
    } catch {
      // 只吞"哈希不可用"这一类；password 的类型问题已在上方前置挡掉。
      return false;
    }
  }

  /**
   * 既有哈希是否应按**当前参数**重算。
   *
   * 对齐 py 的 `PasswordHasher.needs_rehash()`：比较算法、版本、`m`、`t`、`p`、
   * 输出长度、盐长度七项。无法解析的串也算"需要重算"（它已经不可能验证通过，
   * 重算至少能把用户救回来）。
   *
   * @param storedHash 库里的 PHC 串。
   * @returns 需要重算返回 `true`。
   */
  needsRehash(storedHash: string): boolean {
    if (typeof storedHash !== "string" || storedHash === "") return true;
    try {
      const parsed = parseOptions(storedHash);
      return (
        parsed.algorithm !== ARGON2ID_ALGORITHM ||
        parsed.version !== ARGON2_VERSION ||
        parsed.memoryCost !== ARGON2_PARAMS.memoryCost ||
        parsed.timeCost !== ARGON2_PARAMS.timeCost ||
        parsed.parallelism !== ARGON2_PARAMS.parallelism ||
        parsed.outputLen !== ARGON2_PARAMS.outputLen ||
        parsed.saltLen !== ARGON2_SALT_LENGTH
      );
    } catch {
      return true;
    }
  }
}
