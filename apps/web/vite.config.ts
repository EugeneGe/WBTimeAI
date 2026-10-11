import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

// 开发期跨域策略（定稿，§2T.0.1）：采用 **Vite proxy**，把 `/api` 代理到后端
// `http://127.0.0.1:8080`（前端请求同源，无需后端 CORS）。
// 后端 `ASTRA_CORS_ORIGINS` 默认含 `http://localhost:5173`，作为「直连后端」时的兜底。
// 容器编排（docker compose）下可经 `VITE_PROXY_TARGET` 指向 `http://api:8080`。
const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
