// ---------------------------------------------------------------------------
// Astra AI · 前端单测 setup（T1-01 / P0-09）
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

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
