/**
 * B2 · `approval` 族的行为证明（SQLite 真库）。
 *
 * 判据（对应裁定 + B1 换来的判据纪律）：
 *   ① 值域**手写字面量**：状态全集 / 终态集合 / 判定函数，三层（集合 deepEqual、
 *      函数 vs 本侧集合、函数 vs 手写期望表）+ 非成员必 false；
 *   ② `dialect` 双档：`columns.<列>.columnType` 手写字面量配对（pg `Pg*` vs sqlite `SQLite*`）；
 *   ③ `create` 注入 `status=PENDING` + `decided_*` 落 null + `payload` 缺省 `{}` + 租户由 scope 注入；
 *   ④ `listPending` **只回 PENDING**（先造一条已决议的做对照，证明是过滤不是"没有"）；
 *   ⑤ 分页 `limit`/`offset` 契约口径（1..200 缺省 50、offset ≥ 0）+ 同秒并列按 `id` 兜底；
 *   ⑥ 决议是 CAS：`PENDING → 终态`只能一次，第二次必须 `null` 且**行没变**；
 *   ⑦ 非法 `limit` / `offset` / 非终态目标 / 空决议人 ⇒ 抛（不静默修正）。
 *
 * 每个"查不到/只回一条"的断言都配一条**对照路径**，否则"空"可能只是"没插进去"。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  APPROVAL_LIST_DEFAULT_LIMIT,
  APPROVAL_LIST_MAX_LIMIT,
  APPROVAL_STATUSES,
  APPROVAL_STATUS_APPROVED,
  APPROVAL_STATUS_EXPIRED,
  APPROVAL_STATUS_PENDING,
  APPROVAL_STATUS_REJECTED,
  APPROVAL_SUBJECT_TYPES,
  APPROVAL_TERMINAL_STATUSES,
  ApprovalRepo,
  Scope,
  ScopeError,
  isTerminalApprovalStatus,
} from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";

/** 每例一份新库（父链已灌：两个租户 + 两个用户）。 */
function seed() {
  const connection = freshConnection();
  seedParents(connection);
  return {
    connection,
    db: connection.db,
    scopeA: new Scope(T_A),
    scopeB: new Scope(T_B),
  };
}

/** 直读 `approval` 行（绕过仓储 —— 断言"库里到底有什么"）。 */
function rawApprovals(connection, tenantId) {
  return connection.raw
    .prepare("select * from approval where tenant_id = ? order by id")
    .all(tenantId);
}

/** 手写期望：状态 ⇒ 是否终态（4 值全覆盖；**不引用注册表**）。 */
const EXPECTED_TERMINAL = {
  PENDING: false,
  APPROVED: true,
  REJECTED: true,
  EXPIRED: true,
};

let seq = 0;
/** 造一条审批（id 递增，便于手算顺序）。 */
function createApproval(repo, overrides = {}) {
  seq += 1;
  return repo.create({
    id: overrides.id ?? `e0000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    subjectType: "tool",
    subjectRef: "tool-ref-1",
    requestedBy: IDS.userA,
    payload: { reason: "需要执行 shell" },
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
// A · 值域（手写字面量 + 三层判据）
// ---------------------------------------------------------------------------

test("A · 状态值域：手写 4 值同序 + 终态 3 值 + 判定函数三层判据", () => {
  // ① 集合 deepEqual（手写字面量，逐项同序）
  assert.deepEqual([...APPROVAL_STATUSES], ["PENDING", "APPROVED", "REJECTED", "EXPIRED"]);
  assert.deepEqual([...APPROVAL_TERMINAL_STATUSES], ["APPROVED", "REJECTED", "EXPIRED"]);

  // ② 手写期望表必须覆盖全集（少一个状态在这里就红）
  assert.deepEqual(Object.keys(EXPECTED_TERMINAL).sort(), [...APPROVAL_STATUSES].sort());

  for (const status of APPROVAL_STATUSES) {
    const want = EXPECTED_TERMINAL[status];
    // ③ 判定函数 == 手写期望（第三真源：集合与函数一起漂移时只有这层会红）
    assert.equal(isTerminalApprovalStatus(status), want, `isTerminalApprovalStatus(${status})`);
    // ④ 判定函数 == 本侧集合成员关系
    assert.equal(
      isTerminalApprovalStatus(status),
      APPROVAL_TERMINAL_STATUSES.includes(status),
      `判定函数与终态集合不一致：${status}`,
    );
  }

  // ⑤ 非成员一律 false（抓"判定恒真"）
  for (const bogus of ["", "PENDING ", "approved", "APPROVED "]) {
    assert.equal(isTerminalApprovalStatus(bogus), false, `非成员必须 false：${JSON.stringify(bogus)}`);
  }

  // ⑥ 主体类型清单手写（契约用例：tool / mcp / workflow_node）
  assert.deepEqual([...APPROVAL_SUBJECT_TYPES], ["tool", "mcp", "workflow_node"]);

  // ⑦ 分页口径手写（契约：limit ∈ [1,200] 默认 50）
  assert.equal(APPROVAL_LIST_DEFAULT_LIMIT, 50);
  assert.equal(APPROVAL_LIST_MAX_LIMIT, 200);
});

// ---------------------------------------------------------------------------
// B · dialect 双档（真表对象判别式）
// ---------------------------------------------------------------------------

test("B · dialect 双档：columns 的 columnType 是手写字面量且两档不同", () => {
  const { db, scopeA } = seed();
  const sq = new ApprovalRepo(db, scopeA, "sqlite");
  const pg = new ApprovalRepo(db, scopeA, "pg");

  assert.equal(sq.tableName, pg.tableName, "两档表同名 ⇒ tableName 没有判别力");
  assert.equal(sq.tableName, "approval");

  assert.equal(sq.columns.status.columnType, "SQLiteText");
  assert.equal(pg.columns.status.columnType, "PgVarchar");
  assert.equal(sq.columns.created_at.columnType, "SQLiteText");
  assert.equal(pg.columns.created_at.columnType, "PgTimestamp");
  assert.equal(sq.columns.payload.columnType, "SQLiteTextJson");
  assert.equal(pg.columns.payload.columnType, "PgJsonb");
  assert.equal(sq.columns.decided_at.columnType, "SQLiteText");
  assert.equal(pg.columns.decided_at.columnType, "PgTimestamp");
  assert.notEqual(
    sq.columns.status.columnType,
    pg.columns.status.columnType,
    "两档取到同一列构造器 ⇒ dialect 被忽略",
  );

  // 缺省档 = 生产档 pg
  assert.equal(new ApprovalRepo(db, scopeA).columns.status.columnType, "PgVarchar");
});

// ---------------------------------------------------------------------------
// C · create：注入 PENDING / 决议列 null / payload 缺省 / 租户注入
// ---------------------------------------------------------------------------

test("C · create：status=PENDING、decided_* 为 null、payload 缺省 {}、tenant_id 由 scope 注入", async () => {
  const { connection, db, scopeA } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);

  const created = await createApproval(approvals);
  assert.equal(created.status, APPROVAL_STATUS_PENDING, "契约 default：PENDING");
  assert.equal(created.decided_by, null, "新建即 PENDING ⇒ 决议人必须为 null");
  assert.equal(created.decided_at, null, "新建即 PENDING ⇒ 决议时刻必须为 null");

  const bare = await createApproval(approvals, { payload: undefined, subjectType: undefined, subjectRef: undefined });
  assert.deepEqual(bare.payload, {}, "payload 列 NOT NULL ⇒ 缺省 {}，不是 null");
  assert.equal(bare.subject_type, "", "契约 subject_type default \"\"");
  assert.equal(bare.subject_ref, "", "契约 subject_ref default \"\"");

  const rows = rawApprovals(connection, T_A);
  assert.equal(rows.length, 2, "对照路径：两条都真的落库了");
  for (const row of rows) {
    assert.equal(row.tenant_id, T_A, "tenant_id 由 scope 注入");
    assert.equal(row.status, APPROVAL_STATUS_PENDING);
  }
});

// ---------------------------------------------------------------------------
// D · listPending：只回 PENDING（含对照）
// ---------------------------------------------------------------------------

test("D · listPending 只回 PENDING：已决议的那条在库里但不出现在列表里", async () => {
  const { connection, db, scopeA } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);

  const pending = await createApproval(approvals);
  const toDecide = await createApproval(approvals);
  const decided = await approvals.approve(scopeA.ref(toDecide.id), IDS.userA);
  assert.equal(decided.status, APPROVAL_STATUS_APPROVED);

  // 对照路径：库里确实有 2 行（否则下面的"只 1 条"可能是"没插进去"）
  assert.equal(rawApprovals(connection, T_A).length, 2);

  const listed = await approvals.listPending();
  assert.equal(listed.length, 1, "契约：GET /approvals 只返回 PENDING");
  assert.equal(listed[0].id, pending.id);
  assert.equal(listed[0].status, APPROVAL_STATUS_PENDING);

  // 按主体查则两条都能看到（证明是被 status 过滤掉的，不是被主体过滤）
  const bySubject = await approvals.listBySubject("tool", "tool-ref-1");
  assert.equal(bySubject.length, 2);
});

test("D · listPending 分页：limit / offset 生效，两页 id 集合不相交", async () => {
  const { connection, db, scopeA } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);

  // 刻意让「插入序」与「id 升序」相反（c3 → c2 → c1）：否则"没有 id 兜底键"也能碰巧绿
  const ids = [];
  for (const suffix of [3, 2, 1]) {
    const row = await createApproval(approvals, {
      id: `e0000000-0000-4000-8000-00000000000${suffix}`,
    });
    ids.push(row.id);
  }
  const sortedIds = [...ids].sort();

  // 把三条的时间戳显式拉平（CURRENT_TIMESTAMP 是秒粒度，靠运气同秒不可接受）
  connection.raw
    .prepare(`update approval set created_at = '2026-10-22 00:00:00' where tenant_id = ?`)
    .run(T_A);

  const page1 = await approvals.listPending({ limit: 2 });
  const page2 = await approvals.listPending({ limit: 2, offset: 2 });
  assert.equal(page1.length, 2);
  assert.equal(page2.length, 1);

  const seen = new Set(page1.map((row) => row.id));
  for (const row of page2) {
    assert.equal(seen.has(row.id), false, "两页不得出现同一行（时间并列时的经典翻页 bug）");
  }
  assert.deepEqual(
    [...ids].sort(),
    [...page1.map((r) => r.id), ...page2.map((r) => r.id)].sort(),
    "两页合起来必须恰好是全部 3 条",
  );

  // 时间并列 ⇒ 次序必须由 id 兜底决定，且两次调用一致
  const again = await approvals.listPending({ limit: 2 });
  assert.deepEqual(again.map((r) => r.id), page1.map((r) => r.id), "同参数两次调用次序必须一致");
  assert.deepEqual(page1.map((r) => r.id), sortedIds.slice(0, 2), "时间全并列时第一页 = id 升序前两条");
  assert.deepEqual(page2.map((r) => r.id), sortedIds.slice(2), "第二页 = id 升序剩下那条");
});

// ---------------------------------------------------------------------------
// E · 决议 CAS（不可重复决议）
// ---------------------------------------------------------------------------

test("E · approve 一次成功、第二次 null 且行未被改动（CAS 打在 status=PENDING 上）", async () => {
  const { connection, db, scopeA } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);
  const created = await createApproval(approvals);

  const first = await approvals.approve(scopeA.ref(created.id), IDS.userA);
  assert.equal(first.status, APPROVAL_STATUS_APPROVED);
  assert.equal(first.decided_by, IDS.userA);
  assert.ok(first.decided_at, "决议时刻必须落库");

  const second = await approvals.approve(scopeA.ref(created.id), IDS.userB);
  assert.equal(second, null, "已决议 ⇒ 第二次必须 null（不得再改决议人）");

  const row = rawApprovals(connection, T_A)[0];
  assert.equal(row.status, APPROVAL_STATUS_APPROVED, "行仍是 APPROVED");
  assert.equal(row.decided_by, IDS.userA, "决议人不得被第二次覆盖");
});

test("E · reject 走同一 CAS：PENDING → REJECTED", async () => {
  const { db, scopeA } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);
  const created = await createApproval(approvals);

  const rejected = await approvals.reject(scopeA.ref(created.id), IDS.userA);
  assert.equal(rejected.status, APPROVAL_STATUS_REJECTED);
  assert.equal(await approvals.reject(scopeA.ref(created.id), IDS.userA), null);
  assert.equal(
    (await approvals.listPending()).length,
    0,
    "驳回后不再出现在待办列表",
  );
});

test("E · decide 参数校验：非终态目标 / 空决议人 / 跨租户 ref 一律抛", async () => {
  const { db, scopeA, scopeB } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);
  const created = await createApproval(approvals);
  const ref = scopeA.ref(created.id);

  assert.throws(
    () => approvals.decide(ref, { status: APPROVAL_STATUS_PENDING, decidedBy: IDS.userA }),
    (error) => error instanceof ScopeError && /必须是终态/.test(error.message),
    "PENDING 只能作迁移起点",
  );
  assert.throws(
    () => approvals.decide(ref, { status: APPROVAL_STATUS_APPROVED, decidedBy: "  " }),
    (error) => error instanceof ScopeError && /decidedBy 必须是非空用户 id/.test(error.message),
  );
  assert.throws(
    () => approvals.decide(scopeB.ref(created.id), { status: APPROVAL_STATUS_APPROVED, decidedBy: IDS.userA }),
    (error) => error instanceof ScopeError && /approvalRef 不合法/.test(error.message),
    "别的租户铸造的 ref 必须在进 SQL 前被拒",
  );

  // 未命中 id（本租户内不存在的 id）⇒ null，不是抛
  assert.equal(
    await approvals.approve(scopeA.ref("e0000000-0000-4000-8000-00000000dead"), IDS.userA),
    null,
  );
});

// ---------------------------------------------------------------------------
// F · 隔离 + 分页参数校验
// ---------------------------------------------------------------------------

test("F · 跨租户：B 的仓储看不到 A 的审批（对照：A 自己看得到）", async () => {
  const { connection, db, scopeA, scopeB } = seed();
  const approvalsA = new ApprovalRepo(db, scopeA, DIALECT);
  const approvalsB = new ApprovalRepo(db, scopeB, DIALECT);

  const created = await createApproval(approvalsA);
  assert.equal((await approvalsA.listPending()).length, 1, "对照路径：A 看得到自己那条");
  assert.deepEqual(await approvalsB.listPending(), [], "B 的待办列表里不得出现 A 的行");
  assert.equal(await approvalsB.findById(scopeB.ref(created.id)), null, "按 id 也查不到");
  assert.equal(rawApprovals(connection, T_A).length, 1, "行确实在 A 租户下");

  // 决议也跨不过去：B 用自己铸造的 ref 打 A 的 id ⇒ CAS 命中 0 行
  assert.equal(await approvalsB.approve(scopeB.ref(created.id), IDS.userB), null);
  assert.equal(rawApprovals(connection, T_A)[0].status, APPROVAL_STATUS_PENDING, "A 的行未被 B 改动");
});

test("F · 非法 limit / offset ⇒ 抛（不静默夹取）", async () => {
  const { db, scopeA } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);

  for (const limit of [0, -1, 201, 1.5, Number.NaN]) {
    assert.throws(
      () => approvals.listPending({ limit }),
      (error) => error instanceof ScopeError && /limit 非法/.test(error.message),
      `limit=${String(limit)} 必须抛`,
    );
  }
  for (const offset of [-1, 0.5, Number.NaN]) {
    assert.throws(
      () => approvals.listPending({ offset }),
      (error) => error instanceof ScopeError && /offset 非法/.test(error.message),
      `offset=${String(offset)} 必须抛`,
    );
  }
  // 边界合法值不抛
  assert.equal((await approvals.listPending({ limit: 200, offset: 0 })).length, 0);
});

test("F · EXPIRED 也能经 decide 落地（过期任务复用同一入口，仓储不新增方法）", async () => {
  const { connection, db, scopeA } = seed();
  const approvals = new ApprovalRepo(db, scopeA, DIALECT);
  const created = await createApproval(approvals);

  const expired = await approvals.decide(scopeA.ref(created.id), {
    status: APPROVAL_STATUS_EXPIRED,
    decidedBy: IDS.userA,
  });
  assert.equal(expired.status, APPROVAL_STATUS_EXPIRED);
  assert.equal(rawApprovals(connection, T_A)[0].status, APPROVAL_STATUS_EXPIRED);
  assert.equal((await approvals.listPending()).length, 0, "过期后退出待办列表");
});
