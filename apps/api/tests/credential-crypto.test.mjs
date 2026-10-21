/**
 * FIX-05 · 凭据静态加密（AES-256-GCM）单测 —— 20xx 审计 #7「`decryptValue` 零调用零测试」。
 *
 * 被测实现：`apps/api/src/modules/credential/crypto.ts`（**本文件不改实现**）。
 *
 * 六项判据（任务书 FIX-05）
 * ------------------------
 * ① 同明文两次加密：密文不同 且 **IV 段不同** —— IV 复用会让 GCM 直接泄漏明文异或值，
 *    这是本文件唯一的红线，故除了「两次不同」还做 100 轮无碰撞统计；
 * ② 加解密往返（含多字节 UTF-8 —— 按 `utf8` 编码、按字节加密，字符边界不该被切坏）；
 * ③ 篡改密文 / GCM tag ⇒ 必须抛错（GCM 认证失败；"能解出乱码"是不可接受的）；
 * ④ 跨密钥解密失败（HKDF 域分离的实际效果）；
 * ⑤ `maskValue` 不泄露明文长度与前缀（掩码宽度恒 4 个 `*`，不随明文长度变化）；
 * ⑥ 非法信封（非 base64 / 段数不足 / 空串 / 版本未知 / IV·tag 长度非法）抛错。
 *
 * 为什么单测就够：本模块是纯函数（无 IO、无时钟、无随机性依赖 — IV 由 `randomBytes` 内部产生），
 * 不需要起进程或连库。加密的唯一外部输入是主密钥，故 ④ 用"另一把密钥"即可复现。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AES_KEY_BYTES,
  ENVELOPE_VERSION,
  GCM_IV_BYTES,
  GCM_TAG_BYTES,
  decryptValue,
  deriveCredentialKey,
  encryptValue,
  maskValue,
} from "../dist/modules/credential/crypto.js";

/** 测试主密钥（≥32 字节；**不是**任何真实部署的密钥）。 */
const SECRET = "wbtime-test-secret-key-0123456789abcdef";

/** 另一把主密钥（用于 ④ 跨密钥解密）。 */
const OTHER_SECRET = "wbtime-test-secret-key-fedcba9876543210";

const KEY = deriveCredentialKey(SECRET);

/** 把一段 base64 的首字节翻转（保证解码后的字节真的变了）。 */
function flipFirstByte(base64) {
  const buffer = Buffer.from(base64, "base64");
  buffer[0] = buffer[0] ^ 0x01;
  return buffer.toString("base64");
}

/** 拆信封（断言语义清晰一点）。 */
function splitEnvelope(envelope) {
  const [version, iv, tag, ciphertext] = envelope.split(":");
  return { version, iv, tag, ciphertext };
}

// ---------------------------------------------------------------------------
// ① IV 绝不复用
// ---------------------------------------------------------------------------

test("① 同明文两次加密：整体密文不同，且 **IV 段必须不同**（IV 复用 = 泄漏明文）", () => {
  const plaintext = "sk-live-0123456789abcdef";
  const first = encryptValue(plaintext, KEY);
  const second = encryptValue(plaintext, KEY);

  assert.equal(typeof first, "string");
  assert.notEqual(first, second, "同一明文两次加密的**整体**结果必须不同");

  const a = splitEnvelope(first);
  const b = splitEnvelope(second);
  assert.equal(a.version, ENVELOPE_VERSION, "首段必须是版本号");
  assert.notEqual(a.iv, b.iv, "IV 段必须不同 —— 复用 IV 会让 GCM 泄漏明文异或值（本文件红线）");

  // IV / tag 的字节长度必须符合 GCM 标准长度（12 / 16），否则 cross-runtime 解密会不稳
  assert.equal(Buffer.from(a.iv, "base64").length, GCM_IV_BYTES);
  assert.equal(Buffer.from(b.iv, "base64").length, GCM_IV_BYTES);
  assert.equal(Buffer.from(a.tag, "base64").length, GCM_TAG_BYTES);

  // IV 不同 ⇒ CTR 流不同 ⇒ 密文段也不可能相同（同明文前提下）
  assert.notEqual(a.ciphertext, b.ciphertext, "IV 不同则密文段必不同");
});

test("① 100 轮同明文加密：IV 无碰撞（不是「碰巧两次不同」）", () => {
  const ivs = new Set();
  const envelopes = new Set();
  for (let index = 0; index < 100; index += 1) {
    const envelope = encryptValue("identical-plaintext", KEY);
    ivs.add(splitEnvelope(envelope).iv);
    envelopes.add(envelope);
  }
  assert.equal(ivs.size, 100, "100 轮必须产生 100 个互不相同的 IV");
  assert.equal(envelopes.size, 100, "100 轮的信封也必须两两不同");
});

// ---------------------------------------------------------------------------
// ② 往返
// ---------------------------------------------------------------------------

test("② 加解密往返正确（普通 / 多字节 UTF-8 / 长串 / 各类符号）", () => {
  const cases = [
    "sk-live-0123456789abcdef",
    "密钥含中文与 emoji 🔐🚀 —— 按 utf8 编码后是 3～4 字节",
    " 前后有空格  ",
    "a".repeat(4096),
    JSON.stringify({ api_key: "sk-1", region: "cn-north" }),
    "\t\n\r: :::",
  ];
  for (const plaintext of cases) {
    const envelope = encryptValue(plaintext, KEY);
    assert.equal(
      decryptValue(envelope, KEY),
      plaintext,
      `往返失败：${JSON.stringify(plaintext).slice(0, 40)}`
    );
  }
});

test("② 派生密钥是 32 字节且确定性（同一主密钥 ⇒ 同一把 AES key）", () => {
  const again = deriveCredentialKey(SECRET);
  assert.equal(again.length, AES_KEY_BYTES);
  assert.ok(again.equals(KEY), "HKDF 必须确定性 —— 否则重启后旧密文全部解不开");
  assert.ok(
    !again.equals(deriveCredentialKey(OTHER_SECRET)),
    "不同主密钥必须派生出不同 AES key（域分离）"
  );
});

// ---------------------------------------------------------------------------
// ③ 篡改 ⇒ 认证失败
// ---------------------------------------------------------------------------

test("③ 篡改密文 ⇒ 抛错（GCM 认证失败，绝不允许解出乱码）", () => {
  const envelope = encryptValue("sk-live-tamper-me", KEY);
  const parts = splitEnvelope(envelope);
  const tampered = [
    ENVELOPE_VERSION,
    parts.iv,
    parts.tag,
    flipFirstByte(parts.ciphertext),
  ].join(":");

  assert.throws(
    () => decryptValue(tampered, KEY),
    (error) => error instanceof Error,
    "篡改密文必须抛错"
  );

  // 用另一条合法密文的密文段替换（长度一致、格式合法）也必须抛错
  const other = splitEnvelope(encryptValue("sk-live-other", KEY));
  const swapped = [ENVELOPE_VERSION, parts.iv, parts.tag, other.ciphertext].join(":");
  assert.throws(() => decryptValue(swapped, KEY), (error) => error instanceof Error);
});

test("③ 篡改 GCM tag ⇒ 抛错；篡改 IV ⇒ 抛错", () => {
  const envelope = encryptValue("sk-live-tamper-tag", KEY);
  const parts = splitEnvelope(envelope);

  const badTag = [ENVELOPE_VERSION, parts.iv, flipFirstByte(parts.tag), parts.ciphertext].join(":");
  assert.throws(() => decryptValue(badTag, KEY), (error) => error instanceof Error, "tag 被改必须抛错");

  const badIv = [ENVELOPE_VERSION, flipFirstByte(parts.iv), parts.tag, parts.ciphertext].join(":");
  assert.throws(() => decryptValue(badIv, KEY), (error) => error instanceof Error, "IV 被改必须抛错");

  // 原信封仍可解（上两条证明的是「改了就炸」，不是「本来就坏」）
  assert.equal(decryptValue(envelope, KEY), "sk-live-tamper-tag");
});

// ---------------------------------------------------------------------------
// ④ 跨密钥
// ---------------------------------------------------------------------------

test("④ 跨密钥解密失败（别的部署 / 别的用途的密钥解不开本部署的密文）", () => {
  const envelope = encryptValue("sk-live-cross-key", KEY);
  const otherKey = deriveCredentialKey(OTHER_SECRET);
  assert.throws(
    () => decryptValue(envelope, otherKey),
    (error) => error instanceof Error,
    "跨密钥必须抛错（不能返回空串或乱码）"
  );
  // 同一把密钥仍可解 —— 证明失败原因是密钥，不是信封
  assert.equal(decryptValue(envelope, KEY), "sk-live-cross-key");
});

// ---------------------------------------------------------------------------
// ⑤ 掩码
// ---------------------------------------------------------------------------

test("⑤ maskValue 不泄露明文长度：>4 位时输出长度恒为 8，且 `*` 恒为 4 个", () => {
  const lengths = [];
  const starCounts = new Set();
  for (let length = 5; length <= 64; length += 1) {
    const masked = maskValue("k".repeat(length));
    lengths.push(masked.length);
    starCounts.add((masked.match(/\*/g) ?? []).length);
  }
  assert.deepEqual(
    [...new Set(lengths)],
    [8],
    "5..64 位明文的掩码长度必须恒为 8 —— 否则掩码长度就把真实长度泄露出去了"
  );
  assert.deepEqual([...starCounts], [4], "`*` 个数必须恒为 4（不按明文长度铺）");
});

test("⑤ maskValue 只回显末 4 位，绝不回显前缀", () => {
  const plaintext = "sk-live-AAAABBBBCCCC1111";
  const masked = maskValue(plaintext);
  assert.equal(masked, "****1111", "只保留末 4 位");
  assert.equal(masked.startsWith("****"), true);
  const prefix = plaintext.slice(0, plaintext.length - 4);
  assert.equal(masked.includes(prefix), false, "前缀一个字符都不许回显");
  assert.equal(masked.includes("sk-live"), false, "供应商前缀也不许回显");
  for (const character of plaintext.slice(0, plaintext.length - 4)) {
    assert.equal(masked.includes(character), false, `明文前段字符 ${character} 不该出现在掩码里`);
  }
});

test("⑤ maskValue 短明文（≤4 位）全掩码，且不暴露长度/内容", () => {
  for (const plaintext of ["", "a", "ab", "abc", "abcd"]) {
    assert.equal(maskValue(plaintext), "****", `${JSON.stringify(plaintext)} 必须全掩码`);
  }
  // 4 位明文的内容不得出现在掩码里（用与 `*` 不冲突的字符集验证）
  const masked = maskValue("z9x8");
  for (const character of "z9x8") {
    assert.equal(masked.includes(character), false);
  }
  // 非字符串入参按空处理（防御性：宁可显示 `****`，也不能抛错把整条列表请求打挂）
  assert.equal(maskValue(undefined), "****");
  assert.equal(maskValue(null), "****");
});

// ---------------------------------------------------------------------------
// ⑥ 非法信封
// ---------------------------------------------------------------------------

test("⑥ 非法信封（空串 / 段数不足 / 段数过多 / 版本未知）一律抛错", () => {
  const valid = encryptValue("sk-live-envelope", KEY);
  const parts = splitEnvelope(valid);

  const invalid = [
    ["空串", ""],
    ["仅版本号", ENVELOPE_VERSION],
    ["段数 2", `${ENVELOPE_VERSION}:${parts.iv}`],
    ["段数 3", `${ENVELOPE_VERSION}:${parts.iv}:${parts.tag}`],
    ["段数 5", `${valid}:extra`],
    ["版本未知", ["v2", parts.iv, parts.tag, parts.ciphertext].join(":")],
    ["版本为大写", ["V1", parts.iv, parts.tag, parts.ciphertext].join(":")],
  ];
  for (const [label, envelope] of invalid) {
    assert.throws(
      () => decryptValue(envelope, KEY),
      (error) => error instanceof Error,
      `${label} 必须抛错`
    );
  }
});

test("⑥ 非法信封（非 base64 / IV·tag 长度非法 / 非字符串）一律抛错", () => {
  const valid = encryptValue("sk-live-envelope", KEY);
  const parts = splitEnvelope(valid);

  const notBase64 = `${ENVELOPE_VERSION}:!!!!:!!!!:!!!!`;
  assert.throws(() => decryptValue(notBase64, KEY), (error) => error instanceof Error);

  const shortIv = [
    ENVELOPE_VERSION,
    Buffer.alloc(GCM_IV_BYTES - 1).toString("base64"),
    parts.tag,
    parts.ciphertext,
  ].join(":");
  assert.throws(() => decryptValue(shortIv, KEY), (error) => error instanceof Error);

  const shortTag = [
    ENVELOPE_VERSION,
    parts.iv,
    Buffer.alloc(GCM_TAG_BYTES - 1).toString("base64"),
    parts.ciphertext,
  ].join(":");
  assert.throws(() => decryptValue(shortTag, KEY), (error) => error instanceof Error);

  // 非字符串入参：`encryptValue` 侧同样要拒绝空明文
  assert.throws(() => decryptValue(undefined, KEY), (error) => error instanceof Error);
  assert.throws(() => decryptValue(null, KEY), (error) => error instanceof Error);
  assert.throws(() => encryptValue("", KEY), (error) => error instanceof TypeError);
});
