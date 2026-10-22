/**
 * T3-13 · `redactSensitive` —— 与检测**同源**的纯脱敏函数（R3-16 已拍板）。
 *
 * 本文件是**转发壳**：真正的实现在 `rule-registry.ts`（同一注册表、同一批正则、
 * 同一个 `detectSensitive` 调用）。拆成独立文件只是为了让 `index.ts` 的出口形状
 * 与 `scan_sensitive` 并列（M-04 的既有出口不动，R16 的新出口在这里）。
 *
 * 契约（R3-16 影响判据 ③ 的断言面）：
 *   同一段文本、同一组选项 ⇒ `detectSensitive(text).hits` 与
 *   `redactSensitive(text).hits` **完全相等**（id + start + end 逐项一致）。
 *   `safety-redact.test.mjs` 用凭据 + PII 两类 fixture 各断一条。
 */

export { redactSensitive, type RedactResult } from "./rule-registry.js";
