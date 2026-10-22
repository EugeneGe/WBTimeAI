/**
 * 测试档专用的**布尔列读回兜底**（V0.2.0 审计 #23）。
 *
 * 背景：`is_active` 这类布尔列，PG 档读回**真 boolean**（`true` / `false`），
 * 而 SQLite 档（`node:sqlite` 原生读 / drizzle 之外的裸查询）读回 **integer**
 * （`1` / `0`）。测试代码若直接写 `row.is_active === true`，在 SQLite 裸读回上
 * **静默失败**（恒 false）—— 断言变成永假或「看起来在断言、实际什么都没断」。
 *
 * 为什么只放测试档：生产代码（drizzle 模型层）已把布尔列映射成真 boolean
 * （`tenant-repo.ts` / `auth/service.ts` 的 `=== true` 在两档都正确）；产品行为
 * 不需要兜底，也**不允许**被兜底（`1 === true` 在 JS 是 false，生产语义必须精确）。
 * 本兜底**只**服务于「同一份测试代码要跑双档」的场景：谓词对两档读回值都成立，
 * 断言因此同形。
 *
 * @param value 驱动读回的原始值（PG boolean / SQLite integer）。
 * @returns 语义上的「真」。
 */
export function boolFromDriver(value) {
  return value === true || value === 1;
}
