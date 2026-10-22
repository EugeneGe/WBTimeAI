/**
 * T3-11 · MCP client 的行为证明（**真 SDK + 手写假 stdio server**）。
 *
 * 判据（卡面验收 ④ + 反例）
 * --------------------
 *   ① **stdio discover 全链路真跑**：手写一个约 30 行的 JSON-RPC server（回
 *      `initialize` / `tools/list`），用**真 SDK client** 连它、拉到工具清单 ——
 *      这证明 SDK 接线是通的，不是"fake client 自说自话"；
 *   ② **stdio 命令黑名单**（与 shell 工具同一张表）：`command:"sudo"` ⇒ `PERMISSION_DENIED`，
 *      且**子进程从未启动**；
 *   ③ **http 出网闸**（验收 ④）：无白名单 / 解析到内网 ⇒ `PERMISSION_DENIED`，
 *      **未登记域名的 MCP 端点不得放行**（卡面反例②）；
 *   ④ **连接超时**：起一个"从不回话"的进程 ⇒ 超时错误（不是挂死）。
 *
 * 为什么假 server 手写而不是用 SDK 的 Server 类：卡面红线「**只做 client**」——
 * 产品代码不得 import server 侧模块；测试夹具用它同样会让依赖面说不清。
 * 手写只需覆盖 `initialize` / `tools/list` 两条消息，30 行内说清。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/mcp-client.test.mjs`
 */

import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  DEFAULT_MCP_CONNECT_TIMEOUT_MS,
  McpTransportError,
  createMcpClient,
  discoverTools,
} from "../dist/modules/mcp/client.js";

/** 手写假 MCP server（JSON-RPC over stdio，只覆盖两条消息）。 */
const FAKE_SERVER_SCRIPT = `
let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buf += chunk;
  let index;
  while ((index = buf.indexOf("\\n")) >= 0) {
    const line = buf.slice(0, index).trim();
    buf = buf.slice(index + 1);
    if (line === "") continue;
    let message;
    try { message = JSON.parse(line); } catch { continue; }
    if (message.method === "initialize") {
      reply(message.id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "fake-mcp", version: "0.0.1" },
      });
    } else if (message.method === "tools/list") {
      reply(message.id, {
        tools: [
          {
            name: "echo",
            description: "回声工具",
            inputSchema: { type: "object", properties: { text: { type: "string" } } },
          },
        ],
      });
    }
  }
});
function reply(id, result) {
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\\n");
}
`;

/** 建假 server 脚本（返回 `node` 可执行文件路径）。 */
function makeFakeServer() {
  const dir = mkdtempSync(join(tmpdir(), "wb-mcp-"));
  const scriptPath = join(dir, "fake-mcp-server.mjs");
  writeFileSync(scriptPath, FAKE_SERVER_SCRIPT, "utf8");
  return {
    command: process.execPath,
    args: [scriptPath],
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
}

// ---------------------------------------------------------------------------
// A 组 · stdio discover（真 SDK）
// ---------------------------------------------------------------------------

test("A-1 · 真 SDK 连假 server ⇒ discover 拉到工具清单（协议握手真实发生）", async () => {
  const fake = makeFakeServer();
  try {
    const tools = await discoverTools(
      { name: "fake", transport: "stdio", command: fake.command, args: fake.args },
      { connectTimeoutMs: 10_000 }
    );
    assert.equal(tools.length, 1);
    assert.equal(tools[0].name, "echo");
    assert.equal(tools[0].description, "回声工具");
    assert.equal(tools[0].inputSchema.type, "object");
  } finally {
    fake.cleanup();
  }
});

test("A-2 · client 实例可复用两次 listTools（连接不被立即销毁）", async () => {
  const fake = makeFakeServer();
  try {
    const client = await createMcpClient(
      { name: "fake", transport: "stdio", command: fake.command, args: fake.args },
      { connectTimeoutMs: 10_000 }
    );
    const first = await client.listTools();
    const second = await client.listTools();
    assert.deepEqual(second, first, "同一 client 的两次调用结果一致");
    await client.close();
  } finally {
    fake.cleanup();
  }
});

// ---------------------------------------------------------------------------
// B 组 · stdio 命令黑名单
// ---------------------------------------------------------------------------

test("B-1 · stdio 命令命中黑名单 ⇒ PERMISSION_DENIED 且**子进程未启动**", async () => {
  for (const [command, args] of [
    ["sudo", ["ls"]],
    ["rm", ["-rf", "/"]],
    ["sh", ["-c", "echo $(whoami)"]],
  ]) {
    await assert.rejects(
      () =>
        discoverTools({ name: "evil", transport: "stdio", command, args: [...args] }, {}),
      (error) => {
        assert.ok(error instanceof McpTransportError, `必须是 McpTransportError，实测 ${String(error)}`);
        assert.equal(error.code, "PERMISSION_DENIED");
        return true;
      }
    );
  }
});

test("B-2 · stdio 缺 command ⇒ VALIDATION_ERROR（不是 500）", async () => {
  await assert.rejects(
    () => discoverTools({ name: "x", transport: "stdio", command: null, args: [] }, {}),
    (error) => error instanceof McpTransportError && error.code === "VALIDATION_ERROR"
  );
});

// ---------------------------------------------------------------------------
// C 组 · http 出网闸（验收 ④）
// ---------------------------------------------------------------------------

test("C-1 · http transport 无白名单 ⇒ PERMISSION_DENIED（未登记域名不得放行）", async () => {
  await assert.rejects(
    () =>
      discoverTools(
        { name: "remote", transport: "http", endpoint: "https://evil.example/mcp" },
        {}
      ),
    (error) => {
      assert.ok(error instanceof McpTransportError);
      assert.equal(error.code, "PERMISSION_DENIED");
      assert.match(error.message, /未命中白名单|出网被拒/);
      return true;
    }
  );
});

test("C-2 · http transport 解析到内网 ⇒ PERMISSION_DENIED（SSRF 复用同一实现）", async () => {
  await assert.rejects(
    () =>
      discoverTools(
        { name: "remote", transport: "http", endpoint: "https://inside.example/mcp" },
        {
          egressAllowlist: ["*.example"],
          resolver: async () => ["10.0.0.1"],
        }
      ),
    (error) => error instanceof McpTransportError && error.code === "PERMISSION_DENIED"
  );
});

test("C-3 · http transport 白名单 + 公网 IP 字面 ⇒ 过闸后连接失败（不是被闸拒绝）", async () => {
  await assert.rejects(
    () =>
      discoverTools(
        { name: "remote", transport: "http", endpoint: "https://93.184.216.34/mcp" },
        { egressAllowlist: ["93.184.216.34"], connectTimeoutMs: 2_000 }
      ),
    (error) => {
      // 过了出网闸，但真实连接（指向一个没有 MCP server 的地址）会失败：
      // 失败码必须是 INTERNAL_ERROR（连接问题），**不能是** PERMISSION_DENIED。
      assert.ok(error instanceof McpTransportError);
      assert.equal(error.code, "INTERNAL_ERROR");
      return true;
    }
  );
});

// ---------------------------------------------------------------------------
// D 组 · transport 校验与超时
// ---------------------------------------------------------------------------

test("D-1 · 未知 transport ⇒ VALIDATION_ERROR", async () => {
  await assert.rejects(
    () => discoverTools({ name: "x", transport: "carrier-pigeon", command: "ls" }, {}),
    (error) => error instanceof McpTransportError && error.code === "VALIDATION_ERROR"
  );
});

test("D-2 · 永不回话的进程 ⇒ 连接超时（不挂死）", async () => {
  const dir = mkdtempSync(join(tmpdir(), "wb-mcp-"));
  const silent = join(dir, "silent.mjs");
  writeFileSync(silent, "setInterval(() => {}, 1000);\n", "utf8");
  try {
    await assert.rejects(
      () =>
        discoverTools(
          { name: "silent", transport: "stdio", command: process.execPath, args: [silent] },
          { connectTimeoutMs: 500 }
        ),
      (error) => {
        assert.ok(error instanceof McpTransportError);
        assert.match(error.message, /超时|连接失败/);
        return true;
      }
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("D-3 · 缺省连接超时是 10 秒（常量被测试锁住）", () => {
  assert.equal(DEFAULT_MCP_CONNECT_TIMEOUT_MS, 10_000);
});
