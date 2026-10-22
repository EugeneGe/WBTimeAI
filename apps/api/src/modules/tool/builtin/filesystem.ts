/**
 * T3-10 · `filesystem` 工具（read / list / write / delete，**限定在 Workspace 内**）。
 *
 * 四条动作与它们各自的校验
 * ----------------------
 * | action | 校验 | 越界结果 |
 * |---|---|---|
 * | `read` | 路径在 workspace 内 + 存在 | `DENIED` / `VALIDATION_ERROR` |
 * | `list` | 同上（目录） | 同上 |
 * | `write` | 路径在 workspace 内（**不要求存在**） | `DENIED` |
 * | `delete` | 同上 + 存在 | 同上 |
 *
 * 所有路径都经 `resolveWithinWorkspace` —— **没有第二条路径解析**。这是 `path-escape`
 * 那一层的唯一调用点：任何"顺手用 `path.join` 拼一下"的写法都会绕开符号链接展开，
 * 而符号链接正是最容易被漏掉的越界形态。
 *
 * `encoding`：只支持 `utf8`（缺省）/ `base64`（读时编码输出、写时解码输入）。
 * 其他值 ⇒ `VALIDATION_ERROR`（**不静默按 utf8 处理** —— 那会让二进制文件被写坏）。
 */

import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { PathGuardError, resolveWithinWorkspace } from "../guards/path-escape.js";
import type { BuiltinTool, ToolContext, ToolOutcome } from "../registry.js";

/** 支持的编码（`encoding` 入参的值域）。 */
const SUPPORTED_ENCODINGS = new Set(["utf8", "base64"]);

/** 单个文件读写的上限（防止一次读进几个 GB）。 */
const MAX_FILE_BYTES = 8 * 1024 * 1024;

export const filesystemTool: BuiltinTool = {
  name: "filesystem",
  requiresSandbox: false,

  async execute(args: Readonly<Record<string, unknown>>, context: ToolContext): Promise<ToolOutcome> {
    const startedAt = Date.now();
    const action = String(args.action ?? "");
    const rawPath = String(args.path ?? "");
    const encoding = args.encoding === undefined ? "utf8" : String(args.encoding);

    if (!SUPPORTED_ENCODINGS.has(encoding)) {
      return fail("不支持的 encoding（只支持 utf8 / base64）", "VALIDATION_ERROR", startedAt);
    }

    try {
      switch (action) {
        case "read": {
          const resolved = resolveWithinWorkspace(rawPath, {
            root: context.workspaceRoot,
            ...(context.allowedPaths === undefined ? {} : { allowedPaths: context.allowedPaths }),
            mustExist: true,
          });
          const stat = statSync(resolved);
          if (stat.size > MAX_FILE_BYTES) {
            return fail(`文件过大（${stat.size} > ${MAX_FILE_BYTES}）`, "VALIDATION_ERROR", startedAt);
          }
          const buffer = readFileSync(resolved);
          const content = encoding === "base64" ? buffer.toString("base64") : buffer.toString("utf8");
          return { ok: true, output: { path: rawPath, content, size: stat.size }, durationMs: Date.now() - startedAt };
        }

        case "list": {
          const resolved = resolveWithinWorkspace(rawPath, {
            root: context.workspaceRoot,
            ...(context.allowedPaths === undefined ? {} : { allowedPaths: context.allowedPaths }),
            mustExist: true,
          });
          const entries = readdirSync(resolved, { withFileTypes: true }).map((entry) => ({
            name: entry.name,
            type: entry.isDirectory() ? "dir" : "file",
          }));
          return { ok: true, output: { path: rawPath, entries }, durationMs: Date.now() - startedAt };
        }

        case "write": {
          const resolved = resolveWithinWorkspace(rawPath, {
            root: context.workspaceRoot,
            ...(context.allowedPaths === undefined ? {} : { allowedPaths: context.allowedPaths }),
          });
          const content = args.content === undefined ? "" : String(args.content);
          const buffer = encoding === "base64" ? Buffer.from(content, "base64") : Buffer.from(content, "utf8");
          // 父目录可能还不存在（新文件）—— 只建到 workspace 内的那一层，
          // 越界已经在上面挡住，所以这里 mkdir 的目标是安全的。
          const parent = dirname(resolved);
          if (!existsSync(parent)) mkdirSync(parent, { recursive: true });
          writeFileSync(resolved, buffer);
          return { ok: true, output: { path: rawPath, bytes: buffer.length }, durationMs: Date.now() - startedAt };
        }

        case "delete": {
          const resolved = resolveWithinWorkspace(rawPath, {
            root: context.workspaceRoot,
            ...(context.allowedPaths === undefined ? {} : { allowedPaths: context.allowedPaths }),
            mustExist: true,
          });
          rmSync(resolved, { recursive: true, force: false });
          return { ok: true, output: { path: rawPath, deleted: true }, durationMs: Date.now() - startedAt };
        }

        default:
          return fail(`未知 action ${JSON.stringify(action)}`, "VALIDATION_ERROR", startedAt);
      }
    } catch (error) {
      return fromGuardError(error, startedAt);
    }
  },
};

/** 建一个失败结果。 */
function fail(error: string, errorCode: string, startedAt: number): ToolOutcome {
  return { ok: false, error, errorCode, durationMs: Date.now() - startedAt };
}

/** 把 guard 的异常折成工具结果（**不抛**：工具失败是 observation，不是崩溃）。 */
export function fromGuardError(error: unknown, startedAt: number): ToolOutcome {
  if (error instanceof PathGuardError) {
    return {
      ok: false,
      error: error.message,
      errorCode: error.code,
      durationMs: Date.now() - startedAt,
    };
  }
  return {
    ok: false,
    error: error instanceof Error ? error.message : String(error),
    errorCode: "INTERNAL_ERROR",
    durationMs: Date.now() - startedAt,
  };
}
