/**
 * T2-07 · 凭据**静态加密**（AES-256-GCM）。
 *
 * 为什么必须加密（计划 §7.1-2 红线）
 * --------------------------------
 * `credential.encrypted_value` 是**唯一**存放凭据明文的落点。若明文入库，
 * 一次库文件泄漏（备份、快照、误上传）就等于把所有供应商 API key 交给对方，
 * 而且没有"事后补救"—— 只能全部吊销重发。故本版起就是密文落库。
 *
 * 三个实现决策（本版自定，已登记在施工记录）
 * ----------------------------------------
 * 1. **密钥派生**：`HKDF-SHA256(WBTIME_AI_SECRET_KEY)`，`salt`/`info` 固定为
 *    `"wbtime-ai/credential"` / `"aes-256-gcm"`。不用裸密钥直接当 AES key：
 *    JWT 用的是同一把 secret 的 HMAC 语义，直接复用会把"签名密钥"和"加密密钥"
 *    变成同一个值（一处泄漏同时毁掉两件事）。HKDF 让两者在密码学上独立。
 * 2. **信封格式** `v1:<iv_b64>:<tag_b64>:<ciphertext_b64>`：首段是版本号，将来轮换算法
 *    时可以按前缀分派解密，而不是"发现解不开就猜"。IV 12 字节（GCM 标准长度），
 *    tag 16 字节，每次加密独立随机 IV —— **绝不复用 IV**（GCM 复用 IV 会直接泄漏明文异或值）。
 * 3. **AAD 绑定用途**：`setAAD("wbtime-ai.credential.v1")`。这样同一把密钥将来若被用于
 *    别的用途，密文不会互相"可通用"。
 */

import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from "node:crypto";

/** 信封版本前缀。 */
export const ENVELOPE_VERSION = "v1";

/** GCM 的 IV 长度（字节，NIST 推荐 96 bit）。 */
export const GCM_IV_BYTES = 12;

/** GCM 认证标签长度（字节）。 */
export const GCM_TAG_BYTES = 16;

/** AES 密钥长度（字节）。 */
export const AES_KEY_BYTES = 32;

/** HKDF 的固定 salt（与密钥轮换无关，只用于域分离）。 */
const HKDF_SALT = "wbtime-ai/credential";

/** HKDF 的 info（用途标签）。 */
const HKDF_INFO = "aes-256-gcm";

/** 附加认证数据（绑定"这把密文是凭据"这一事实）。 */
const AAD = Buffer.from("wbtime-ai.credential.v1", "utf8");

/**
 * 从主密钥派生凭据加密密钥（32 字节）。
 *
 * @param secretKey `WBTIME_AI_SECRET_KEY`（≥32 UTF-8 字节，长度由装配入口把关）。
 * @returns 32 字节 AES-256 密钥。
 * @throws {TypeError} 密钥为空。
 */
export function deriveCredentialKey(secretKey: string): Buffer {
  if (typeof secretKey !== "string" || secretKey === "") {
    throw new TypeError("deriveCredentialKey：secretKey 必须非空");
  }
  const derived = hkdfSync("sha256", Buffer.from(secretKey, "utf8"), Buffer.from(HKDF_SALT, "utf8"), Buffer.from(HKDF_INFO, "utf8"), AES_KEY_BYTES);
  return Buffer.from(derived);
}

/**
 * 加密一个凭据明文。
 *
 * @param plaintext 明文（**只在内存里与响应掩码中出现**）。
 * @param key {@link deriveCredentialKey} 的产物。
 * @returns `v1:<iv_b64>:<tag_b64>:<ciphertext_b64>`。
 */
export function encryptValue(plaintext: string, key: Buffer): string {
  if (typeof plaintext !== "string" || plaintext === "") {
    throw new TypeError("encryptValue：凭据明文必须非空");
  }
  const iv = randomBytes(GCM_IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(AAD);
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return [ENVELOPE_VERSION, iv.toString("base64"), tag.toString("base64"), ciphertext.toString("base64")].join(":");
}

/**
 * 解密。
 *
 * @param envelope {@link encryptValue} 的产物。
 * @param key 同一把派生密钥。
 * @returns 明文。
 * @throws {Error} 版本未知、格式非法、密钥不匹配或密文被篡改（GCM 认证失败）。
 */
export function decryptValue(envelope: string, key: Buffer): string {
  const parts = typeof envelope === "string" ? envelope.split(":") : [];
  if (parts.length !== 4 || parts[0] !== ENVELOPE_VERSION) {
    throw new Error("凭据信封格式非法（期望 v1:<iv>:<tag>:<ciphertext>）");
  }
  const iv = Buffer.from(parts[1], "base64");
  const tag = Buffer.from(parts[2], "base64");
  const ciphertext = Buffer.from(parts[3], "base64");
  if (iv.length !== GCM_IV_BYTES || tag.length !== GCM_TAG_BYTES) {
    throw new Error("凭据信封的 IV / tag 长度非法");
  }
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAAD(AAD);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
}

/**
 * 生成对外展示的掩码（契约 `CredentialResponse.masked_value`）。
 *
 * 规则：保留**末 4 位**，其余以 `*` 代替；长度 ≤ 4 时全掩码。
 * 保留末 4 位是行业惯例（够用户认出是哪把 key，不足以还原）。**不回显长度**：
 * 用固定 4 个 `*` 而不是按长度铺 `*`，避免把"密钥多长"这种本可不泄漏的信息带出去。
 *
 * @param plaintext 明文。
 * @returns 形如 `****ab12`。
 */
export function maskValue(plaintext: string): string {
  const text = typeof plaintext === "string" ? plaintext : "";
  if (text.length <= 4) return "****";
  return `****${text.slice(-4)}`;
}
