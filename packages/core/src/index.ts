// @wbtime/core —— 平台基座最底层：错误码 / 响应壳 / Result。
// 分层：本包不得依赖任何 @wbtime/* 包，也不得依赖运行时（Electron / 浏览器 API）。

export * from "./errors.js";
export * from "./envelope.js";
export * from "./result.js";
