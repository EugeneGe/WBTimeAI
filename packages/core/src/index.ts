// @wbtime/core —— 平台基座最底层：错误码 / 响应壳 / Result。
// 分层：本包不得依赖任何 @wbtime/* 包，也不得依赖运行时（Electron / 浏览器 API）。
//
// V0.2.0（T2-02）新增的公共面由下面两条 `export *` 自动透出，无需在此逐条重复
// 声明（重复声明会与 `export *` 撞成 duplicate export）：
//   * `./errors.js`      → `dependencyMissing()` / `DependencyMissingError` /
//                          `DependencyMissingStatus` / `DEPENDENCY_MISSING_CODE`
//   * `./envelope.js`    → `isSuccessShell()` / `isErrorShell()`（值判定，中间件幂等闸门）
// 导出面断言见 `apps/api/tests/errors-contract.test.mjs` 与
// `apps/api/tests/envelope-contract.test.mjs`（运行时 import 后逐项判 typeof）。

export * from "./errors.js";
export * from "./envelope.js";
export * from "./result.js";
