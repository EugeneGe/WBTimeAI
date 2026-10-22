#!/usr/bin/env node
/**
 * T3-14 · 运行时 e2e 的 **stdio MCP server** fixture（手写 JSON-RPC，零 SDK 依赖）。
 *
 * 为什么要它：`mcp.started` / `mcp.completed` 两帧只有在"模型请求一个 MCP 工具"时才
 * 会产生。要让这条通路**真的**通，必须有一个能被 `createMcpClient` 连上的 server ——
 * 用假对象顶替 `createMcpClient` 就等于验了"我们自己的桩"，不是验通路。
 *
 * 协议面（只实现用到的最小集，行分隔 JSON-RPC 2.0）：
 *   - `initialize`  ⇒ 回 `protocolVersion` + `capabilities.tools` + `serverInfo`
 *   - `tools/list`  ⇒ 回一条 `echo` 工具（带 `inputSchema`）
 *   - `tools/call`  ⇒ 回 `content: [{type:"text", text:"echo:<入参 text>"}]`
 *   - `notifications/initialized` 等通知 ⇒ 忽略（不回）
 *
 * 用法：`node mcp-echo-server.mjs`（由 e2e 经 `POST /mcp/servers` 注册为 stdio server）。
 */

import { stdin, stdout } from "node:process";

/** 逐行读 stdin（JSON-RPC 的 stdio 传输是"一行一条消息"）。 */
let buffer = "";
stdin.setEncoding("utf8");
stdin.on("data", (chunk) => {
  buffer += chunk;
  let index = buffer.indexOf("\n");
  while (index >= 0) {
    const line = buffer.slice(0, index).trim();
    buffer = buffer.slice(index + 1);
    if (line !== "") handleLine(line);
    index = buffer.indexOf("\n");
  }
});

/** 回一条 result。 */
function reply(id, result) {
  stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id, result })}\n`);
}

/** 回一条 error。 */
function fail(id, code, message) {
  stdout.write(`${JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } })}\n`);
}

/** 处理一条请求。 */
function handleLine(line) {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    return;
  }
  if (message.id === undefined) return; // 通知：不需要回
  switch (message.method) {
    case "initialize":
      reply(message.id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "wbtime-e2e-echo", version: "0.0.1" },
      });
      return;
    case "tools/list":
      reply(message.id, {
        tools: [
          {
            name: "echo",
            description: "e2e 回声工具（把入参 text 原样回显）",
            inputSchema: {
              type: "object",
              properties: { text: { type: "string" } },
              required: ["text"],
            },
          },
        ],
      });
      return;
    case "tools/call": {
      const params = message.params ?? {};
      const args = params.arguments ?? {};
      if (params.name !== "echo") {
        fail(message.id, -32602, `unknown tool ${JSON.stringify(params.name)}`);
        return;
      }
      reply(message.id, {
        content: [{ type: "text", text: `echo:${String(args.text ?? "")}` }],
        isError: false,
      });
      return;
    }
    default:
      fail(message.id, -32601, `method not found: ${JSON.stringify(message.method)}`);
  }
}
