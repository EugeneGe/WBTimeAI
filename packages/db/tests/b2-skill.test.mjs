/**
 * B2 · `skill` 族行为证明（`skill` + `skill_version`，SQLite 真库）。
 *
 * 判据（裁定 ⑤ + B1 判据纪律）：
 *   ① 两套状态值域**手写字面量** + 判定函数三层；
 *   ② `dialect` 双档：`columns.<列>.columnType` 手写字面量配对；
 *   ③ `create` 注入 `DRAFT`、`current_version_id` **恒 null**、租户由 scope 注入；
 *   ④ **环状外键的插入序是结构约束**：两个方向都被数据库拒（raw 直插举证），
 *      再证明仓储走通的唯一序列 `skill(null) → version → UPDATE current`；
 *   ⑤ `createVersion` 父不可见 ⇒ `ScopeError` 且**不落库**；版本号复用 ⇒ 抛；
 *   ⑥ `listVersions` 父域隔离（同租户两个 skill 互不可见）+ 同秒并列按 `id` 兜底；
 *   ⑦ 不可变口径：版本只有 `status` 可迁移，内容列无入口可改；
 *   ⑧ `publish` = 冻结最新 `DRAFT` + 更新 `current_version_id`，无 DRAFT ⇒ `null`。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  Scope,
  ScopeError,
  SKILL_STATUSES,
  SKILL_STATUS_ACTIVE,
  SKILL_STATUS_ARCHIVED,
  SKILL_STATUS_DRAFT,
  SKILL_VERSION_STATUSES,
  SKILL_VERSION_STATUS_DRAFT,
  SKILL_VERSION_STATUS_PUBLISHED,
  SkillRepo,
  isSkillStatus,
  isSkillVersionStatus,
} from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";

function seed() {
  const connection = freshConnection();
  seedParents(connection);
  return { connection, db: connection.db, scopeA: new Scope(T_A), scopeB: new Scope(T_B) };
}

/** 直读 skill_version 行数（绕过仓储）。 */
function rawVersionCount(connection) {
  return Number(connection.raw.prepare("select count(*) as n from skill_version").get().n);
}

/** 手写期望：状态 ⇒ 是否"skill 生命周期值"（3 值全覆盖）。 */
const EXPECTED_SKILL_STATUS = { DRAFT: true, ACTIVE: true, ARCHIVED: true };

/** 手写期望：版本状态 ⇒ 是否"版本状态值"（2 值全覆盖）。 */
const EXPECTED_VERSION_STATUS = { DRAFT: true, PUBLISHED: true };

let seq = 0;
function newSkill(repo, overrides = {}) {
  seq += 1;
  return repo.create({
    id: overrides.id ?? `f0000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    name: overrides.name ?? `skill-${seq}`,
    displayName: "技能",
    category: "ops",
    createdBy: IDS.userA,
    ...overrides,
  });
}

function newVersion(repo, skillRef, overrides = {}) {
  seq += 1;
  return repo.createVersion(skillRef, {
    id: overrides.id ?? `f1000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    version: overrides.version ?? `v${seq}`,
    instructions: "做点什么",
    manifest: { entry: "main.md" },
    createdBy: IDS.userA,
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
// A · 值域
// ---------------------------------------------------------------------------

test("A · 两套值域手写字面量：skill 3 值 / 版本 2 值 + 判定函数三层", () => {
  assert.deepEqual([...SKILL_STATUSES], ["DRAFT", "ACTIVE", "ARCHIVED"]);
  assert.deepEqual([...SKILL_VERSION_STATUSES], ["DRAFT", "PUBLISHED"]);
  assert.equal(SKILL_STATUS_DRAFT, "DRAFT");
  assert.equal(SKILL_VERSION_STATUS_DRAFT, "DRAFT", "两侧 DRAFT 同字面量，但属于两套值域");
  assert.equal(SKILL_VERSION_STATUS_PUBLISHED, "PUBLISHED");
  assert.equal(SKILL_STATUS_ACTIVE, "ACTIVE");
  assert.equal(SKILL_STATUS_ARCHIVED, "ARCHIVED");

  assert.deepEqual(Object.keys(EXPECTED_SKILL_STATUS).sort(), [...SKILL_STATUSES].sort());
  assert.deepEqual(Object.keys(EXPECTED_VERSION_STATUS).sort(), [...SKILL_VERSION_STATUSES].sort());

  for (const status of SKILL_STATUSES) {
    assert.equal(isSkillStatus(status), EXPECTED_SKILL_STATUS[status], `isSkillStatus(${status})`);
    assert.equal(isSkillStatus(status), SKILL_STATUSES.includes(status), `函数 vs 集合：${status}`);
  }
  for (const status of SKILL_VERSION_STATUSES) {
    assert.equal(
      isSkillVersionStatus(status),
      EXPECTED_VERSION_STATUS[status],
      `isSkillVersionStatus(${status})`,
    );
    assert.equal(
      isSkillVersionStatus(status),
      SKILL_VERSION_STATUSES.includes(status),
      `函数 vs 集合：${status}`,
    );
  }

  // 非成员（含两套值域的交叉污染：ACTIVE 不是版本状态，PUBLISHED 不是 skill 生命周期）
  for (const bogus of ["", "draft", "DRAFT "]) {
    assert.equal(isSkillStatus(bogus), false, `skill 非成员：${JSON.stringify(bogus)}`);
  }
  assert.equal(isSkillStatus("PUBLISHED"), false, "PUBLISHED 是版本状态，不是 skill 生命周期值");
  assert.equal(isSkillVersionStatus("ACTIVE"), false, "ACTIVE 是 skill 生命周期值，不是版本状态");
  assert.equal(isSkillVersionStatus("ARCHIVED"), false);
});

// ---------------------------------------------------------------------------
// B · dialect 双档
// ---------------------------------------------------------------------------

test("B · dialect 双档：skill 表列构造器手写字面量配对（缺省 pg）", () => {
  const { db, scopeA } = seed();
  const sq = new SkillRepo(db, scopeA, "sqlite");
  const pg = new SkillRepo(db, scopeA, "pg");

  assert.equal(sq.tableName, pg.tableName, "两档同名 ⇒ tableName 无判别力");
  assert.equal(sq.tableName, "skill");
  assert.equal(sq.columns.status.columnType, "SQLiteText");
  assert.equal(pg.columns.status.columnType, "PgVarchar");
  assert.equal(sq.columns.created_at.columnType, "SQLiteText");
  assert.equal(pg.columns.created_at.columnType, "PgTimestamp");
  assert.equal(sq.columns.current_version_id.columnType, "SQLiteText");
  assert.equal(pg.columns.current_version_id.columnType, "PgUUID");
  assert.notEqual(sq.columns.status.columnType, pg.columns.status.columnType);
  assert.equal(new SkillRepo(db, scopeA).columns.status.columnType, "PgVarchar", "缺省档必须是 pg");
});

// ---------------------------------------------------------------------------
// C · create
// ---------------------------------------------------------------------------

test("C · create：status 缺省 DRAFT、current_version_id 恒 null、缺省串字段、租户注入", async () => {
  const { connection, db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);

  const created = await newSkill(skills, { displayName: undefined, category: undefined });
  assert.equal(created.status, SKILL_STATUS_DRAFT, "契约 default：DRAFT");
  assert.equal(created.current_version_id, null, "环状外键：新 skill 不可能已有当前版本");
  assert.equal(created.display_name, "");
  assert.equal(created.category, "");
  assert.equal(created.description, null);
  assert.equal(created.tenant_id, T_A);

  const row = connection.raw.prepare("select * from skill where id = ?").get(created.id);
  assert.ok(row, "对照路径：行真的落库了");
  assert.equal(row.tenant_id, T_A);

  assert.throws(
    () => skills.create({ id: "x", name: "y", createdBy: IDS.userA, status: "PUBLISHED" }),
    (error) => error instanceof ScopeError && /status 必须是 DRAFT \| ACTIVE \| ARCHIVED/.test(error.message),
    "PUBLISHED 不是 skill 生命周期值（两套值域不许串）",
  );
});

// ---------------------------------------------------------------------------
// D · 环状外键：插入序是结构约束
// ---------------------------------------------------------------------------

test("D · 环状外键：两个方向都被数据库拒 ⇒ 唯一可行序列 skill(null) → version → UPDATE", async () => {
  const { connection, db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);
  const raw = connection.raw;

  // 方向一：版本先于 skill ⇒ skill_id 悬空
  assert.throws(
    () =>
      raw.exec(
        `insert into skill_version (id, skill_id, version, instructions, manifest, status, created_by) ` +
          `values ('99990000-0000-4000-8000-000000000001', '99990000-0000-4000-8000-0000000000aa', ` +
          `'v1', 'x', '{}', 'DRAFT', '${IDS.userA}')`,
      ),
    /FOREIGN KEY|constraint/i,
    "skill_version.skill_id 指向尚不存在的 skill ⇒ 必须被外键拒（先建版本这条路是堵死的）",
  );

  // 方向二：skill 一步到位指向不存在的版本 ⇒ current_version_id 悬空
  assert.throws(
    () =>
      raw.exec(
        `insert into skill (id, tenant_id, name, display_name, category, status, current_version_id, created_by) ` +
          `values ('99990000-0000-4000-8000-000000000002', '${T_A}', 'one-shot', 'd', 'c', 'DRAFT', ` +
          `'99990000-0000-4000-8000-0000000000bb', '${IDS.userA}')`,
      ),
    /FOREIGN KEY|constraint/i,
    "skill.current_version_id 指向尚不存在的版本 ⇒ 必须被外键拒（不能「一步到位」）",
  );

  assert.equal(rawVersionCount(connection), 0, "两次失败都不得留下半行");
  assert.equal(Number(raw.prepare("select count(*) as n from skill").get().n), 0);

  // 唯一可行序列：仓储按 1→2→3 走通
  const skill = await newSkill(skills, { name: "circular" });
  assert.equal(skill.current_version_id, null, "第 1 步：skill 先以 null 落地");
  const version = await newVersion(skills, scopeA.ref(skill.id), { version: "1.0.0" });
  assert.equal(version.skill_id, skill.id, "第 2 步：版本挂到已存在的 skill 上");
  const published = await skills.publish(scopeA.ref(skill.id));
  assert.equal(published.id, version.id, "第 3 步：发布即把指针指过去");
  const after = await skills.findById(scopeA.ref(skill.id));
  assert.equal(after.current_version_id, version.id, "current_version_id 指向刚发布的版本");
});

// ---------------------------------------------------------------------------
// E · createVersion 的父域与版本号唯一
// ---------------------------------------------------------------------------

test("E · createVersion：父不存在 ⇒ ScopeError 且不落库（对照：真实父可写）", async () => {
  const { connection, db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);

  const ghost = scopeA.ref("f0000000-0000-4000-8000-00000000dead");
  await assert.rejects(
    () => newVersion(skills, ghost, { version: "9.9.9" }),
    (error) => {
      assert.ok(error instanceof ScopeError, `必须是 ScopeError，实测 ${String(error)}`);
      assert.match(error.message, /父 skill .* 在本 scope 下不可见/);
      return true;
    },
  );
  assert.equal(rawVersionCount(connection), 0, "父不可见时一行都不许落库");
  assert.equal(Number(connection.raw.prepare("select count(*) as n from skill").get().n), 0);

  // 对照路径
  const skill = await newSkill(skills);
  const version = await newVersion(skills, scopeA.ref(skill.id));
  assert.equal(version.status, SKILL_VERSION_STATUS_DRAFT, "新版本恒为 DRAFT（契约 default）");
  assert.equal(rawVersionCount(connection), 1);
});

test("E · 版本号复用 ⇒ 抛（uq_skill_version_skill_version 的应用层前置检查）", async () => {
  const { db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);
  const a = await newSkill(skills, { name: "a" });
  const b = await newSkill(skills, { name: "b" });

  await newVersion(skills, scopeA.ref(a.id), { version: "1.0.0" });
  await assert.rejects(
    () => newVersion(skills, scopeA.ref(a.id), { version: "1.0.0" }),
    (error) => error instanceof ScopeError && /版本号不可复用/.test(error.message),
  );

  // 对照：另一个 skill 用同一个版本号是完全合法的（唯一约束是 (skill_id, version)）
  const other = await newVersion(skills, scopeA.ref(b.id), { version: "1.0.0" });
  assert.equal(other.skill_id, b.id);
});

// ---------------------------------------------------------------------------
// F · listVersions 隔离 + 排序
// ---------------------------------------------------------------------------

test("F · listVersions：同租户两个 skill 互不可见（对照：各自看得到自己那条）", async () => {
  const { db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);
  const a = await newSkill(skills, { name: "a" });
  const b = await newSkill(skills, { name: "b" });
  const va = await newVersion(skills, scopeA.ref(a.id), { version: "1.0.0" });
  const vb = await newVersion(skills, scopeA.ref(b.id), { version: "1.0.0" });

  assert.deepEqual((await skills.listVersions(scopeA.ref(a.id))).map((v) => v.id), [va.id]);
  assert.deepEqual((await skills.listVersions(scopeA.ref(b.id))).map((v) => v.id), [vb.id]);
  // 父域隔离：按版本号查也只在父内命中
  assert.equal(await skills.findVersion(scopeA.ref(a.id), "2.0.0"), null);
  assert.ok(await skills.findVersion(scopeA.ref(a.id), "1.0.0"));
});

test("F · listVersions 同秒并列 ⇒ 按 id 兜底且两次调用一致", async () => {
  const { connection, db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);
  const skill = await newSkill(skills);
  // 刻意让「插入序」与「id 升序」相反：否则去掉 id 兜底键也能碰巧绿
  const first = await newVersion(skills, scopeA.ref(skill.id), {
    id: "f1000000-0000-4000-8000-000000000002",
    version: "1.0.0",
  });
  const second = await newVersion(skills, scopeA.ref(skill.id), {
    id: "f1000000-0000-4000-8000-000000000001",
    version: "2.0.0",
  });

  // 显式拉平时间戳（CURRENT_TIMESTAMP 是秒粒度，不靠运气）
  connection.raw
    .prepare("update skill_version set created_at = '2026-10-22 00:00:00' where skill_id = ?")
    .run(skill.id);

  const listed = await skills.listVersions(scopeA.ref(skill.id));
  const again = await skills.listVersions(scopeA.ref(skill.id));
  assert.deepEqual(again.map((v) => v.id), listed.map((v) => v.id), "两次调用次序必须一致");
  const expected = [first.id, second.id].sort();
  assert.deepEqual(expected, [second.id, first.id], "夹具自检：id 升序与插入序相反");
  assert.deepEqual(listed.map((v) => v.id), expected, "时间并列时次序 = id 升序（第二排序键）");
});

// ---------------------------------------------------------------------------
// G · 不可变口径 + publish
// ---------------------------------------------------------------------------

test("G · 版本不可变：只有 status 可迁移，内容列没有入口可改", async () => {
  const { connection, db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);
  const skill = await newSkill(skills);
  const version = await newVersion(skills, scopeA.ref(skill.id), {
    instructions: "原始指令",
    manifest: { entry: "main.md" },
  });

  const updated = await skills.updateVersionStatus(
    scopeA.ref(skill.id),
    version.id,
    SKILL_VERSION_STATUS_PUBLISHED,
  );
  assert.equal(updated.status, SKILL_VERSION_STATUS_PUBLISHED);
  assert.equal(updated.instructions, "原始指令", "改 status 不得动内容列");
  const raw = connection.raw.prepare("select * from skill_version where id = ?").get(version.id);
  assert.equal(raw.instructions, "原始指令");
  assert.equal(JSON.parse(raw.manifest).entry, "main.md");

  // 非法状态 / 不属于该 skill 的版本
  await assert.rejects(
    () => skills.updateVersionStatus(scopeA.ref(skill.id), version.id, "ACTIVE"),
    (error) => error instanceof ScopeError && /status 必须是 DRAFT \| PUBLISHED/.test(error.message),
    "ACTIVE 属于 skill 生命周期，不是版本状态",
  );
  const other = await newSkill(skills, { name: "other" });
  assert.equal(
    await skills.updateVersionStatus(scopeA.ref(other.id), version.id, SKILL_VERSION_STATUS_PUBLISHED),
    null,
    "版本不属于该 skill ⇒ 命中 0 行 ⇒ null（父域隔离）",
  );

  // 元数据入口不接受 name（uq(tenant_id,name) 的成员不可改）
  await assert.rejects(
    async () => skills.updateMetadata(scopeA.ref(skill.id), { name: "renamed" }),
    (error) => error instanceof ScopeError && /不支持的字段 name/.test(error.message),
  );
  const renamed = await skills.updateMetadata(scopeA.ref(skill.id), { display_name: "新显示名", status: SKILL_STATUS_ACTIVE });
  assert.equal(renamed.display_name, "新显示名");
  assert.equal(renamed.status, SKILL_STATUS_ACTIVE);
});

test("G · publish：冻结最新 DRAFT + 更新 current_version_id；再发布 ⇒ null", async () => {
  const { connection, db, scopeA } = seed();
  const skills = new SkillRepo(db, scopeA, DIALECT);
  const skill = await newSkill(skills);
  const ref = scopeA.ref(skill.id);

  // 没有 DRAFT ⇒ null（不抛，不造错误码）
  assert.equal(await skills.publish(ref), null);

  const v1 = await newVersion(skills, ref, { version: "1.0.0" });
  const published = await skills.publish(ref);
  assert.equal(published.id, v1.id);
  assert.equal(published.status, SKILL_VERSION_STATUS_PUBLISHED);

  const after = await skills.findById(ref);
  assert.equal(after.current_version_id, v1.id, "发布即更新 current_version_id");
  assert.equal(after.status, SKILL_STATUS_DRAFT, "契约对 publish 未规定 skill.status ⇒ 本层不动它");

  // 再发布：已无 DRAFT ⇒ null
  assert.equal(await skills.publish(ref), null);
  const rawV1 = connection.raw.prepare("select status from skill_version where id = ?").get(v1.id);
  assert.equal(rawV1.status, SKILL_VERSION_STATUS_PUBLISHED, "已发布版本保持冻结");

  // 新 DRAFT 出现后，publish 发的是新那个
  const v2 = await newVersion(skills, ref, { version: "2.0.0" });
  const second = await skills.publish(ref);
  assert.equal(second.id, v2.id);
  assert.equal((await skills.findById(ref)).current_version_id, v2.id);
});

test("G · 跨租户：B 的仓储看不到 A 的 skill，也不能给 A 的 skill 建版本", async () => {
  const { connection, db, scopeA, scopeB } = seed();
  const skillsA = new SkillRepo(db, scopeA, DIALECT);
  const skillsB = new SkillRepo(db, scopeB, DIALECT);
  const skill = await newSkill(skillsA);

  assert.deepEqual(await skillsB.list(), [], "B 的列表里不得出现 A 的 skill");
  assert.equal(await skillsB.findById(scopeB.ref(skill.id)), null);
  await assert.rejects(
    () => skillsB.createVersion(scopeB.ref(skill.id), {
      id: "f1000000-0000-4000-8000-00000000beef",
      version: "1.0.0",
      createdBy: IDS.userB,
    }),
    (error) => error instanceof ScopeError && /在本 scope 下不可见/.test(error.message),
    "B 铸造的 ref 打 A 的 skill id ⇒ 父不可见（不是「写入成功」）",
  );
  assert.equal(rawVersionCount(connection), 0, "跨租户建版本一行都不许落库");
  assert.equal((await skillsA.list()).length, 1, "对照路径：A 自己看得到");
});
