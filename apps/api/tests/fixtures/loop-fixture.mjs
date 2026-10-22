/**
 * T3-09 · AgentLoop 测试夹具（**无网络、无数据库**）。
 *
 * 为什么全部是 fake：`AgentLoop` 的设计前提是"依赖全是端口"。如果测试要起真 provider，
 * 就永远测不了"预算耗尽时是否精确停"——那需要真的烧 token。fake 让 6 项停止条件
 * 各自 1 条用例成为可能（每项只需把账本推到阈值）。
 *
 * fake 的**唯一职责**是"按脚本产出分片"，不含任何业务判断 —— 任何"fake 里也判一下"
 * 的写法都会让被测逻辑出现两个真相源。
 */

import { BudgetLedger } from "@wbtime/domain";

/** 造一条消息行（`MessageRow` 的最小形态；只填被测代码读的字段）。 */
export function messageRow(id, role, content, seq = 1) {
  return {
    id,
    conversation_id: "c0000000-0000-4000-8000-000000000001",
    run_id: null,
    role,
    content,
    content_parts: [],
    token_count: null,
    created_at: `2026-10-22 00:00:0${seq}`,
  };
}

/** 造 N 条 user/assistant 交替的消息。 */
export function conversationRows(pairs) {
  const rows = [messageRow("m-system", "system", "你是测试助手")];
  for (let index = 0; index < pairs; index += 1) {
    rows.push(messageRow(`m-u-${index}`, "user", `问题 ${index}`));
    rows.push(messageRow(`m-a-${index}`, "assistant", `回答 ${index}`));
  }
  return rows;
}

/**
 * fake 模型网关：按 `script` 逐轮产出分片。
 *
 * @param script 每轮一个分片数组；取完后重复最后一轮（避免用例因轮数写少了挂住）。
 * @param onStream 每次 `stream` 调用时回调（用于断言"调了几次"）。
 */
export function fakeGateway(script, onStream = () => {}) {
  let turn = 0;
  return {
    get calls() {
      return turn;
    },
    async *stream(request, context) {
      onStream(request, turn);
      const chunks = script[Math.min(turn, script.length - 1)];
      turn += 1;
      for (const chunk of chunks) {
        // ⚠️ 记账是 **ModelGateway 的契约**（`gateway.ts` 在转发 `usage` 前调
        // `budget.addTokens()`），不是 AgentLoop 的职责 —— 两边都记会翻倍。
        // fake 必须忠实模拟这条契约，否则"预算耗尽"类用例在 fake 上永远不触发。
        if (chunk.type === "usage" && context !== undefined) {
          const tokens = (chunk.tokensIn ?? 0) + (chunk.tokensOut ?? 0);
          if (tokens > 0) context.budget.addTokens(tokens);
        }
        yield chunk;
      }
    },
  };
}

/** 一轮"请求工具"的分片（文本 + 一个 tool_call + usage + finish）。 */
export function toolCallTurn({ id = "call-1", name = "filesystem", input = { action: "list", path: "." } } = {}) {
  return [
    { type: "text_delta", text: "我查一下" },
    { type: "tool_call", id, name, input },
    { type: "usage", tokensIn: 10, tokensOut: 5 },
    { type: "finish", reason: "model_finish" },
  ];
}

/** 一轮"最终答复"的分片（无 tool_call）。 */
export function finalTurn(text = "好了，这就是答案") {
  return [
    { type: "text_delta", text },
    { type: "usage", tokensIn: 8, tokensOut: 4 },
    { type: "finish", reason: "model_finish" },
  ];
}

/** fake 执行器：按工具名返回预置结果，并记录调用。 */
export function fakeExecutor(results = {}, onExecute = () => {}) {
  const calls = [];
  return {
    get calls() {
      return calls;
    },
    async execute(invocation) {
      calls.push(invocation);
      onExecute(invocation);
      const preset = results[invocation.toolName];
      if (preset !== undefined) return preset;
      return { status: "SUCCESS", output: { ok: true }, durationMs: 1 };
    },
  };
}

/** 内存事件 sink（记录内部行）。 */
export function memoryEvents() {
  const rows = [];
  return {
    get rows() {
      return rows;
    },
    types() {
      return rows.map((row) => row.type);
    },
    async appendInternal(type, payload) {
      rows.push({ type, payload });
      return rows.length;
    },
  };
}

/** 标准工具规格（与 `filesystem` / `code_exec` 同类）。 */
export const TOOL_SPECS = [
  {
    name: "filesystem",
    description: "文件系统",
    inputSchema: { type: "object", properties: { action: { type: "string" } } },
  },
  {
    name: "code_exec",
    description: "代码执行",
    inputSchema: { type: "object", properties: { code: { type: "string" } } },
  },
];

/** 建一份可用的 `RunCallContext`。 */
export function callContext(limits, options = {}) {
  const ledger = new BudgetLedger(limits);
  const controller = new AbortController();
  return {
    ledger,
    controller,
    context: {
      runId: options.runId ?? "r0000000-0000-4000-8000-000000000001",
      tenantId: "11111111-1111-4111-8111-111111111111",
      signal: controller.signal,
      deadlineMs: Date.now() + (options.deadlineMs ?? 60_000),
      budget: ledger,
      permissions: options.permissions ?? [],
      policyVersion: "test-policy-v1",
    },
  };
}
