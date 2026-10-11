// ---------------------------------------------------------------------------
// Astra AI · 前端单测配置（vitest）
//
// 落点（P0-09 / T1-01）：`apps/web` 引入 vitest + @testing-library/react + msw，
// 使 §3-#17/#26「前端可证」可判定，`pnpm --filter @astra/web test` 入 CI 必绿。
//
// - `environment: jsdom`：浏览器 DOM 语义；
// - `setupFiles`：注册 RTL/jest-dom 与 msw server 生命周期；
// - `resolve.alias`：与 `vite.config.ts` 的 `@` 别名保持一致。
// ---------------------------------------------------------------------------
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
