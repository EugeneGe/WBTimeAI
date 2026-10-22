/**
 * T3-11 · MCP 工具 → `ToolExecutor` 的**唯一桥**（卡面验收 ③ / 反例①）。
 *
 * 为什么要"包成 `BuiltinTool`"而不是让 AgentLoop 直接调 MCP
 * ----------------------------------------------------
 *   卡面反例写得很直白：「MCP 工具绕过 `ToolExecutor` 直连 ⇒ 必红」。绕过会同时失去四件事：
 *   **逐次授权**、**统一超时**、**四段事务边界**（intent/authorize/execute/result）、
 *   **审计**。把 MCP 工具实现成 `BuiltinTool`，它就走与 5 个内置工具**完全相同**的路径 ——
 *   `ToolExecutor` 不需要知道"这个工具在进程内还是远端"。
 *
 * 命名空间：`mcp:<server>/<tool>`
 * ----------------------------
 *   为什么必须加前缀：MCP server 的工具名是**外部给的**，可以叫 `filesystem` / `shell`。
 *   不加命名空间，一个恶意 server 注册 `shell` 就能顶掉内置工具（或反过来被内置顶掉，
 *   取决于 Map 插入顺序 —— 那是不可接受的"看运气"）。前缀让两边永不冲突，
 *   也让授权串（`tool:mcp:fs/read`）能一眼看出归属。
 *
 * 本文件**不产出** `ToolExecutionResult`：它返回 `ToolOutcome`（工具层形态），
 * 由 `ToolExecutor` 的第 4 段映射。保持"工具只说自己成功没成功"这一层职责。
 */

import type { BuiltinTool, ToolContext, ToolOutcome } from "../tool/registry.js";
import { McpTransportError, type CreateClientOptions, type McpClientLike } from "./client.js";
import type { McpServerTarget, McpToolDescriptor } from "./client.js";

/** MCP 工具的对外名字（`mcp:<server>/<tool>`）。 */
export function mcpToolName(serverName: string, toolName: string): string {
  return `mcp:${serverName}/${toolName}`;
}

/** 拆回 `{server, tool}`（`tool` 里允许含 `/`，只按第一个 `/` 切）。 */
export function parseMcpToolName(qualified: string): { server: string; tool: string } | null {
  if (!qualified.startsWith("mcp:")) return null;
  const rest = qualified.slice("mcp:".length);
  const index = rest.indexOf("/");
  if (index <= 0 || index === rest.length - 1) return null;
  return { server: rest.slice(0, index), tool: rest.slice(index + 1) };
}

/** adapter 依赖。 */
export interface McpToolAdapterOptions {
  readonly server: McpServerTarget;
  readonly tool: McpToolDescriptor;
  /** client 工厂（测试注入 fake；缺省走真 SDK）。 */
  readonly createClient: (server: McpServerTarget, options: CreateClientOptions) => Promise<McpClientLike>;
  /** 出网白名单（http transport 用）。 */
  readonly egressAllowlist?: readonly string[];
}

/**
 * 把一个 MCP 工具包装成 `BuiltinTool`。
 *
 * 每次 `execute` **建连 → 调用 → 关闭**：MCP 会话有状态，长期持有会让"server 挂了
 * 但连接还在"在内存里堆积。调用频次低于 discover，代价可接受（连接池归后续版本）。
 *
 * `requiresSandbox: false`：MCP 的执行发生在**远端**或它自己的子进程里，
 * 本机不需要再套一层沙箱（stdio transport 的子进程已由 `client.ts` 的命令黑名单兜住）。
 */
export function createMcpToolAdapter(options: McpToolAdapterOptions): BuiltinTool {
  const name = mcpToolName(options.server.name, options.tool.name);

  return {
    name,
    requiresSandbox: false,

    async execute(args: Readonly<Record<string, unknown>>, _context: ToolContext): Promise<ToolOutcome> {
      const startedAt = Date.now();
      let client: McpClientLike | undefined;
      try {
        client = await options.createClient(
          options.server,
          options.egressAllowlist === undefined
            ? {}
            : { egressAllowlist: options.egressAllowlist }
        );
        const result = await client.callTool(options.tool.name, { ...args });
        const durationMs = Date.now() - startedAt;

        if (result.isError === true) {
          return {
            ok: false,
            error: describeContent(result.content) || "MCP 工具返回 isError",
            errorCode: "INTERNAL_ERROR",
            durationMs,
          };
        }
        return {
          ok: true,
          output: { content: result.content },
          durationMs,
        };
      } catch (error) {
        const durationMs = Date.now() - startedAt;
        if (error instanceof McpTransportError) {
          return {
            ok: false,
            error: error.message,
            errorCode: error.code === "PERMISSION_DENIED" ? "PERMISSION_DENIED" : "INTERNAL_ERROR",
            durationMs,
          };
        }
        return {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
          errorCode: "INTERNAL_ERROR",
          durationMs,
        };
      } finally {
        await client?.close();
      }
    },
  };
}

/** 把 MCP 的内容分片拼成一句人读文本（用于错误信息）。 */
function describeContent(content: readonly unknown[]): string {
  const parts: string[] = [];
  for (const item of content) {
    if (typeof item === "string") {
      parts.push(item);
      continue;
    }
    if (typeof item === "object" && item !== null) {
      const record = item as Record<string, unknown>;
      if (typeof record.text === "string") parts.push(record.text);
      else parts.push(JSON.stringify(record));
      continue;
    }
    parts.push(String(item));
  }
  return parts.join("\n").slice(0, 1000);
}
