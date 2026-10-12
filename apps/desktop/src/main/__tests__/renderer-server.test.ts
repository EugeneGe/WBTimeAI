// ---------------------------------------------------------------------------
// RendererServer 单测（M2 · WS3 · T-03/#13）
//
// 覆盖：无后端 → `/` 提供引导页；设置后端 → `/` 提供应用 index；SPA 深链回退；
// 带扩展名的缺失资源 → 404。全部本地起随机端口，无外部依赖。
// ---------------------------------------------------------------------------
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { RendererServer } from "../renderer-server";

async function get(url: string): Promise<{ status: number; body: string }> {
  const response = await fetch(url);
  return { status: response.status, body: await response.text() };
}

/** 构造 renderer 目录 + 可选引导页，返回路径。 */
function scaffold(): { rendererDir: string; guideFile: string } {
  const root = mkdtempSync(join(tmpdir(), "astra-rs-"));
  const rendererDir = join(root, "renderer");
  mkdirSync(rendererDir, { recursive: true });
  writeFileSync(join(rendererDir, "index.html"), "<html><body>APP-INDEX</body></html>", "utf-8");
  const guideFile = join(root, "guide.html");
  writeFileSync(guideFile, "<html><body>GUIDE-PAGE</body></html>", "utf-8");
  return { rendererDir, guideFile };
}

test("无后端 → / 提供引导页；设置后端后 → / 提供应用 index", async () => {
  const { rendererDir, guideFile } = scaffold();
  const server = new RendererServer(rendererDir, guideFile);
  const base = await server.start();
  try {
    const before = await get(base);
    assert.equal(before.status, 200);
    assert.match(before.body, /GUIDE-PAGE/);

    server.setBackendBaseUrl("http://127.0.0.1:1"); // 非空即视为「有后端」
    const after = await get(base);
    assert.equal(after.status, 200);
    assert.match(after.body, /APP-INDEX/);
  } finally {
    await server.stop();
  }
});

test("无引导页时 / 始终应用 index；深链回退；缺失资源 404", async () => {
  const { rendererDir } = scaffold();
  const server = new RendererServer(rendererDir); // 不传 guide
  const base = await server.start();
  try {
    assert.match((await get(base)).body, /APP-INDEX/);
    // SPA 深链（无扩展名）→ 回退入口，200。
    assert.equal((await get(`${base}projects/123`)).status, 200);
    // 带扩展名的缺失资源 → 404（不得回退为页面）。
    assert.equal((await get(`${base}assets/missing.js`)).status, 404);
  } finally {
    await server.stop();
  }
});
