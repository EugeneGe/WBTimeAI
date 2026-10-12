#!/usr/bin/env node
// ---------------------------------------------------------------------------
// 构建期：把前端产物 apps/web/dist 同步到 apps/desktop/renderer/（M2 · WS3）
//
// - `RendererServer` 在 `bundled` 模式下托管本目录（内置 UI，不依赖 WS2）。
// - 该目录**不入库**（见 apps/desktop/.gitignore）。
// - 幂等：先清理目标目录再整树拷贝。
//
// 用法： node scripts/sync-renderer.mjs
// ---------------------------------------------------------------------------
import { access, cp, mkdir, rm } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(here, "..");
const sourceDir = resolve(desktopDir, "..", "web", "dist");
const targetDir = resolve(desktopDir, "renderer");

/**
 * 校验前端产物存在（含 index.html 入口），否则给出可操作的提示并退出。
 */
async function assertSourceReady() {
  try {
    await access(resolve(sourceDir, "index.html"), constants.R_OK);
  } catch {
    console.error(`[sync-renderer] 未找到前端产物：${sourceDir}`);
    console.error("[sync-renderer] 请先构建前端：pnpm --filter @astra/web build");
    process.exit(1);
  }
}

async function main() {
  await assertSourceReady();
  await rm(targetDir, { recursive: true, force: true });
  await mkdir(targetDir, { recursive: true });
  await cp(sourceDir, targetDir, { recursive: true });
  console.log(`[sync-renderer] 已同步前端产物：${sourceDir} -> ${targetDir}`);
}

main().catch((error) => {
  console.error("[sync-renderer] 同步失败：", error);
  process.exit(1);
});
