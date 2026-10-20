// ---------------------------------------------------------------------------
// WBTimeAI · 前端单测 setup（T1-01 / P0-09）
//
// - `@testing-library/jest-dom/vitest`：注册 jest-dom 匹配器（toBeInTheDocument 等）
//   并扩展 vitest 的 `expect`；
// - msw `setupServer`：在 node 测试环境拦截 fetch / XHR，生命周期随测试文件挂钩；
// - RTL `cleanup`：`globals:false` 下 RTL 不会自动注册清理，这里显式挂 `afterEach`。
// ---------------------------------------------------------------------------
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll } from "vitest";

import { handlers } from "./msw-handlers";

export const server = setupServer(...handlers);

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(async () => {
  cleanup();
  server.resetHandlers();
  // vitest 3（2026-10-19，0.4.8 升级）：hook 之间存在 await 微任务窗口，用例内挂起的
  // 异步链（典型：`lib/api.ts` 401 → refresh → `setSession` 置 isAuthenticated=true）
  // 会漏到**下一个用例**的 beforeEach 之后 resolve，绕过其状态复位（实测：
  // SettingsDialog「匿名用户→添加按钮禁用」隔离跑绿、全文件跑红）。
  // 在用例边界排空一轮宏任务，确保残留链在本用例内完结，不跨用例污染状态。
  await new Promise((resolve) => setTimeout(resolve, 0));
});

afterAll(() => {
  server.close();
});
