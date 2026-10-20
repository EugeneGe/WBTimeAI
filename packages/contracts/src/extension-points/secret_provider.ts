/**
 * ExtensionPoint ④ `secret_provider`（密钥管理）—— interface 声明（纯类型，无 loader）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/secret_provider.py:23`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/secret_provider.py:27-44`（`SecretProvider` Protocol）
 *
 * 🔴 **命名冲突处置（旧线 C1 / F6）**：本接口 = **key-management**（Vault / KMS 加解密钥匙管理），
 *    与 `wbtime_ai_security.SecretProvider`（= **secret-source**，密钥来源）**同名异义**；
 *    二者命名空间不同、语义正交，**禁止**跨包 re-export / 别名 / 互相继承。
 * 🔴 `master_key()` 返回值**仅供内部加解密使用，不得落日志**（旧线 C-07）。
 * 🔴 本文件**不含**任何运行面。
 */

import type { RotationResult } from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const SECRET_PROVIDER_VERSION = "secret_provider/v1";

/** 密钥管理扩展点（加解密钥匙；非 secret-source）。 */
export interface SecretProvider {
  /** 返回当前主密钥（**不得落日志**）。旧线 `bytes` ⇒ TS `Uint8Array`。 */
  master_key(): Uint8Array;
  /** 使用主密钥加密。 */
  encrypt(plaintext: Uint8Array): Uint8Array;
  /** 使用主密钥解密。 */
  decrypt(ciphertext: Uint8Array): Uint8Array;
  /** 轮换主密钥（须支持中断恢复，旧线 QA-45）。 */
  rotate(): RotationResult;
}
