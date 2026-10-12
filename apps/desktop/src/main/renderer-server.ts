// ---------------------------------------------------------------------------
// 内置渲染服务（M2 · WS3 · T-03 · 设计 §3/§10）
//
// `bundled` 模式下：壳内 Node http 服务托管内置前端产物（`renderer/`），并把
// `/api`、`/health`、`/docs`、`/openapi.json`、`/metrics` **同源反代**到后端。
//
// 🔴 SSE 关键：反代**逐块 flush、不缓冲、不改写**（透传 `text/event-stream`），
//    否则 Chat 流式（`/agents/{id}/run`）会卡死。
// 🔴 同源原则：UI 与 `/api/v1` 同 host:port → 无需改 `apps/web`、无需改后端 CORS。
// ---------------------------------------------------------------------------
import { createReadStream, statSync } from "node:fs";
import {
  createServer,
  request as httpRequest,
  type IncomingMessage,
  type OutgoingHttpHeaders,
  type Server,
  type ServerResponse,
} from "node:http";
import { request as httpsRequest } from "node:https";
import type { AddressInfo } from "node:net";
import { extname, join, resolve, sep } from "node:path";

/** 需反代到后端的路径前缀（其余按静态资源处理）。 */
const PROXY_PREFIXES: readonly string[] = [
  "/api",
  "/health",
  "/docs",
  "/openapi.json",
  "/metrics",
];

/** 逐跳（hop-by-hop）头：反代时需剔除，由 Node 重新计算。 */
const HOP_BY_HOP_HEADERS: readonly string[] = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

/** 扩展名 → MIME（SPA 常见资源）。 */
const MIME_TYPES: Readonly<Record<string, string>> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".txt": "text/plain; charset=utf-8",
  ".wasm": "application/wasm",
};

const INDEX_FILE = "index.html";

/** 路径末段是否含扩展名（用于 SPA 回退判据）。 */
function hasExtension(relativePath: string): boolean {
  const lastSegment = relativePath.replace(/\/+$/, "").split("/").pop() ?? "";
  return lastSegment.includes(".");
}

/** 是否应反代到后端（保留前缀不参与 SPA 回退）。 */
function isProxyPath(pathname: string): boolean {
  return PROXY_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * 内置渲染服务：静态托管 + SPA 回退 + 后端同源反代（含 SSE 不缓冲）。
 */
export class RendererServer {
  private server: Server | null = null;
  private port = 0;
  private backendBaseUrl = "";
  private readonly rendererDir: string;

  /**
   * @param rendererDir 内置前端产物目录（含 `index.html`）。
   */
  constructor(rendererDir: string) {
    this.rendererDir = resolve(rendererDir);
  }

  /** 设置后端基址（`kind=none` 时传空串 → 反代返回 502）。 */
  setBackendBaseUrl(baseUrl: string): void {
    this.backendBaseUrl = baseUrl.trim().replace(/\/+$/, "");
  }

  /**
   * 启动服务（绑定 `127.0.0.1` 上的随机空闲端口）。
   *
   * @returns 渲染层入口 URL（`http://127.0.0.1:<port>/`）。
   */
  async start(): Promise<string> {
    if (this.server) {
      return this.url();
    }
    const server = createServer((req, res) => this.handle(req, res));
    // SSE 长连接：禁用请求超时，避免流式被中间层掐断。
    server.requestTimeout = 0;
    server.headersTimeout = 60_000;

    await new Promise<void>((resolvePromise, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => resolvePromise());
    });

    this.server = server;
    this.port = (server.address() as AddressInfo).port;
    return this.url();
  }

  /** 停止服务（幂等）。 */
  async stop(): Promise<void> {
    const server = this.server;
    this.server = null;
    if (!server) {
      return;
    }
    await new Promise<void>((resolvePromise) => {
      server.close(() => resolvePromise());
      server.closeAllConnections?.();
    });
  }

  private url(): string {
    return `http://127.0.0.1:${this.port}/`;
  }

  private handle(req: IncomingMessage, res: ServerResponse): void {
    const rawUrl = req.url ?? "/";
    const pathname = rawUrl.split("?")[0] ?? "/";
    if (isProxyPath(pathname)) {
      this.proxyToBackend(req, res);
      return;
    }
    this.serveStatic(pathname, res);
  }

  /** 静态托管 + SPA 回退。 */
  private serveStatic(pathname: string, res: ServerResponse): void {
    let relativePath: string;
    try {
      relativePath = decodeURIComponent(pathname).replace(/^\/+/, "");
    } catch {
      this.sendPlain(res, 400, "Bad Request");
      return;
    }

    const target = this.resolveWithin(relativePath);
    if (target !== null && this.isFile(target)) {
      this.sendFile(target, res);
      return;
    }
    if (target !== null && this.isDirectory(target)) {
      const indexTarget = join(target, INDEX_FILE);
      if (this.isFile(indexTarget)) {
        this.sendFile(indexTarget, res);
        return;
      }
    }

    // SPA 回退：导航路径（无扩展名）→ index.html；带扩展名的缺失资源 → 404。
    if (!hasExtension(relativePath)) {
      const indexTarget = join(this.rendererDir, INDEX_FILE);
      if (this.isFile(indexTarget)) {
        this.sendFile(indexTarget, res);
        return;
      }
    }
    this.sendPlain(res, 404, "Not Found");
  }

  /** 解析路径，确保不越出 `rendererDir`（防目录穿越）；越界 / 非法返回 `null`。 */
  private resolveWithin(relativePath: string): string | null {
    const base = this.rendererDir;
    const target = resolve(base, relativePath === "" ? "." : relativePath);
    if (target !== base && !target.startsWith(base + sep)) {
      return null;
    }
    return target;
  }

  private isFile(target: string): boolean {
    try {
      return statSync(target).isFile();
    } catch {
      return false;
    }
  }

  private isDirectory(target: string): boolean {
    try {
      return statSync(target).isDirectory();
    } catch {
      return false;
    }
  }

  private sendFile(filePath: string, res: ServerResponse): void {
    const contentType = MIME_TYPES[extname(filePath).toLowerCase()] ?? "application/octet-stream";
    const stat = statSync(filePath);
    const headers: Record<string, string> = {
      "content-type": contentType,
      "content-length": String(stat.size),
    };
    // 入口 html 不缓存（保证版本更新即时生效）；带哈希资源可长缓存。
    headers["cache-control"] =
      filePath.endsWith(INDEX_FILE) ? "no-cache" : "public, max-age=31536000, immutable";
    res.writeHead(200, headers);
    createReadStream(filePath).pipe(res);
  }

  private sendPlain(res: ServerResponse, statusCode: number, message: string): void {
    res.writeHead(statusCode, { "content-type": "text/plain; charset=utf-8" });
    res.end(message);
  }

  /** 同源反代到后端；**逐块 flush、不缓冲、不改写 body**（SSE 依赖）。 */
  private proxyToBackend(req: IncomingMessage, res: ServerResponse): void {
    if (this.backendBaseUrl === "") {
      res.writeHead(502, { "content-type": "application/json; charset=utf-8" });
      res.end(
        JSON.stringify({
          code: "BACKEND_UNAVAILABLE",
          message: "No backend connected",
          data: {},
          request_id: null,
        }),
      );
      return;
    }

    let upstreamUrl: URL;
    try {
      upstreamUrl = new URL(this.backendBaseUrl);
    } catch {
      this.sendPlain(res, 502, "Bad Gateway");
      return;
    }

    const useHttps = upstreamUrl.protocol === "https:";
    const sender = useHttps ? httpsRequest : httpRequest;
    const headers = { ...req.headers, host: upstreamUrl.host };

    const upstream = sender(
      {
        protocol: upstreamUrl.protocol,
        hostname: upstreamUrl.hostname,
        port: upstreamUrl.port !== "" ? upstreamUrl.port : useHttps ? 443 : 80,
        method: req.method,
        path: req.url,
        headers,
      },
      (upstreamRes) => {
        const responseHeaders: OutgoingHttpHeaders = {};
        for (const [key, value] of Object.entries(upstreamRes.headers)) {
          if (value === undefined) {
            continue;
          }
          if (!HOP_BY_HOP_HEADERS.includes(key.toLowerCase())) {
            responseHeaders[key] = value;
          }
        }
        res.writeHead(upstreamRes.statusCode ?? 502, responseHeaders);
        // 立即下发响应头：SSE（text/event-stream）据此开始逐块推送。
        res.flushHeaders();
        upstreamRes.pipe(res);
      },
    );

    upstream.on("error", () => {
      if (!res.headersSent) {
        res.writeHead(502, { "content-type": "application/json; charset=utf-8" });
        res.end(
          JSON.stringify({
            code: "BACKEND_UNAVAILABLE",
            message: "Backend request failed",
            data: {},
            request_id: null,
          }),
        );
      } else {
        res.end();
      }
    });

    req.pipe(upstream);
  }
}
