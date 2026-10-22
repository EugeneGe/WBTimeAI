/**
 * B2 · `agent` 族的行为证明（SQLite 真库）。
 *
 * 判据（对应 B1 换来的判据纪律 + 任务卡验收）：
 *   ① 值域**手写字面量**：状态 / 版本状态 / 类型三组全集 + 迁移矩阵手写期望表
 *      （第三真源）+ 判定函数非成员必 false；
 *   ② `dialect` 双档：`columns.<列>.columnType` 手写字面量配对（pg `Pg*` vs sqlite `SQLite*`）；
 *   ③ `create` 注入 `DRAFT` + `current_version_id` 恒 null + `type` 缺省 PRIMARY + 租户注入；
 *   ④ `list` 分页 `page`/`page_size` 契约口径（page ≥ 1、page_size 1..100 缺省 20）
 *      + 同秒并列按 `id` 兜底 + 非法值抛；
 *   ⑤ `updateMetadata` 只收 name/description（status 键 ⇒ 抛，后门封死）；
 *   ⑥ `transition` 是状态机唯一入口：矩阵内成功、矩阵外 `null` 且行未变、
 *      词表外与"无来源目标"抛、CAS 二次迁移 `null`、跨租户 ref 进 SQL 前被拒；
 *   ⑦ `publishVersion` 环状外键三步序：版本行 PUBLISHED → 指针回写 → DRAFT→ACTIVE；
 *      版本号缺省 `v{n+1}`；ARCHIVED 再发布复活（py 实证路径）；跨租户决定性夹具
 *      （`863a25c` 风格：铸造合法 + `owns()` 为真 + 行归属仍被拦）；
 *   ⑧ 版本不可变：无 update/delete 入口（结构性 —— 方法不存在即编译不过）。
 *
 * 每个"查不到/只回一条"的断言都配一条**对照路径**，否则"空"可能只是"没插进去"。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  AGENT_LIST_DEFAULT_PAGE,
  AGENT_LIST_DEFAULT_PAGE_SIZE,
  AGENT_LIST_MAX_PAGE_SIZE,
  AGENT_STATUSES,
  AGENT_STATUS_ACTIVE,
  AGENT_STATUS_ARCHIVED,
  AGENT_STATUS_DRAFT,
  AGENT_STATUS_TRANSITIONS,
  AGENT_TYPES,
  AGENT_VERSION_STATUSES,
  AGENT_VERSION_STATUS_PUBLISHED,
  AGENT_TYPE_PRIMARY,
  AgentRepo,
  Scope,
  ScopeError,
  canTransitionStatus,
  isAgentStatus,
  isAgentType,
  isAgentVersionStatus,
} from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";

/** 每例一份新库（父链已灌：两个租户 + 两个用户 + 各自的 agent/版本）。 */
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

/** 直读 `agent` 行（绕过仓储 —— 断言"库里到底有什么"）。 */
function rawAgents(connection, tenantId) {
  return connection.raw
    .prepare("select * from agent where tenant_id = ? order by id")
    .all(tenantId);
}

/** 直读 `agent_version` 行（对照版本表的真实落库形状）。 */
function rawVersions(connection, agentId) {
  return connection.raw
    .prepare("select * from agent_version where agent_id = ? order by id")
    .all(agentId);
}

let seq = 0;
/** 造一个 agent（id 递增，便于手算顺序；`created_by` 用夹具里租户 A 的用户）。 */
function createAgent(repo, overrides = {}) {
  seq += 1;
  return repo.create({
    id: overrides.id ?? `f0000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    name: overrides.name ?? `agent-${seq}`,
    createdBy: IDS.userA,
    ...overrides,
  });
}

let vseq = 0;
/** 给 agent 发一个版本（id 递增）。 */
function publish(repo, agentRef, overrides = {}) {
  vseq += 1;
  return repo.publishVersion(agentRef, {
    id: overrides.id ?? `f0000000-0000-4000-9000-${String(vseq).padStart(12, "0")}`,
    createdBy: IDS.userA,
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
// A · 值域（手写字面量 + 三层判据）
// ---------------------------------------------------------------------------

/** 手写迁移期望表（第三真源；键 = from，值 = 允许的 to 全集）。 */
const EXPECTED_TRANSITIONS = {
  DRAFT: ["ACTIVE", "ARCHIVED"],
  ACTIVE: ["ARCHIVED"],
  ARCHIVED: ["ACTIVE"],
};

test("A · 值域：状态/版本状态/类型手写全集 + 迁移矩阵手写期望表 + 判定函数非成员必 false", () => {
  // ① 集合 deepEqual（手写字面量，逐项同序；顺序 = py constants.py 声明顺序）
  assert.deepEqual([...AGENT_STATUSES], ["DRAFT", "ACTIVE", "ARCHIVED"]);
  assert.deepEqual([...AGENT_VERSION_STATUSES], ["DRAFT", "PUBLISHED", "DEPRECATED"]);
  assert.deepEqual([...AGENT_TYPES], [
    "PRIMARY",
    "SUB_AGENT",
    "WORKFLOW_AGENT",
    "SCHEDULED_AGENT",
    "EVENT_AGENT",
  ]);

  // ② 迁移矩阵：键集合 == 状态全集（少一个状态 = 矩阵对它沉默，这里红）
  assert.deepEqual(Object.keys(AGENT_STATUS_TRANSITIONS).sort(), [...AGENT_STATUSES].sort());

  // ③ 矩阵 vs 手写期望表（第三真源：矩阵与 canTransitionStatus 一起漂移时只有这层会红）
  assert.deepEqual(AGENT_STATUS_TRANSITIONS, EXPECTED_TRANSITIONS);
  for (const [from, tos] of Object.entries(EXPECTED_TRANSITIONS)) {
    for (const to of tos) {
      assert.equal(canTransitionStatus(from, to), true, `${from} → ${to} 必须合法`);
    }
  }
  // 全对全的手写期望表：矩阵外的每一对都必须 false（9 对里只有 4 条合法边）
  const legal = new Set([
    "DRAFT>ACTIVE",
    "DRAFT>ARCHIVED",
    "ACTIVE>ARCHIVED",
    "ARCHIVED>ACTIVE",
  ]);
  for (const from of AGENT_STATUSES) {
    for (const to of AGENT_STATUSES) {
      assert.equal(
        canTransitionStatus(from, to),
        legal.has(`${from}>${to}`),
        `${from} → ${to} 的合法性必须与手写期望一致`,
      );
    }
  }

  // ④ 判定函数：成员 true（逐项）+ 非成员 false（抓"判定恒真"）
  for (const status of AGENT_STATUSES) assert.equal(isAgentStatus(status), true, status);
  for (const status of AGENT_VERSION_STATUSES) {
    assert.equal(isAgentVersionStatus(status), true, status);
  }
  for (const type of AGENT_TYPES) assert.equal(isAgentType(type), true, type);
  for (const bogus of ["", "draft", "ACTIVE ", "PUBLISHED ", "primary"]) {
    assert.equal(isAgentStatus(bogus), false, `非成员必须 false：${JSON.stringify(bogus)}`);
    assert.equal(isAgentVersionStatus(bogus), false, `非成员必须 false：${JSON.stringify(bogus)}`);
    assert.equal(isAgentType(bogus), false, `非成员必须 false：${JSON.stringify(bogus)}`);
  }

  // ⑤ 分页口径手写（契约：page 默认 1；page_size 默认 20、上限 100）
  assert.equal(AGENT_LIST_DEFAULT_PAGE, 1);
  assert.equal(AGENT_LIST_DEFAULT_PAGE_SIZE, 20);
  assert.equal(AGENT_LIST_MAX_PAGE_SIZE, 100);
});

// ---------------------------------------------------------------------------
// B · dialect 双档（真表对象判别式）
// ---------------------------------------------------------------------------

test("B · dialect 双档：columns 的 columnType 是手写字面量且两档不同", () => {
  const { db, scopeA } = seed();
  const sq = new AgentRepo(db, scopeA, "sqlite");
  const pg = new AgentRepo(db, scopeA, "pg");

  assert.equal(sq.tableName, pg.tableName, "两档表同名 ⇒ tableName 没有判别力");
  assert.equal(sq.tableName, "agent");

  assert.equal(sq.columns.status.columnType, "SQLiteText");
  assert.equal(pg.columns.status.columnType, "PgVarchar");
  assert.equal(sq.columns.created_at.columnType, "SQLiteText");
  assert.equal(pg.columns.created_at.columnType, "PgTimestamp");
  assert.equal(sq.columns.current_version_id.columnType, "SQLiteText");
  assert.equal(pg.columns.current_version_id.columnType, "PgUUID");
  assert.notEqual(
    sq.columns.status.columnType,
    pg.columns.status.columnType,
    "两档取到同一列构造器 ⇒ dialect 被忽略",
  );

  // 缺省档 = 生产档 pg
  assert.equal(new AgentRepo(db, scopeA).columns.status.columnType, "PgVarchar");
});

// ---------------------------------------------------------------------------
// C · create：注入 DRAFT / 指针 null / type 缺省 / 租户注入
// ---------------------------------------------------------------------------

test("C · create：status=DRAFT、current_version_id=null、type 缺省 PRIMARY、tenant_id 由 scope 注入", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);

  const created = await createAgent(agents, { description: "测试 agent" });
  assert.equal(created.status, AGENT_STATUS_DRAFT, "契约：创建即 DRAFT");
  assert.equal(created.current_version_id, null, "契约：无当前版本（环状 FK 第一步）");
  assert.equal(created.type, AGENT_TYPE_PRIMARY, "契约 CreateAgentRequest.type default PRIMARY");

  const bare = await createAgent(agents, { description: undefined, type: undefined });
  assert.equal(bare.description, null, "description 缺省 null（契约 anyOf null）");
  assert.equal(bare.type, AGENT_TYPE_PRIMARY);

  const rows = rawAgents(connection, T_A);
  assert.equal(rows.length, 3, "对照路径：夹具 1 条 + 新建 2 条都真的落库了");
  const fresh = rows.filter((row) => row.id !== IDS.agentA);
  for (const row of fresh) {
    assert.equal(row.tenant_id, T_A, "tenant_id 由 scope 注入");
    assert.equal(row.status, AGENT_STATUS_DRAFT);
    assert.equal(row.current_version_id, null);
  }
});

test("C · create：非法 type ⇒ 抛（不静默落库）", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);

  assert.throws(
    () => createAgent(agents, { type: "primary" }),
    (error) => error instanceof ScopeError && /type 必须是/.test(error.message),
  );
  assert.equal(rawAgents(connection, T_A).length, 1, "对照：夹具 1 条，非法行没有落库");
});

// ---------------------------------------------------------------------------
// D · list 分页（page / page_size）
// ---------------------------------------------------------------------------

test("D · list 分页：page/page_size 生效，两页 id 集合不相交，同秒按 id 兜底", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);

  // 刻意让「插入序」与「id 升序」相反（g3 → g2 → g1）：否则"没有 id 兜底键"也能碰巧绿
  const ids = [];
  for (const suffix of [3, 2, 1]) {
    const row = await createAgent(agents, {
      id: `f0000000-0000-4000-8000-00000000010${suffix}`,
    });
    ids.push(row.id);
  }

  // 把 A 租户全部 agent 的时间戳拉平（含夹具那条；CURRENT_TIMESTAMP 秒粒度靠运气不可接受）
  connection.raw
    .prepare(`update agent set created_at = '2026-10-22 00:00:00' where tenant_id = ?`)
    .run(T_A);

  const page1 = await agents.list({ page: 1, pageSize: 2 });
  const page2 = await agents.list({ page: 2, pageSize: 2 });
  assert.equal(page1.length, 2);
  assert.equal(page2.length, 2, "A 租户共 4 条（夹具 1 + 新建 3），第二页满");

  const seen = new Set(page1.map((row) => row.id));
  for (const row of page2) {
    assert.equal(seen.has(row.id), false, "两页不得出现同一行（时间并列时的经典翻页 bug）");
  }
  const allIds = (await agents.list({ pageSize: 100 })).map((row) => row.id);
  assert.deepEqual(allIds.sort(), [...rawAgents(connection, T_A).map((r) => r.id)].sort());

  // 时间并列 ⇒ 次序必须由 id 兜底决定，且两次调用一致
  const again = await agents.list({ page: 1, pageSize: 2 });
  assert.deepEqual(again.map((r) => r.id), page1.map((r) => r.id), "同参数两次调用次序必须一致");
  const sortedAll = allIds.slice().sort();
  assert.deepEqual(page1.map((r) => r.id), sortedAll.slice(0, 2), "第一页 = id 升序前两条");
});

test("D · list：非法 page / page_size ⇒ 抛（不静默夹取）；边界值合法", async () => {
  const { db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);

  for (const page of [0, -1, 1.5, Number.NaN]) {
    assert.throws(
      () => agents.list({ page }),
      (error) => error instanceof ScopeError && /page 非法/.test(error.message),
      `page=${String(page)} 必须抛`,
    );
  }
  for (const pageSize of [0, -1, 101, 2.5, Number.NaN]) {
    assert.throws(
      () => agents.list({ pageSize }),
      (error) => error instanceof ScopeError && /page_size 非法/.test(error.message),
      `page_size=${String(pageSize)} 必须抛`,
    );
  }
  // 边界合法值不抛
  assert.equal((await agents.list({ page: 1, pageSize: 100 })).length, 1, "夹具那条");
});

// ---------------------------------------------------------------------------
// E · updateMetadata：只收 name / description（status 后门封死）
// ---------------------------------------------------------------------------

test("E · updateMetadata：name/description 生效、updated_at 显式推进、缺省字段不变", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  // 把 updated_at 种成远古值：之后断言"变了"就是"真的写过这一列"（不受同秒粒度影响）
  connection.raw
    .prepare(`update agent set updated_at = '2000-01-01 00:00:00' where id = ?`)
    .run(created.id);

  const updated = await agents.updateMetadata(ref, { name: "改名", description: "新描述" });
  assert.equal(updated.name, "改名");
  assert.equal(updated.description, "新描述");
  assert.equal(updated.status, AGENT_STATUS_DRAFT, "缺省字段不变");
  assert.equal(updated.type, AGENT_TYPE_PRIMARY, "缺省字段不变");

  const row = rawAgents(connection, T_A).find((r) => r.id === created.id);
  assert.equal(row.name, "改名");
  assert.ok(row.updated_at > "2000-01-01 00:00:00", "updated_at 必须被显式推进（SQLite 无 ON UPDATE）");
});

test("E · updateMetadata：status 键 ⇒ 抛（状态机后门封死）；跨租户 ref ⇒ 抛", async () => {
  const { connection, db, scopeA, scopeB } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  // updateMetadata 是 async ⇒ 断言必须走 rejects（throws 会漏掉已拒绝的 promise）
  await assert.rejects(
    () => agents.updateMetadata(ref, { status: AGENT_STATUS_ACTIVE }),
    (error) => error instanceof ScopeError && /不支持的字段 status/.test(error.message),
    "status 变更只能走 transition()，updateMetadata 不得成为后门",
  );
  await assert.rejects(
    () => agents.updateMetadata(scopeB.ref(created.id), { name: "x" }),
    (error) => error instanceof ScopeError && /agentRef 不合法/.test(error.message),
    "别的租户铸造的 ref 必须在进 SQL 前被拒",
  );
  // 两条都被拒后行未变
  const row = rawAgents(connection, T_A).find((r) => r.id === created.id);
  assert.equal(row.status, AGENT_STATUS_DRAFT);
  assert.equal(row.name, created.name, "name 未被 B 铸造的 ref 改动");
});

// ---------------------------------------------------------------------------
// F · transition：矩阵 + 原子 CAS
// ---------------------------------------------------------------------------

test("F · 合法迁移逐步成功：DRAFT→ACTIVE→ARCHIVED→ACTIVE，行值与 updated_at 正确", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  const activated = await agents.transition(ref, AGENT_STATUS_ACTIVE, {
    at: "2026-10-22 12:00:00",
  });
  assert.equal(activated.status, AGENT_STATUS_ACTIVE);
  // 显式 at 的落库形状在后续迁移覆盖它**之前**验证（后面的迁移不传 at）
  assert.equal(
    rawAgents(connection, T_A).find((r) => r.id === created.id).updated_at,
    "2026-10-22 12:00:00",
    "显式 at 落库（SQLite 文本形状）",
  );

  const archived = await agents.transition(ref, AGENT_STATUS_ARCHIVED);
  assert.equal(archived.status, AGENT_STATUS_ARCHIVED);
  const revived = await agents.transition(ref, AGENT_STATUS_ACTIVE);
  assert.equal(revived.status, AGENT_STATUS_ACTIVE, "ARCHIVED→ACTIVE 是矩阵内的合法边");
  assert.equal(
    rawAgents(connection, T_A).find((r) => r.id === created.id).status,
    AGENT_STATUS_ACTIVE,
  );
});

test("F · 矩阵外迁移 ⇒ null 且行未变；目标 DRAFT ⇒ 抛（无来源）；词表外 ⇒ 抛", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  // 先启用：ACTIVE 之后回 DRAFT 不在矩阵里（矩阵没有指向 DRAFT 的边）
  assert.equal((await agents.transition(ref, AGENT_STATUS_ACTIVE)).status, AGENT_STATUS_ACTIVE);
  // transition 的校验在发 SQL 之前**同步**抛 ⇒ 用 throws（rejects 抓不到同步异常）
  assert.throws(
    () => agents.transition(ref, AGENT_STATUS_DRAFT),
    (error) => error instanceof ScopeError && /没有任何合法来源/.test(error.message),
    "ACTIVE→DRAFT 矩阵外 ⇒ 目标 DRAFT 无任何来源，直接抛（连 SQL 都不发）",
  );
  let row = rawAgents(connection, T_A).find((r) => r.id === created.id);
  assert.equal(row.status, AGENT_STATUS_ACTIVE, "非法迁移不得改动行");

  // 词表外的值 ⇒ 抛
  for (const bogus of ["active", "PUBLISHED", ""]) {
    assert.throws(
      () => agents.transition(ref, bogus),
      (error) => error instanceof ScopeError && /目标状态必须是/.test(error.message),
      `词表外目标 ${JSON.stringify(bogus)} 必须抛`,
    );
  }
  row = rawAgents(connection, T_A).find((r) => r.id === created.id);
  assert.equal(row.status, AGENT_STATUS_ACTIVE, "抛错路径一行未动");
});

test("F · CAS：同一来源只能迁出一次 —— 第二次同向迁移必须 null", async () => {
  const { db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  const first = await agents.transition(ref, AGENT_STATUS_ACTIVE);
  assert.equal(first.status, AGENT_STATUS_ACTIVE);
  // 第二个"迁移者"仍以为它在 DRAFT：CAS（status IN (DRAFT, ARCHIVED)）必须未命中
  const second = await agents.transition(ref, AGENT_STATUS_ACTIVE);
  assert.equal(second, null, "已 ACTIVE ⇒ 再次 DRAFT→ACTIVE 必须未命中（同 approval.decide 口径）");
});

test("F · transition 跨租户：A 仓储拒 B 铸造的 ref（进 SQL 前）；B 仓储打 A 的行 ⇒ CAS 0 行（404 语义）", async () => {
  const { connection, db, scopeA, scopeB } = seed();
  const agentsA = new AgentRepo(db, scopeA, DIALECT);
  const agentsB = new AgentRepo(db, scopeB, DIALECT);
  const created = await createAgent(agentsA);

  // 方向一：A 的仓储收到 **B 铸造**的 ref ⇒ 铸造来源不同租户，进 SQL 前被拒
  // （transition 的 ref 校验是**同步**抛 ⇒ 用 throws）
  assert.throws(
    () => agentsA.transition(scopeB.ref(created.id), AGENT_STATUS_ACTIVE),
    (error) => error instanceof ScopeError && /agentRef 不合法/.test(error.message),
  );
  assert.equal(
    rawAgents(connection, T_A).find((r) => r.id === created.id).status,
    AGENT_STATUS_DRAFT,
    "A 的行没有被改动",
  );

  // 方向二：B 的仓储收到 **B 铸造**、id 指向 A 的行的 ref ⇒ owns() 放行（它不是
  // 行归属证明），但租户谓词让 CAS 命中 0 行 ⇒ null（I-1：跨租户 404，不是 403）
  assert.equal(
    await agentsB.transition(scopeB.ref(created.id), AGENT_STATUS_ACTIVE),
    null,
  );
  assert.equal(
    rawAgents(connection, T_A).find((r) => r.id === created.id).status,
    AGENT_STATUS_DRAFT,
    "B 的迁移没有改动 A 的行",
  );

  // 本租户内不存在的 id ⇒ CAS 命中 0 行 ⇒ null（不是抛）
  assert.equal(
    await agentsA.transition(scopeA.ref("f0000000-0000-4000-8000-00000000dead"), AGENT_STATUS_ACTIVE),
    null,
  );
});

// ---------------------------------------------------------------------------
// G · publishVersion：环状外键三步序 + PUBLISHED + 状态推进
// ---------------------------------------------------------------------------

test("G · publish：版本行 PUBLISHED、指针回写、DRAFT→ACTIVE；版本号缺省 v{n+1}", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  const v1 = await publish(agents, ref, { systemPrompt: "sys-1", modelConfig: { a: 1 } });
  assert.equal(v1.version, "v1", "缺省版本号 = 既有版本数 + 1（py 同口径）");
  assert.equal(v1.status, AGENT_VERSION_STATUS_PUBLISHED, "契约 AgentVersionResponse.status default");
  assert.equal(v1.system_prompt, "sys-1");
  assert.deepEqual(v1.model_config, { a: 1 });
  assert.equal(v1.agent_id, created.id);

  let row = rawAgents(connection, T_A).find((r) => r.id === created.id);
  assert.equal(row.current_version_id, v1.id, "第三步：指针必须回写");
  assert.equal(row.status, AGENT_STATUS_ACTIVE, "发布即启用（py publish 实证路径）");

  const v2 = await publish(agents, ref, { version: "v9" });
  assert.equal(v2.version, "v9", "显式版本号原样采用");
  row = rawAgents(connection, T_A).find((r) => r.id === created.id);
  assert.equal(row.current_version_id, v2.id, "指针指向最新发布");
  assert.equal(rawVersions(connection, created.id).length, 2, "一次发布 = 一个新行（不可变快照）");
});

test("G · publish 缺省配置列：model_config / runtime_config 落 {} 不是 null（列 NOT NULL）", async () => {
  const { db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);

  const version = await publish(agents, scopeA.ref(created.id));
  assert.deepEqual(version.model_config, {});
  assert.deepEqual(version.runtime_config, {});
  assert.equal(version.system_prompt, "", "契约 PublishRequest.system_prompt default \"\"");
});

test("G · 版本快照：listVersions 升序 + findVersion 归属不符 ⇒ null；发布后旧版本行不变", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  const v1 = await publish(agents, ref, { systemPrompt: "第一版" });
  const v2 = await publish(agents, ref, { systemPrompt: "第二版" });

  // 同秒并列 ⇒ 顺序由 id 兜底；断言按"发布时的版本行内容"认版本，不靠运气
  connection.raw
    .prepare(`update agent_version set created_at = '2026-10-22 00:00:00' where agent_id = ?`)
    .run(created.id);

  const listed = await agents.listVersions(ref);
  assert.deepEqual(
    listed.map((row) => row.system_prompt),
    ["第一版", "第二版"],
    "created_at 升序（py list_by_agent 同向）+ 同秒由 id 兜底",
  );
  const again = await agents.listVersions(ref);
  assert.deepEqual(again.map((r) => r.id), listed.map((r) => r.id), "两次调用次序必须一致");

  const first = await agents.findVersion(ref, v1.id);
  assert.equal(first.system_prompt, "第一版", "发布后旧版本行不变（不可变快照）");
  assert.equal(first.version, v1.version);

  // 归属不符：本租户另一个 agent 的版本 id ⇒ null（py load_version 的 NOT_FOUND 同形）
  const other = await createAgent(agents);
  await publish(agents, scopeA.ref(other.id));
  const otherRow = rawVersions(connection, other.id)[0];
  assert.equal(await agents.findVersion(ref, otherRow.id), null, "版本不属于该 agent ⇒ null");
  assert.equal(await agents.findVersion(ref, "f0000000-0000-4000-9000-00000000dead"), null);
});

test("G · ARCHIVED agent 再发布 ⇒ 复活为 ACTIVE（py 无条件置 ACTIVE 的实证路径）", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);
  const created = await createAgent(agents);
  const ref = scopeA.ref(created.id);

  await agents.transition(ref, AGENT_STATUS_ARCHIVED);
  assert.equal(
    rawAgents(connection, T_A).find((r) => r.id === created.id).status,
    AGENT_STATUS_ARCHIVED,
  );

  await publish(agents, ref);
  const row = rawAgents(connection, T_A).find((r) => r.id === created.id);
  assert.equal(row.status, AGENT_STATUS_ACTIVE, "ARCHIVED→ACTIVE 经由 publish 路径成立");
  assert.ok(row.current_version_id, "指针同时回写");
});

test("G · publish 父不可见 ⇒ 抛且零写入（决定性夹具：跨租户 ref 铸造合法、owns() 为真、行归属仍被拦）", async () => {
  const { connection, db, scopeA, scopeB } = seed();
  const agentsA = new AgentRepo(db, scopeA, DIALECT);

  // IDS.agentB 属租户 B（夹具灌的行）。scopeA 铸造指向它的 ref：
  // 品牌 ✅、owns() ✅（只验铸造来源，不验行归属 —— 见 scoped-repo.ts 的心智模型注释）。
  const forged = scopeA.ref(IDS.agentB);
  assert.equal(forged.tenantId, T_A, "铸造章 = scopeA");
  assert.equal(scopeA.owns(forged), true, "owns() 恒放行 —— 它不是行归属证明（钉住闸门表达边界）");

  // 写/读三路观测 + 行数证据（不用 assert.rejects 前置，避免第一条失败吞掉行数证据）
  const problems = [];
  const before = rawVersions(connection, IDS.agentB).length;
  try {
    await agentsA.publishVersion(forged, { id: "f0000000-0000-4000-9000-00000000bad1", createdBy: IDS.userA });
    problems.push("写路径：publishVersion 成功了 —— 跨租户写泄漏");
  } catch (error) {
    if (!(error instanceof ScopeError)) problems.push(`写路径：抛的不是 ScopeError：${error.message}`);
  }
  try {
    await agentsA.listVersions(forged);
    problems.push("读路径：listVersions 成功了 —— 跨租户读泄漏");
  } catch (error) {
    if (!(error instanceof ScopeError)) problems.push(`读路径：抛的不是 ScopeError：${error.message}`);
  }
  try {
    await agentsA.findVersion(forged, IDS.versionB);
    problems.push("读路径：findVersion 成功了 —— 跨租户读泄漏");
  } catch (error) {
    if (!(error instanceof ScopeError)) problems.push(`读路径：抛的不是 ScopeError：${error.message}`);
  }
  const after = rawVersions(connection, IDS.agentB).length;
  if (after !== before) problems.push(`行数：agentB 名下版本 ${before} → ${after}（有行漏进去）`);

  assert.deepEqual(problems, [], "跨租户三路观测必须全被拦，且一行都不许漏");
  // 对照路径：B 自己的仓储看得到、发得动（证明"拦"是因为租户，不是行坏了）
  const agentsB = new AgentRepo(db, scopeB, DIALECT);
  const ownRef = scopeB.ref(IDS.agentB);
  const listed = await agentsB.listVersions(ownRef);
  assert.equal(listed.length, 1, "对照：B 自己能看到夹具灌的那条版本");
  const published = await publish(agentsB, ownRef, { createdBy: IDS.userB });
  assert.equal(published.status, AGENT_VERSION_STATUS_PUBLISHED, "对照：B 自己发布成功");
  assert.equal(
    rawVersions(connection, IDS.agentB).length,
    2,
    "对照：B 的新版本真的落库了",
  );
});

test("G · 环状外键顺序是结构约束：带非 NULL 指针建 agent 必被 FK 拒（原生对照）", async () => {
  const { connection, db, scopeA } = seed();
  const agents = new AgentRepo(db, scopeA, DIALECT);

  // 第一步必须 NULL：agent.current_version_id → agent_version.id，而版本要 agent 先存在。
  // 原生 SQL 直接构造"指针指向不存在版本"的 agent ⇒ 外键当场拒绝（结构证据，不依赖仓储）。
  assert.throws(
    () =>
      connection.raw
        .prepare(
          `insert into agent (id, tenant_id, organization_id, workspace_id, name, description, type, status, current_version_id, created_by, created_at, updated_at) ` +
            `values ('f0000000-0000-4000-8000-00000000f000', '${T_A}', null, null, 'bad', null, 'PRIMARY', 'DRAFT', 'f0000000-0000-4000-9000-00000000f000', '${IDS.userA}', '2026-10-22 00:00:00', '2026-10-22 00:00:00')`,
        )
        .run(),
    (error) => /FOREIGN KEY|foreign key/i.test(String(error.message)),
    "FK 顺序错误必红：current_version_id 指向不存在的版本必须被数据库拒绝",
  );

  // 对照：仓储 create 恒 NULL（绕不开），该行此后唯一的版本入口是 publishVersion
  const created = await createAgent(agents, { id: "f0000000-0000-4000-8000-00000000f001" });
  assert.equal(created.current_version_id, null);
  const version = await publish(agents, scopeA.ref(created.id));
  assert.equal(
    rawAgents(connection, T_A).find((r) => r.id === created.id).current_version_id,
    version.id,
  );
});
