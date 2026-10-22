/**
 * T3-11 · MCP client（**只做 client**，卡面红线）。
 *
 * 三种 transport 与它们各自的闸
 * --------------------------
 * | transport | 连接方式 | 额外闸 |
 * |---|---|---|
 * | `stdio` | `command` + `args` 起子进程，走 JSON-RPC over stdio | 无网络，但**命令本身**要过 `checkCommand` |
 * | `http` / `sse` | `endpoint` 远程 | **必须过 `checkEgress`**（卡面验收 ④：MCP 端点未登记域名不得放行） |
 *
 * 为什么 `std::` 也要过 `checkCommand`
 * --------------------------------
 *   `command: "rm"`, `args: ["-rf", "/"]` 与 shell 工具是同一种风险 —— MCP server 是
 *   **外部提供的可执行文件**，注册它等于让用户往本机装一个进程。所以 stdio 起进程前
 *   复用 `guards/command` 的 15 条黑名单（拼成一条命令扫）。
 *
 * 为什么用 SDK 的 `Client` 而不是自己实现 JSON-RPC
 * --------------------------------------------
 *   协议版本协商 + `initialized` 通知 + 分页 + 错误码都是协议细节，自己实现等于维护
 *   第二份 MCP。卡面明确「`@modelcontextprotocol/sdk@1.32.1` 仅 client」。
 *   本文件把 SDK 收在一个薄适配层里，好处是**测试可以注入 fake client**
 *   （`mcp-client.test.mjs` 用假 stdio server 走真 SDK；单元测试用 fake 走纯逻辑）。
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import { checkCommand, CommandDeniedError } from "../tool/guards/command.js";
import { checkEgress, EgressDeniedError, type HostResolver } from "../tool/guards/ssrf.js";

/** 一个 MCP 工具的描述（`tools/list` 的条目）。 */
export interface McpToolDescriptor {
  readonly name: string;
  readonly description?: string;
  /** 入参 JSON Schema（MCP 原样给出；我们原样存进 `mcp_tool.input_schema`）。 */
  readonly inputSchema: Record<string, unknown>;
  readonly outputSchema?: Record<string, unknown>;
}

/** `tools/call` 的返回（MCP 原样：`content` 是分片数组）。 */
export interface McpCallResult {
  readonly content: readonly unknown[];
  readonly isError?: boolean;
}

/** client 抽象（测试注入用）。 */
export interface McpClientLike {
  listTools(): Promise<readonly McpToolDescriptor[]>;
  /** 调用一个工具（**唯一执行入口**；产品侧只经 `adapter.ts` 间接调用）。 */
  callTool(name: string, args: Record<string, unknown>): Promise<McpCallResult>;
  close(): Promise<void>;
}

/** 注册到库里的 server 形态（只取连接需要的字段）。 */
export interface McpServerTarget {
  readonly name: string;
  readonly transport: string;
  readonly command?: string | null;
  readonly args?: readonly string[] | null;
  readonly endpoint?: string | null;
}

/** 连接 / 发现失败的分类（调用方据此给 502 / 403 / 400）。 */
export class McpTransportError extends Error {
  readonly name = "McpTransportError";
  readonly code: "PERMISSION_DENIED" | "VALIDATION_ERROR" | "INTERNAL_ERROR";
  readonly data: Readonly<Record<string, unknown>>;

  constructor(message: string, code: McpTransportError["code"], data: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

/** client 工厂选项。 */
export interface CreateClientOptions {
  /** 出网白名单（`http` transport 必填；空 ⇒ 拒绝全部）。 */
  readonly egressAllowlist?: readonly string[];
  /** 解析器（测试注入，用于 SSRF rebinding 用例）。 */
  readonly resolver?: HostResolver;
  /** 连接超时（毫秒，缺省 10s）。 */
  readonly connectTimeoutMs?: number;
  /**
   * transport 构造注入缝（**测试专用**，与 `resolver` 同一形态的先例）。
   *
   * 为什么需要它（AUD-14）：`http` 档的用例原本连 `https://93.184.216.34/mcp`
   * （example.com 的 IP 字面）来证明"过闸之后**连接失败**"，于是**整个单测依赖外网**：
   * 没有网络的环境里它红得莫名其妙，有网络时又慢又不可复现。
   *
   * ⚠️ 把地址改成 `127.0.0.1` 是**不可行**的替代方案：`checkEgress` 的 `DENY_RANGES`
   * 含 `127.0.0.0/8`，回环地址会被出网闸直接拒掉 ⇒ 用例退化成"被闸拒绝"，
   * 恰好把要证的那件事（**过闸之后**才失败）证反。
   *
   * 所以注入点在 **transport**：出网闸照旧真跑（这才是被测语义），只把"真去连一个
   * socket"换成"返回一个立刻失败的假 transport"。类型用 `unknown` 是为了不让测试
   * 依赖 SDK 的 transport 抽象（它只是被原样交给 `client.connect()`）。
   */
  readonly transportFactory?: (url: URL) => unknown;
}

/** 缺省连接超时。 */
export const DEFAULT_MCP_CONNECT_TIMEOUT_MS = 10_000;

/**
 * 建一个 MCP client（**未连接**，由调用方 `listTools()` 时惰性连接）。
 *
 * @throws {McpTransportError} transport 不支持 / stdio 命令被黑名单拦 / http 出网被拒。
 */
export async function createMcpClient(
  server: McpServerTarget,
  options: CreateClientOptions = {}
): Promise<McpClientLike> {
  const transport = (server.transport || "stdio").toLowerCase();

  if (transport === "stdio") {
    return createStdioClient(server, options);
  }
  if (transport === "http" || transport === "sse") {
    return createHttpClient(server, options);
  }
  throw new McpTransportError(
    `不支持的 MCP transport ${JSON.stringify(server.transport)}（允许：stdio / http / sse）`,
    "VALIDATION_ERROR",
    { transport: server.transport }
  );
}

/** stdio：起子进程 + JSON-RPC。 */
async function createStdioClient(
  server: McpServerTarget,
  options: CreateClientOptions
): Promise<McpClientLike> {
  const command = server.command ?? "";
  if (command === "") {
    throw new McpTransportError("stdio transport 需要 command", "VALIDATION_ERROR", {
      server: server.name,
    });
  }

  // 闸：命令黑名单（与 shell 工具同一张表）
  try {
    checkCommand([command, ...(server.args ?? [])]);
  } catch (error) {
    if (error instanceof CommandDeniedError) {
      throw new McpTransportError(`MCP stdio 命令被拒：${error.message}`, "PERMISSION_DENIED", {
        server: server.name,
        command,
      });
    }
    throw error;
  }

  const transport = new StdioClientTransport({
    command,
    args: [...(server.args ?? [])],
    // 不继承 `process.env`：与 `LocalProcessSandbox` 同一纪律（主密钥不得漏进子进程）。
    env: pickSafeEnv(),
    stderr: "pipe",
  });

  return connectClient(new Client({ name: "wbtime-ai", version: "0.3.0" }, { capabilities: {} }), transport, options);
}

/** http / sse：远程端点（**必须先过 SSRF**）。 */
async function createHttpClient(
  server: McpServerTarget,
  options: CreateClientOptions
): Promise<McpClientLike> {
  const endpoint = server.endpoint ?? "";
  if (endpoint === "") {
    throw new McpTransportError("http transport 需要 endpoint", "VALIDATION_ERROR", {
      server: server.name,
    });
  }

  // 闸：出网（卡面验收 ④）
  try {
    await checkEgress(endpoint, {
      ...(options.egressAllowlist === undefined ? {} : { allowlist: options.egressAllowlist }),
      ...(options.resolver === undefined ? {} : { resolver: options.resolver }),
    });
  } catch (error) {
    if (error instanceof EgressDeniedError) {
      throw new McpTransportError(`MCP 端点出网被拒：${error.message}`, "PERMISSION_DENIED", {
        server: server.name,
        endpoint,
      });
    }
    throw error;
  }

  const target = new URL(endpoint);
  // 测试注入缝优先（`transportFactory` 只在单测里出现；生产路径恒走 SDK 的
  // `StreamableHTTPClientTransport`）。注意出网闸在**上面**已经执行过 —— 注入的只是
  // "怎么连"，不是"能不能连"。
  const transport =
    options.transportFactory !== undefined
      ? options.transportFactory(target)
      : new StreamableHTTPClientTransport(target);
  return connectClient(
    new Client({ name: "wbtime-ai", version: "0.3.0" }, { capabilities: {} }),
    transport as Parameters<Client["connect"]>[0],
    options
  );
}

/** 连上并包成 `McpClientLike`（连接超时用 `Promise.race`）。 */
async function connectClient(
  client: Client,
  transport: Parameters<Client["connect"]>[0],
  options: CreateClientOptions
): Promise<McpClientLike> {
  const timeoutMs = options.connectTimeoutMs ?? DEFAULT_MCP_CONNECT_TIMEOUT_MS;
  try {
    await withTimeout(client.connect(transport), timeoutMs, "MCP 连接超时");
  } catch (error) {
    // 连不上就别留半开的子进程
    await client.close().catch(() => undefined);
    throw error instanceof McpTransportError
      ? error
      : new McpTransportError(
          `MCP 连接失败：${error instanceof Error ? error.message : String(error)}`,
          "INTERNAL_ERROR"
        );
  }

  return {
    async listTools() {
      const result = await withTimeout(client.listTools(), timeoutMs, "MCP tools/list 超时");
      return (result.tools ?? []).map((tool) => ({
        name: tool.name,
        ...(tool.description === undefined ? {} : { description: tool.description }),
        inputSchema: (tool.inputSchema ?? {}) as Record<string, unknown>,
        ...(tool.outputSchema === undefined
          ? {}
          : { outputSchema: tool.outputSchema as Record<string, unknown> }),
      }));
    },
    async callTool(name, args) {
      const result = await withTimeout(
        client.callTool({ name, arguments: args }),
        timeoutMs,
        "MCP tools/call 超时"
      );
      return {
        content: (result.content ?? []) as readonly unknown[],
        ...(result.isError === true ? { isError: true } : {}),
      };
    },
    async close() {
      await client.close().catch(() => undefined);
    },
  };
}

/** 超时包装（SDK 自己不保证超时）。 */
function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new McpTransportError(message, "INTERNAL_ERROR")), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

/** 子进程环境白名单（与 `LocalProcessSandbox` 同纪律）。 */
function pickSafeEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const key of ["PATH", "HOME", "LANG", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT"]) {
    const value = process.env[key];
    if (value !== undefined) env[key] = value;
  }
  return env;
}

/**
 * 发现工具（连接 → `tools/list` → 关闭）。
 *
 * **一次一连接**：MCP 的 stdio 会话是有状态的，长期持有会让"server 挂了但连接还在"的
 * 状态在内存里堆积。discover 是低频动作，开完就关最省心。
 *
 * @throws {McpTransportError}
 */
export async function discoverTools(
  server: McpServerTarget,
  options: CreateClientOptions = {}
): Promise<readonly McpToolDescriptor[]> {
  const client = await createMcpClient(server, options);
  try {
    return await client.listTools();
  } finally {
    await client.close();
  }
}
