// ---------------------------------------------------------------------------
// RendererServer 单测（M2 · WS3 · T-03/#13）
//
// 覆盖：无后端 → `/` 提供引导页；设置后端 → `/` 提供应用 index；SPA 深链回退；
// 带扩展名的缺失资源 → 404。全部本地起随机端口，无外部依赖。
//
// G-2（V0.4.1）：把 QA 独立探针（`QA-M2-WS3-验收.md` §3/§7）补齐的
// `/redoc` 反代 + SSE 条件化头固化进回归（伪后端 + 真实 RendererServer）。
// ---------------------------------------------------------------------------
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { RendererServer } from "../renderer-server";

async function get(url: string): Promise<{ status: number; body: string }> {
  const response = await fetch(url);
  return { status: response.status, body: await response.text() };
}

/** 伪后端：路径含 `/sse` → `text/event-stream`；含 `/redoc` → HTML；其余 → JSON。 */
async function startFakeBackend(): Promise<{ url: string; close: () => Promise<void> }> {
  const backend = createServer((req, res) => {
    const pathname = (req.url ?? "/").split("?")[0];
    if (pathname.includes("/sse")) {
      // 上游显式声明 `public`：验证反代对 SSE **条件化覆写**为 `no-cache`。
      res.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "public, max-age=60",
      });
      res.write("data: hello\n\n");
      res.end();
      return;
    }
    if (pathname.includes("/redoc")) {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(JSON.stringify({ proxied: "/redoc" }));
      return;
    }
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ proxied: pathname }));
  });
  await new Promise<void>((resolvePromise) => backend.listen(0, "127.0.0.1", resolvePromise));
  const port = (backend.address() as AddressInfo).port;
  return {
    url: `http://127.0.0.1:${port}`,
    close: () =>
      new Promise<void>((resolvePromise) => {
        backend.close(() => resolvePromise());
        backend.closeAllConnections?.();
      }),
  };
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

test("/redoc 反代 200；SSE 条件化头；非 SSE 不加 no-cache（G-2）", async () => {
  const { rendererDir } = scaffold();
  const backend = await startFakeBackend();
  const server = new RendererServer(rendererDir);
  server.setBackendBaseUrl(backend.url);
  const base = await server.start();
  try {
    // 1) `/redoc` 属 PROXY_PREFIXES → 反代到后端（200），不被静态托管接管。
    const redoc = await fetch(`${base}redoc`);
    assert.equal(redoc.status, 200);
    assert.match(await redoc.text(), /"proxied":"\/redoc"/);

    // 2) SSE（text/event-stream）：**经反代前缀 `/api`** 命中后端，条件化追加
    //    「禁缓存 / 禁中间层缓冲」（`/sse` 本身非反代前缀，故走 `/api/sse`）。
    const sse = await fetch(`${base}api/sse`);
    assert.equal(sse.status, 200);
    assert.equal(sse.headers.get("content-type"), "text/event-stream");
    assert.equal(sse.headers.get("cache-control"), "no-cache"); // 覆写上游 public
    assert.equal(sse.headers.get("x-accel-buffering"), "no");
    await sse.text();

    // 3) 非 SSE（application/json）：**不**强加 no-cache（验证「条件化」而非无条件）。
    const json = await fetch(`${base}api/json`);
    assert.equal(json.status, 200);
    assert.equal(json.headers.get("cache-control"), null);
    await json.text();
  } finally {
    await server.stop();
    await backend.close();
  }
});
