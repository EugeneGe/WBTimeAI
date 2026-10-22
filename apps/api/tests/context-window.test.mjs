/**
 * AUD-01 · 长会话上下文**窗口方向**的行为证明（driver 层，真库 + 假网关）。
 *
 * 被修复的缺陷（AUD-01，P1）
 * ------------------------
 *   `RunDriver.loadMessages` 原先写 `messagesRepo.list({ limit: 200 })`。`MessageRepo.list`
 *   是 `(created_at asc, id asc) + LIMIT` ⇒ 取到的是**最旧的** 200 条。长会话一旦超过
 *   200 条，模型看到的永远是"开头那一段"，**本次 run 刚写入的用户消息在最末尾、看不见**，
 *   而且链路上一处报错都没有（静默截断）。
 *
 * 判据（三条，都钉在**可观测产物**上，不看实现细节）
 * ----------------------------------------------
 *   ① **最新用户消息必定在上下文里**：真跑一次 `RunDriver.start()`，记录假网关收到的
 *      `ModelRequest.messages` ⇒ 必须含本次发送的那句话（修复前：不含）；
 *   ② `context.built` 内部行带 `list_limit=200` 与 `truncated_by_list=true`
 *      （取回条数达到窗口上限）—— 静默截断从此**可观测**；
 *   ③ 窗口真的是 200（不是把整段历史全塞进上下文）：`input_count === 200`。
 *
 * 为什么用 driver 层而不是 HTTP 层：HTTP 回执里看不到"模型收到了什么"，
 * 而本条的缺陷恰恰是"HTTP 一切正常、模型看不到最新消息"。假网关是唯一能直接观测
 * `ModelRequest` 的注入点（`RunDriverDeps.gateway` 已是端口）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/context-window.test.mjs`
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { MessageRepo, Scope } from "@wbtime/db";

import { RunCoordinator } from "../dist/modules/run/coordinator.js";
import { RunDriver } from "../dist/modules/run/driver.js";
import { makeApp, TENANT_ID } from "./routes-harness.mjs";
import { createAgentWithVersion, createConversation, seedWorkspace } from "./fixtures/run-fixture.mjs";

/** 历史消息条数（**大于** 200 窗口，否则"取最旧"与"取最新"没有区别）。 */
const HISTORY = 250;

/** 历史消息的时间戳：远早于"现在"，保证本次 run 写入的用户消息**严格最新**。 */
const PAST = "2020-01-01 00:00:00";

/**
 * 记录每一次 `stream()` 的请求的假网关。
 *
 * 只发一段文本 + finish（不产生 tool_call）⇒ 一次 turn 就终态 `SUCCEEDED`，
 * 上下文只被读一次，断言不受多轮影响。
 */
function recordingGateway() {
  const requests = [];
  return {
    requests,
    stream(request) {
      requests.push(request);
      return (async function* generate() {
        yield { type: "text_delta", text: "好的" };
        yield { type: "finish", reason: "model_finish" };
      })();
    },
  };
}

/** 往会话里直插 N 条历史消息（`created_at` 固定在过去 —— 见 {@link PAST}）。 */
function seedHistory(fixture, conversationId, count) {
  const insert = fixture.raw.prepare(
    "insert into message (id, conversation_id, run_id, role, content, content_parts, token_count, created_at) " +
      "values (?, ?, null, ?, ?, null, null, ?)",
  );
  for (let index = 1; index <= count; index += 1) {
    insert.run(randomUUID(), conversationId, index % 2 === 0 ? "assistant" : "user", `历史消息 ${index}`, PAST);
  }
}

/** 读某 run 的内部事件行（`agent_event` 里非 12 帧的那些）。 */
function internalPayload(fixture, runId, type) {
  const row = fixture.raw
    .prepare("select payload from agent_event where run_id = ? and type = ? order by seq limit 1")
    .get(runId, type);
  return row === undefined ? null : JSON.parse(row.payload);
}

test("① 250 条历史（>窗口）⇒ 最新用户消息仍在上下文里；context.built 标记截断", async () => {
  const fixture = await makeApp({ username: "ctx-window" });
  try {
    seedWorkspace(fixture);
    const { agentId, versionId } = await createAgentWithVersion(fixture);
    const conversationId = await createConversation(fixture, agentId);
    seedHistory(fixture, conversationId, HISTORY);

    // 前置对照：库里确实有 250 条历史，且它们都早于"现在"。
    const scope = new Scope(TENANT_ID);
    const messages = new MessageRepo(fixture.connection.db, scope, scope.ref(conversationId), "sqlite");
    assert.equal((await messages.list({ limit: 500 })).length, HISTORY);

    const gateway = recordingGateway();
    const coordinator = new RunCoordinator({ db: fixture.connection.db, dialect: "sqlite", tenantId: TENANT_ID });
    const driver = new RunDriver({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      coordinator,
      gateway,
      workspaceRoot: mkdtempSync(join(tmpdir(), "wb-ctx-")),
      // 值取大：本用例不测压缩（压缩有独立判据），只测"窗口方向"。
      limits: {
        maxModelTurns: 3,
        maxToolCalls: 3,
        maxToolCallsPerTurn: 3,
        maxWallTimeMs: 60_000,
        maxTokens: 1_000_000,
        maxCost: 1_000_000,
      },
    });

    const newest = "最新一条用户消息：现在几点了";
    const started = await driver.start({
      tenantId: TENANT_ID,
      userId: fixture.userId,
      agentId,
      agentVersionId: versionId,
      systemPrompt: "你是测试助手",
      modelConfig: {},
      runtimeConfig: {},
      conversationId,
      workspaceId: null,
      agentWorkspaceId: null,
      message: newest,
      requestId: randomUUID(),
    });
    await driver.awaitSettled(started.run.id);

    // ---- ① 模型真的看到了本次用户消息 -----------------------------------
    assert.equal(gateway.requests.length, 1, "本用例只应调一次模型");
    const contents = gateway.requests[0].messages.map((message) => message.content);
    assert.ok(
      contents.includes(newest),
      `最新用户消息必须出现在模型上下文里 —— 实测 ${contents.length} 条，` +
        `头=${JSON.stringify(contents[0])} 尾=${JSON.stringify(contents[contents.length - 1])}` +
        `（修复前取的是最旧 200 条 ⇒ 这句话不在里面）`,
    );
    assert.equal(contents[contents.length - 1], newest, "它还必须排在**最后**（上下文按时间正序）");

    // ---- ② 截断可观测 ---------------------------------------------------
    const built = internalPayload(fixture, started.run.id, "context.built");
    assert.notEqual(built, null, "context.built 内部行必须存在");
    assert.equal(built.list_limit, 200, "窗口上限必须落进内部行（AUD-01 的可观测字段）");
    assert.equal(built.truncated_by_list, true, "取回条数达到窗口上限 ⇒ truncated_by_list=true");
    // 201 = 200 条仓储行（窗口）+ 1 条前置的合成 system 行；`truncated_by_list` 只数仓储行。
    assert.equal(built.input_count, 201, "③ 窗口就是 200 条仓储行（不是把 251 条全塞进去）");
  } finally {
    await fixture.close();
  }
});

test("② 历史不足窗口 ⇒ truncated_by_list=false（不把「没截断」谎报成截断）", async () => {
  const fixture = await makeApp({ username: "ctx-window-small" });
  try {
    seedWorkspace(fixture);
    const { agentId, versionId } = await createAgentWithVersion(fixture);
    const conversationId = await createConversation(fixture, agentId);
    seedHistory(fixture, conversationId, 3);

    const gateway = recordingGateway();
    const coordinator = new RunCoordinator({ db: fixture.connection.db, dialect: "sqlite", tenantId: TENANT_ID });
    const driver = new RunDriver({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      coordinator,
      gateway,
      workspaceRoot: mkdtempSync(join(tmpdir(), "wb-ctx-")),
    });

    const started = await driver.start({
      tenantId: TENANT_ID,
      userId: fixture.userId,
      agentId,
      agentVersionId: versionId,
      systemPrompt: "",
      modelConfig: {},
      runtimeConfig: {},
      conversationId,
      workspaceId: null,
      agentWorkspaceId: null,
      message: "短会话",
      requestId: randomUUID(),
    });
    await driver.awaitSettled(started.run.id);

    const built = internalPayload(fixture, started.run.id, "context.built");
    assert.equal(built.input_count, 4, "3 条历史 + 本次用户消息");
    assert.equal(built.truncated_by_list, false, "没到上限 ⇒ false（不许恒 true）");
    assert.equal(built.list_limit, 200, "limit 仍如实上报");
  } finally {
    await fixture.close();
  }
});
