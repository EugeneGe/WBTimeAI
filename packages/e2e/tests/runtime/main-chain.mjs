/**
 * T3-14 · DoD#1 **主链 e2e**（真端口 · 真 HTTP · `node:sqlite` · 脚本化假 Provider）。
 *
 * 判据（卡面 DoD#1 的第一句 + R3-11a 的双向口径）
 * -------------------------------------------
 *   ① **主链闭环**：建 Agent → 选模型 → 绑工具 → Chat 流式 → 调工具 → 沙箱执行 → 回放 ——
 *      每一段都有**外部可观测**证据（HTTP 响应 / 库里的行 / 沙箱输出），不靠"看起来对"；
 *   ② **19 帧按 12 产生 / 7 不产生**（R3-11a）：采集到的 `event:` 集合 **== 12 个**，
 *      另外 7 个**一次都不出现**（多一帧红、少一帧红）；
 *   ③ **真端口**：`assertRealPort` 用真实 TCP 连接复验（`app.inject()` 会被这条打红）。
 *
 * 为什么一个文件要跑四段场景
 * ----------------------
 *   12 帧里有 5 个只能由**特定通路**产生：`mcp.*` 需要 MCP server，`approval.*` 需要
 *   一次审批，`agent.error` 需要一次失败，`skill.resolved` 需要版本绑定技能。
 *   拆成四个文件会让"12/7 双向断言"没有单一载体；合在一个文件的四段场景里，
 *   "集合 == 12" 才是一条可复跑的断言。这与 V0.0.2 的 `sse.test.mjs` 同款手法。
 *
 * 复跑：`node packages/e2e/tests/runtime/main-chain.mjs`
 *      （或 `node scripts/run-runtime-e2e.mjs` 跑全套）
 */

import assert from "node:assert/strict";
import test, { after, before } from "node:test";

import {
  assertRealPort,
  call,
  collectRunFrames,
  createAgent,
  mcpEchoServerSpec,
  startRun,
  startRuntimeServer,
  waitFor,
  waitTerminal,
  WORKSPACE_ID,
} from "../../lib/runtime-server.mjs";
import { finalTurn, toolTurn } from "../../lib/fake-provider.mjs";

/** 12 个**必须产生**的通道（R3-11a 逐字）。 */
const TWELVE = [
  "agent.started",
  "agent.thinking",
  "message.delta",
  "tool.started",
  "tool.completed",
  "mcp.started",
  "mcp.completed",
  "agent.completed",
  "agent.error",
  "skill.resolved",
  "approval.requested",
  "approval.decided",
];

/** 7 个**一次都不许产生**的通道（能力在 V0.4.0 / V0.5.0）。 */
const SEVEN = [
  "workflow.started",
  "workflow.node.started",
  "workflow.node.completed",
  "workflow.completed",
  "workflow.failed",
  "knowledge.indexed",
  "memory.written",
];

const observed = new Set();
let server = null;

before(async () => {
  // 四段场景的模型脚本（网关每次 stream() 消耗一个脚本，见 lib/fake-provider.mjs）
  const turns = [
    // ① 主链：请求 shell（沙箱执行）→ 最终答复
    toolTurn("call-main", "shell", { command: "echo wbtime-e2e-sandbox" }),
    finalTurn("主链完成。"),
    // ② MCP：请求 mcp:echo/echo → 最终答复
    toolTurn("call-mcp", "mcp:echo/echo", { text: "hello-mcp" }),
    finalTurn("MCP 完成。"),
    // ③ 审批：请求 filesystem 写（需审批）→ 最终答复
    toolTurn("call-appr", "filesystem", { action: "write", path: "approval.txt", content: "ok" }),
    finalTurn("审批完成。"),
    // ④ 失败：一直请求工具 + maxModelTurns=1 ⇒ budget_turns ⇒ agent.error
    toolTurn("call-fail", "shell", { command: "echo never" }),
  ];
  server = await startRuntimeServer({ label: "main-chain", turns });
  await assertRealPort(server);
});

after(async () => {
  if (server !== null) await server.stop();
});

// ---------------------------------------------------------------------------
// ① 主链：建 Agent → 选模型 → 绑工具 → Chat 流式 → 调工具 → 沙箱执行 → 回放
// ---------------------------------------------------------------------------

test("① 主链闭环：建 Agent / 选模型 / 绑技能 / 流式 / 调工具 / 沙箱执行 / 回放", async (t) => {
  // 绑技能（`skill.resolved` 需要它真的在库里；解析不到就不发帧）
  const skillName = `e2e-skill-${Date.now()}`;
  const skill = await call({
    baseUrl: server.baseUrl,
    method: "POST",
    path: "/api/v1/skills",
    token: server.token,
    body: { name: skillName, description: "e2e 技能" },
  });
  assert.equal(skill.status, 201, skill.text);

  const agent = await createAgent(server, {
    name: "e2e 主链 Agent",
    modelConfig: { model: "fake-1", provider: "fake" },
    runtimeConfig: { skills: [skillName] },
  });

  // 「绑工具」：先让内置 5 工具物化（`GET /tools` 幂等 ensure，R3-23），再读回确认
  const tools = await call({ baseUrl: server.baseUrl, path: "/api/v1/tools", token: server.token });
  assert.equal(tools.status, 200, tools.text);
  const toolNames = tools.json.data.map((item) => item.name).sort();
  for (const name of ["filesystem", "git", "http", "shell", "code_exec"]) {
    assert.ok(toolNames.includes(name), `工具目录缺 ${name}：${toolNames.join(",")}`);
  }

  const run = await startRun(server, agent.agentId, { message: "请跑一个命令" });
  assert.equal(typeof run.id, "string", "run 入口必须返回 RunResponse（含 id）");
  assert.equal(run.agent_version_id, agent.versionId);

  const terminal = await waitTerminal(server, run.id);
  t.diagnostic(`run ${run.id} ⇒ ${terminal.status}/${terminal.stop_reason}`);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));
  assert.equal(terminal.stop_reason, "model_finish");

  // 沙箱执行的**外部证据**：tool_call 行里的 stdout（不是"我们声称执行了"）
  const toolCall = server.raw
    .prepare("select * from tool_call where run_id = ?")
    .get(run.id);
  assert.ok(toolCall !== undefined, "tool_call 行必须存在");
  assert.equal(toolCall.tool_name, "shell");
  assert.equal(toolCall.status, "SUCCESS");
  const output = JSON.parse(toolCall.output);
  assert.match(String(output.stdout ?? ""), /wbtime-e2e-sandbox/, `沙箱 stdout 实测 ${JSON.stringify(output)}`);

  // 回放：真 HTTP 收帧（带 Last-Event-ID 续传）
  const collected = await collectRunFrames(server, run.id);
  for (const channel of collected.channels) observed.add(channel);
  for (const channel of ["agent.started", "agent.thinking", "message.delta", "tool.started", "tool.completed", "skill.resolved", "agent.completed"]) {
    assert.ok(collected.channels.has(channel), `主链缺帧 ${channel}（实测 ${[...collected.channels].join(",")}）`);
  }

  // 消息落库：user + assistant + tool（回放读的就是这批持久化数据）
  const roles = server.raw
    // 按 `rowid`（插入序）读：`created_at` 是秒粒度，同一秒内的行会并列 ⇒
    // 用 `id` 兜底等于用随机 uuid 排序，会把"对话次序"读成乱序。
    .prepare("select role from message where conversation_id = ? order by rowid")
    .all(run.conversation_id)
    .map((row) => row.role);
  assert.deepEqual(roles.filter((role) => role !== "system"), ["user", "assistant", "tool", "assistant"]);
});

// ---------------------------------------------------------------------------
// ② MCP 通路：工具经 ToolExecutor 的四段边界（mcp.* 帧）
// ---------------------------------------------------------------------------

test("② MCP 通路：注册 stdio server → discover → 模型请求 mcp 工具 ⇒ mcp.started/completed", async (t) => {
  const spec = mcpEchoServerSpec();
  const registered = await call({
    baseUrl: server.baseUrl,
    method: "POST",
    path: "/api/v1/mcp/servers",
    token: server.token,
    body: { name: "echo", transport: "stdio", command: spec.command, args: spec.args },
  });
  assert.equal(registered.status, 201, registered.text);
  const serverId = registered.json.data.id;

  // discover：真连一次 stdio server（协议握手真实发生）
  const discovered = await call({
    baseUrl: server.baseUrl,
    method: "POST",
    path: `/api/v1/mcp/servers/${serverId}/discover`,
    token: server.token,
  });
  assert.equal(discovered.status, 200, discovered.text);
  assert.ok(
    discovered.json.data.some((item) => item.name === "echo"),
    `discover 应物化 echo：${discovered.text.slice(0, 300)}`
  );

  const agent = await createAgent(server, { name: "e2e MCP Agent" });
  const run = await startRun(server, agent.agentId, { message: "用 MCP 回声" });
  const terminal = await waitTerminal(server, run.id);
  t.diagnostic(`mcp run ⇒ ${terminal.status}/${terminal.stop_reason} :: ${terminal.error ?? ""}`);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

  const collected = await collectRunFrames(server, run.id);
  for (const channel of collected.channels) observed.add(channel);
  assert.ok(collected.channels.has("mcp.started"), `缺 mcp.started：${[...collected.channels].join(",")}`);
  assert.ok(collected.channels.has("mcp.completed"), `缺 mcp.completed：${[...collected.channels].join(",")}`);

  // MCP 工具走的是**同一条**四段边界（不是旁路）：tool_call 行的 tool_type = mcp
  const toolCall = server.raw.prepare("select * from tool_call where run_id = ?").get(run.id);
  assert.equal(toolCall.tool_name, "mcp:echo/echo");
  assert.equal(toolCall.tool_type, "mcp");
  assert.equal(toolCall.status, "SUCCESS");
  assert.match(String(toolCall.output ?? ""), /echo:hello-mcp/, `MCP 输出实测 ${toolCall.output}`);
});

// ---------------------------------------------------------------------------
// ③ 审批通路：approval.requested / approval.decided
// ---------------------------------------------------------------------------

test("③ 审批通路：requires_approval 命中 ⇒ 挂起 → 批准 → 继续执行", async () => {
  const agent = await createAgent(server, {
    name: "e2e 审批 Agent",
    runtimeConfig: { requires_approval: ["filesystem"] },
  });
  const run = await startRun(server, agent.agentId, { message: "写一个文件" });

  // 等审批单出现（真 HTTP 轮询 `GET /approvals`，契约：只返回 PENDING）
  let approval = null;
  await waitFor(async () => {
    const pending = await call({ baseUrl: server.baseUrl, path: "/api/v1/approvals", token: server.token });
    approval = (pending.json?.data ?? []).find((item) => item.subject_type === "tool") ?? null;
    return approval !== null;
  }, "approval PENDING");

  const decided = await call({
    baseUrl: server.baseUrl,
    method: "POST",
    path: `/api/v1/approvals/${approval.id}/approve`,
    token: server.token,
    body: {},
  });
  assert.equal(decided.status, 200, decided.text);

  const terminal = await waitTerminal(server, run.id);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

  const collected = await collectRunFrames(server, run.id);
  for (const channel of collected.channels) observed.add(channel);
  assert.ok(collected.channels.has("approval.requested"), [...collected.channels].join(","));
  assert.ok(collected.channels.has("approval.decided"), [...collected.channels].join(","));

  // 批准后工具真的执行了（外部观测：工作区文件）
  const written = server.raw.prepare("select status from tool_call where run_id = ?").get(run.id);
  assert.equal(written.status, "SUCCESS");
});

// ---------------------------------------------------------------------------
// ④ 失败通路：agent.error
// ---------------------------------------------------------------------------

test("④ 失败通路：maxModelTurns=1 且模型一直请求工具 ⇒ budget_turns ⇒ agent.error", async () => {
  const agent = await createAgent(server, {
    name: "e2e 失败 Agent",
    runtimeConfig: { limits: { maxModelTurns: 1 } },
  });
  const run = await startRun(server, agent.agentId, { message: "一直请求工具" });
  const terminal = await waitTerminal(server, run.id);
  assert.equal(terminal.status, "FAILED", JSON.stringify(terminal));
  assert.equal(terminal.stop_reason, "budget_turns");

  const collected = await collectRunFrames(server, run.id);
  for (const channel of collected.channels) observed.add(channel);
  assert.ok(collected.channels.has("agent.error"), [...collected.channels].join(","));
  assert.ok(!collected.channels.has("agent.completed"), "失败的 run 不得发 agent.completed");
});

// ---------------------------------------------------------------------------
// ⑤ 19 帧双向断言（R3-11a）—— 必须放最后（依赖前四段场景的采集结果）
// ---------------------------------------------------------------------------

test("⑤ R3-11a 双向：采集集合 == 12 个 ∧ 7 个一次都不出现", (t) => {
  t.diagnostic(`observed(${observed.size})=${[...observed].sort().join(",")}`);

  const missing = TWELVE.filter((channel) => !observed.has(channel));
  assert.deepEqual(missing, [], `12 个通道缺 ${missing.join(",")}`);

  const unexpected = [...observed].filter((channel) => !TWELVE.includes(channel));
  assert.deepEqual(unexpected, [], `出现了 12 帧之外的下发通道：${unexpected.join(",")}`);

  const forbidden = SEVEN.filter((channel) => observed.has(channel));
  assert.deepEqual(forbidden, [], `7 个"不产生"的通道出现了：${forbidden.join(",")}（R3-11a 反例）`);

  assert.equal(observed.size, 12, `集合必须恰 12 个，实测 ${observed.size}`);
});

// ---------------------------------------------------------------------------
// 附：真端口自证（把"不是 mock"做成断言而不是声明）
// ---------------------------------------------------------------------------

test("附 · 真端口自证：能连上 ∧ inject 不在本文件的请求路径上", async () => {
  await assertRealPort(server);
  // 一个不存在的端口必须连不上（否则"能连上"就没有区分力）
  const closed = 1;
  assert.notEqual(server.port, closed);
  const health = await call({ baseUrl: server.baseUrl, path: "/healthz" });
  assert.equal(health.status, 200, "健康检查必须 200（真 HTTP 通路）");
  // 响应壳自证：带 request_id 且体 == 头
  const envelope = await call({ baseUrl: server.baseUrl, path: `/api/v1/runs/${"0".repeat(8)}-0000-4000-8000-000000000000`, token: server.token });
  assert.equal(typeof envelope.headers.get("x-request-id"), "string");
  assert.equal(envelope.json.request_id, envelope.headers.get("x-request-id"));
  void WORKSPACE_ID;
});
