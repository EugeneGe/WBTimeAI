// @wbtime/domain · Task 实体不变量测试（node:test，零测试框架）。
//
// 运行：`pnpm --filter @wbtime/domain test`（先 `tsc -b` 产出 dist，再跑本文件）。

import assert from "node:assert/strict";
import test from "node:test";

import {
  ALLOWED_TRANSITIONS,
  TASK_COLUMN_LIMITS,
  TASK_STATUSES,
  Task,
  TERMINAL_STATUSES,
} from "../dist/index.js";

const UUID_A = "018f3f6a-7b1c-7c2e-9a11-2f5b0d3e4a01";
const UUID_B = "018f3f6a-7b1c-7c2e-9a11-2f5b0d3e4a02";
const NOW = "2026-10-21T00:00:00.000Z";
const LATER = "2026-10-21T00:00:01.000Z";

const baseInput = {
  id: UUID_A,
  tenantId: UUID_B,
  type: "agent.run",
  now: NOW,
};

test("create：13 个契约列逐一落到 toRecord()", () => {
  const task = Task.create({
    ...baseInput,
    organizationId: UUID_B,
    workspaceId: UUID_B,
    priority: 3,
    executionMode: "QUEUED",
    payload: { a: 1 },
    idempotencyKey: "idem-1",
  });

  const row = task.toRecord();
  assert.deepEqual(Object.keys(row).sort(), [
    "created_at",
    "execution_mode",
    "id",
    "idempotency_key",
    "organization_id",
    "payload",
    "priority",
    "result",
    "status",
    "tenant_id",
    "type",
    "updated_at",
    "workspace_id",
  ]);
  assert.equal(Object.keys(row).length, 13);
  assert.equal(row.status, "CREATED");
  assert.equal(row.execution_mode, "QUEUED");
  assert.equal(row.priority, 3);
  assert.equal(row.created_at, NOW);
  assert.equal(row.updated_at, NOW);
});

test("create：默认值（status/priority/executionMode/可空列）", () => {
  const task = Task.create(baseInput);
  assert.equal(task.status, "CREATED");
  assert.equal(task.priority, 0);
  assert.equal(task.executionMode, "INLINE");
  assert.equal(task.organizationId, null);
  assert.equal(task.workspaceId, null);
  assert.equal(task.payload, null);
  assert.equal(task.result, null);
  assert.equal(task.idempotencyKey, null);
});

test("create：非法 UUID / 空 type / 非整数 priority / 超长列 一律抛 VALIDATION_ERROR", () => {
  const cases = [
    ["id 非 UUID", { ...baseInput, id: "not-a-uuid" }],
    ["tenant_id 非 UUID", { ...baseInput, tenantId: "bad" }],
    ["type 为空", { ...baseInput, type: "" }],
    ["type 超 100", { ...baseInput, type: "x".repeat(TASK_COLUMN_LIMITS.type + 1) }],
    ["priority 非整数", { ...baseInput, priority: 1.5 }],
    [
      "idempotency_key 超 255",
      { ...baseInput, idempotencyKey: "k".repeat(TASK_COLUMN_LIMITS.idempotency_key + 1) },
    ],
    ["execution_mode 非法", { ...baseInput, executionMode: "BATCH" }],
  ];

  for (const [name, input] of cases) {
    assert.throws(
      () => Task.create(input),
      (err) => {
        assert.equal(err.name, "DomainError");
        assert.equal(err.code, "VALIDATION_ERROR");
        return true;
      },
      `用例「${name}」应抛 VALIDATION_ERROR`,
    );
  }
});

test("状态机：合法迁移通过；非法迁移抛 VALIDATION_ERROR（不是静默成功）", () => {
  const created = Task.create(baseInput);

  // CREATED → PENDING（QUEUED 路径）→ RUNNING → SUCCESS
  const pending = created.transitionTo("PENDING", LATER);
  assert.equal(pending.status, "PENDING");
  assert.equal(pending.updatedAt, LATER);
  assert.equal(created.status, "CREATED", "实体不可变：原实例状态不变");

  const running = pending.transitionTo("RUNNING", LATER);
  const success = running.completeWith("SUCCESS", { ok: true }, LATER);
  assert.equal(success.status, "SUCCESS");
  assert.deepEqual(success.result, { ok: true });

  // 非法：CREATED → SUCCESS（跳过中间态）
  assert.throws(
    () => created.transitionTo("SUCCESS"),
    (err) => {
      assert.equal(err.code, "VALIDATION_ERROR");
      assert.equal(err.data.from, "CREATED");
      assert.equal(err.data.to, "SUCCESS");
      return true;
    },
  );

  // 非法：终态不可再迁移
  assert.throws(() => success.transitionTo("RUNNING"), (err) => err.code === "VALIDATION_ERROR");
  assert.ok(TERMINAL_STATUSES.has("SUCCESS"));
});

test("状态机：INLINE 路径 CREATED → RUNNING 合法（跳过 PENDING）", () => {
  const task = Task.create(baseInput);
  assert.ok(task.canTransitionTo("RUNNING"));
  assert.ok(ALLOWED_TRANSITIONS.CREATED.includes("RUNNING"));
  assert.equal(task.transitionTo("RUNNING", LATER).status, "RUNNING");
});

test("状态枚举：6 值齐全，终态 3 个且出度为 0", () => {
  assert.deepEqual([...TASK_STATUSES], [
    "CREATED",
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "CANCELLED",
  ]);
  for (const s of TERMINAL_STATUSES) {
    assert.deepEqual([...ALLOWED_TRANSITIONS[s]], [], `终态 ${s} 出度必须为 0`);
  }
});

test("fromRecord：脏行（非法状态值）不得进入域", () => {
  const row = Task.create(baseInput).toRecord();
  assert.equal(Task.fromRecord(row).id, UUID_A);

  assert.throws(
    () => Task.fromRecord({ ...row, status: "WEIRD" }),
    (err) => err.code === "VALIDATION_ERROR",
  );
  assert.throws(
    () => Task.fromRecord({ ...row, tenant_id: "not-a-uuid" }),
    (err) => err.code === "VALIDATION_ERROR",
  );
});

// ---------------------------------------------------------------------------
// completeWith：注释写的是「仅 RUNNING 路径的结果落库」，实现必须同样窄
// ---------------------------------------------------------------------------

test("completeWith：非 RUNNING 状态写入结果一律 VALIDATION_ERROR", () => {
  const created = Task.create(baseInput);

  // PENDING → FAILED 在状态机上是**合法**迁移，但不该带执行结果。
  const pending = created.transitionTo("PENDING", LATER);
  assert.throws(
    () => pending.completeWith("FAILED", { reason: "x" }, LATER),
    (err) => {
      assert.equal(err.name, "DomainError");
      assert.equal(err.code, "VALIDATION_ERROR");
      assert.equal(err.data.from, "PENDING");
      assert.equal(err.data.to, "FAILED");
      assert.match(err.message, /RUNNING/);
      return true;
    },
  );

  // CREATED → CANCELLED 同样合法，同样不允许携带结果。
  assert.throws(
    () => created.completeWith("CANCELLED", null, LATER),
    (err) => {
      assert.equal(err.code, "VALIDATION_ERROR");
      assert.equal(err.data.from, "CREATED");
      assert.equal(err.data.to, "CANCELLED");
      return true;
    },
  );
});

test("completeWith：RUNNING → SUCCESS 仍正常写入结果（收窄不误伤主路径）", () => {
  const running = Task.create(baseInput).transitionTo("RUNNING", LATER);
  const done = running.completeWith("SUCCESS", { ok: true }, LATER);
  assert.equal(done.status, "SUCCESS");
  assert.deepEqual(done.result, { ok: true });
  assert.equal(running.result, null, "实体不可变：原实例结果不变");
});
