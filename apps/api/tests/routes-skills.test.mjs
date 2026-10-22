/**
 * T3-06 · Skill 族 **7 op** 的行为证明（真库 + `buildApp` + `app.inject`）。
 *
 * 判据（任务卡验收 ①④ + py oracle 逐条对齐）：
 *   ① 7 op 全通（create 201 / list / get / put / publish **200** / versions GET 200 /
 *      versions POST 201）；
 *   ④ `resolveSkill(name)` 纯查询：可解析已发布技能；**零写**（调用前后各表计数不变
 *      —— `skill.resolved` 事件由 T3-08 的 writer 承载，本任务不落任何事件）；
 *   冲突语义与 py 同文案同码：重名 409 / 无可发布版本 409 / 版本号重复 409；
 *   跨租户 ⇒ 404（I-1 口径，不是 403）。
 *
 * 每个"查不到"的断言都配对照路径（同租户看得到），否则"空/404"可能只是"没插进去"。
 */

import assert from "node:assert/strict";
import test from "node:test";

import { SkillService } from "../dist/modules/skill/service.js";
import { makeApp, OTHER_TENANT_ID, request } from "./routes-harness.mjs";

/** 造一个 skill（真 HTTP 路由；返回响应 data）。 */
async function createSkill(fixture, overrides = {}) {
  const res = await request(fixture, "POST", "/api/v1/skills", {
    payload: { name: overrides.name ?? "my-skill", ...overrides },
  });
  assert.equal(res.statusCode, 201, res.body);
  return JSON.parse(res.body).data;
}

/** 建一个 DRAFT 版本（真 HTTP 路由）。 */
async function createVersion(fixture, skillId, overrides = {}) {
  const res = await request(fixture, "POST", `/api/v1/skills/${skillId}/versions`, {
    payload: { version: overrides.version ?? "1.0.0", ...overrides },
  });
  assert.equal(res.statusCode, 201, res.body);
  return JSON.parse(res.body).data;
}

/** 直读 skill 行（对照"库里到底有什么"）。 */
function rawSkill(raw, id) {
  return raw.prepare("select * from skill where id = ?").get(id);
}

// ---------------------------------------------------------------------------
// A · create / list / get（op 1–3）
// ---------------------------------------------------------------------------

test("A · create：201 + DRAFT + display_name 缺省回落 name + tenant 注入 + created_by", async () => {
  const fixture = await makeApp({ username: "skill-a" });
  try {
    const created = await createSkill(fixture, { name: "deploy-helper", description: "描述" });
    assert.equal(created.status, "DRAFT", "契约：创建即 DRAFT");
    assert.equal(created.display_name, "deploy-helper", "缺省回落 name（py `or name` 同口径）");
    assert.equal(created.current_version_id, null, "契约：无当前版本");
    assert.equal(created.current_version, null, "py _to_skill_response 恒不传 ⇒ 恒 null（同形）");
    assert.equal(created.tenant_id, "11111111-1111-4111-8111-111111111111");
    assert.equal(created.created_by, fixture.userId, "created_by = 当前登录用户");

    const row = rawSkill(fixture.raw, created.id);
    assert.equal(row.status, "DRAFT", "对照：真的落库了");
  } finally {
    await fixture.close();
  }
});

test("A · create：缺 name ⇒ 422；name >64 ⇒ 422；重名 ⇒ 409 CONFLICT（py 同文案）", async () => {
  const fixture = await makeApp({ username: "skill-b" });
  try {
    const noName = await request(fixture, "POST", "/api/v1/skills", { payload: {} });
    assert.equal(noName.statusCode, 422, noName.body);

    const tooLong = await request(fixture, "POST", "/api/v1/skills", {
      payload: { name: "x".repeat(65) },
    });
    assert.equal(tooLong.statusCode, 422, "契约 CreateSkillRequest.name maxLength 64");

    await createSkill(fixture, { name: "dup-skill" });
    const dup = await request(fixture, "POST", "/api/v1/skills", { payload: { name: "dup-skill" } });
    assert.equal(dup.statusCode, 409, dup.body);
    const dupBody = JSON.parse(dup.body);
    assert.equal(dupBody.code, "CONFLICT", "py DomainError(CONFLICT) 同码");
    assert.equal(dupBody.message, "Skill 名已存在", "py 同文案");
  } finally {
    await fixture.close();
  }
});

test("A · list：只回本租户；get 未知 id / 跨租户 ⇒ 404 NOT_FOUND（I-1，不泄漏存在性）", async () => {
  const fixture = await makeApp({ username: "skill-c" });
  try {
    const own = await createSkill(fixture);
    await createSkill(fixture, { name: "second-skill" });

    const listed = JSON.parse((await request(fixture, "GET", "/api/v1/skills")).body).data;
    assert.equal(listed.length, 2, "对照：本租户两个都看得到");

    // 跨租户行：先造租户 B 的用户（skill.created_by 的 FK 需要真实 user 行）
    const crossUserId = "cccc0000-0000-4000-8000-0000000000c2";
    fixture.raw
      .prepare(
        "insert into user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
          "values (?, ?, 'carol', 'c@c.example', 'x', 'carol', 1, 0)",
      )
      .run(crossUserId, OTHER_TENANT_ID);
    const crossId = "cccc0000-0000-4000-8000-0000000000c1";
    fixture.raw
      .prepare(
        "insert into skill (id, tenant_id, organization_id, name, display_name, description, category, status, current_version_id, created_by, created_at, updated_at) " +
          "values (?, ?, null, '隔壁技能', '隔壁技能', null, '', 'DRAFT', null, ?, '2026-10-22 00:00:00', '2026-10-22 00:00:00')",
      )
      .run(crossId, OTHER_TENANT_ID, crossUserId);
    assert.ok(rawSkill(fixture.raw, crossId), "对照：跨租户行确实存在");

    const listedAgain = JSON.parse((await request(fixture, "GET", "/api/v1/skills")).body).data;
    assert.equal(listedAgain.length, 2, "跨租户行不得出现在列表里");

    for (const id of ["f0000000-0000-4000-8000-0000000000dead", crossId]) {
      const res = await request(fixture, "GET", `/api/v1/skills/${id}`);
      assert.equal(res.statusCode, 404);
      assert.equal(JSON.parse(res.body).code, "NOT_FOUND");
    }
    assert.equal(own.id.length, 36);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B · update（op 4）：缺省不变 / 直改生效 / 显式 null = 不变（py is not None）/ status 词表
// ---------------------------------------------------------------------------

test("B · PUT：缺省字段不变；display_name / description / category 直改生效；显式 null = 不变", async () => {
  const fixture = await makeApp({ username: "skill-d" });
  try {
    const created = await createSkill(fixture, { name: "put-skill", display_name: "原名" });
    const url = `/api/v1/skills/${created.id}`;

    const untouched = await request(fixture, "PUT", url, { payload: {} });
    assert.equal(untouched.statusCode, 200);
    assert.equal(JSON.parse(untouched.body).data.display_name, "原名", "缺省字段不变");

    const updated = JSON.parse(
      (
        await request(fixture, "PUT", url, {
          payload: { display_name: "新名", description: "新描述", category: "ops" },
        })
      ).body,
    ).data;
    assert.equal(updated.display_name, "新名");
    assert.equal(updated.description, "新描述");
    assert.equal(updated.category, "ops");
    assert.equal(updated.status, "DRAFT", "没传 status 就不该动状态");

    // py `is not None` 语义：显式 null = **不变**（不是清空）
    const nulled = JSON.parse(
      (await request(fixture, "PUT", url, { payload: { description: null, display_name: null } })).body,
    ).data;
    assert.equal(nulled.description, "新描述", "显式 null 不清空（py 同口径）");
    assert.equal(nulled.display_name, "新名", "显式 null 不清空（py 同口径）");
  } finally {
    await fixture.close();
  }
});

test("B · PUT status：DRAFT→ACTIVE 合法；词表外 ⇒ 422 且行未变；未知 skill ⇒ 404（先于校验）", async () => {
  const fixture = await makeApp({ username: "skill-e" });
  try {
    const created = await createSkill(fixture, { name: "status-skill" });
    const url = `/api/v1/skills/${created.id}`;

    const active = JSON.parse((await request(fixture, "PUT", url, { payload: { status: "ACTIVE" } })).body).data;
    assert.equal(active.status, "ACTIVE");

    // 词表外值 ⇒ 422（repo 值域校验；py 不校验 —— TS 更严，偏差 #3 登记）
    for (const bogus of ["active", "PUBLISHED", "NOT_A_STATUS"]) {
      const res = await request(fixture, "PUT", url, { payload: { status: bogus } });
      assert.equal(res.statusCode, 422, `status=${bogus} 必须 422`);
      assert.equal(JSON.parse(res.body).code, "VALIDATION_ERROR");
    }
    assert.equal(rawSkill(fixture.raw, created.id).status, "ACTIVE", "词表外值不得改动行");

    // ARCHIVED 也是合法词表值
    assert.equal(
      JSON.parse((await request(fixture, "PUT", url, { payload: { status: "ARCHIVED" } })).body).data.status,
      "ARCHIVED",
    );

    const missing = await request(fixture, "PUT", "/api/v1/skills/f0000000-0000-4000-8000-0000000000dead", {
      payload: { status: "ACTIVE" },
    });
    assert.equal(missing.statusCode, 404, "先 404 后校验（同族一致）");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C · versions / publish（op 5–7）：DRAFT 建立 / 版本号唯一 / 发布冻结 + 指针回写
// ---------------------------------------------------------------------------

test("C · versions POST：201 + DRAFT + manifest/instructions 落库；版本号重复 ⇒ 409；未知 skill ⇒ 404", async () => {
  const fixture = await makeApp({ username: "skill-f" });
  try {
    const skill = await createSkill(fixture, { name: "ver-skill" });
    const v1 = await createVersion(fixture, skill.id, {
      version: "1.0.0",
      instructions: "第一步",
      manifest: { entry: "scripts/run.py", resources: "res" },
    });
    assert.equal(v1.status, "DRAFT", "契约：建版本即 DRAFT");
    assert.equal(v1.skill_id, skill.id);
    assert.deepEqual(v1.manifest, { entry: "scripts/run.py", resources: "res" });
    assert.equal(v1.instructions, "第一步");

    const dup = await request(fixture, "POST", `/api/v1/skills/${skill.id}/versions`, {
      payload: { version: "1.0.0" },
    });
    assert.equal(dup.statusCode, 409, dup.body);
    assert.equal(JSON.parse(dup.body).code, "CONFLICT", "uq_skill_version_skill_version 先查后插 ⇒ 409");
    assert.equal(JSON.parse(dup.body).message, "Skill 版本已存在", "py 同文案");

    const missing = await request(fixture, "POST", "/api/v1/skills/f0000000-0000-4000-8000-0000000000dead/versions", {
      payload: { version: "1.0.0" },
    });
    assert.equal(missing.statusCode, 404);
  } finally {
    await fixture.close();
  }
});

test("C · versions GET：全部版本可见；未知 skill ⇒ 404", async () => {
  const fixture = await makeApp({ username: "skill-g" });
  try {
    const skill = await createSkill(fixture, { name: "listver-skill" });
    await createVersion(fixture, skill.id, { version: "0.1.0" });
    await createVersion(fixture, skill.id, { version: "0.2.0" });

    const listed = JSON.parse((await request(fixture, "GET", `/api/v1/skills/${skill.id}/versions`)).body).data;
    assert.equal(listed.length, 2);
    assert.deepEqual(
      listed.map((v) => v.version).sort(),
      ["0.1.0", "0.2.0"],
      "对照：两个版本都在（次序按 repo 既有口径：created_at 倒序，偏差 #7 登记）",
    );

    const missing = await request(fixture, "GET", "/api/v1/skills/f0000000-0000-4000-8000-0000000000dead/versions");
    assert.equal(missing.statusCode, 404);
  } finally {
    await fixture.close();
  }
});

test("C · publish：200 + PUBLISHED + current_version_id 指针回写（raw 对照）；版本行内容冻结", async () => {
  const fixture = await makeApp({ username: "skill-h" });
  try {
    const skill = await createSkill(fixture, { name: "pub-skill" });
    const v1 = await createVersion(fixture, skill.id, { version: "1.0.0", instructions: "冻结前" });

    const published = JSON.parse(
      (await request(fixture, "POST", `/api/v1/skills/${skill.id}/publish`)).body,
    ).data;
    assert.equal(published.id, v1.id, "发布的是最新 DRAFT 版本");
    assert.equal(published.status, "PUBLISHED", "发布即冻结");

    const row = rawSkill(fixture.raw, skill.id);
    assert.equal(row.current_version_id, v1.id, "指针回写（环状外键第三步）");

    // 冻结：published 行内容与 DRAFT 时期一致（不可变口径）
    const vrow = fixture.raw.prepare("select * from skill_version where id = ?").get(v1.id);
    assert.equal(vrow.instructions, "冻结前");
    assert.equal(vrow.version, "1.0.0");
    assert.equal(vrow.status, "PUBLISHED");
  } finally {
    await fixture.close();
  }
});

test("C · publish：无 DRAFT 版本 ⇒ 409「无可发布的 Skill 版本」（py 同文案）；未知 skill ⇒ 404", async () => {
  const fixture = await makeApp({ username: "skill-i" });
  try {
    const skill = await createSkill(fixture, { name: "nodraft-skill" });

    // 从未建过版本 ⇒ 无 DRAFT 可发
    const noDraft = await request(fixture, "POST", `/api/v1/skills/${skill.id}/publish`);
    assert.equal(noDraft.statusCode, 409, noDraft.body);
    const body = JSON.parse(noDraft.body);
    assert.equal(body.code, "CONFLICT");
    assert.equal(body.message, "无可发布的 Skill 版本", "py 同文案");

    // 全部版本已发布（无新 DRAFT）⇒ 同样 409
    await createVersion(fixture, skill.id, { version: "1.0.0" });
    const first = await request(fixture, "POST", `/api/v1/skills/${skill.id}/publish`);
    assert.equal(first.statusCode, 200);
    const again = await request(fixture, "POST", `/api/v1/skills/${skill.id}/publish`);
    assert.equal(again.statusCode, 409, "已发布过的版本不是 DRAFT，不得再发");

    const missing = await request(fixture, "POST", "/api/v1/skills/f0000000-0000-4000-8000-0000000000dead/publish");
    assert.equal(missing.statusCode, 404, "先 404 后 409");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// D · resolveSkill（验收 ④）：纯查询可解析 / 无技能 null / **零写**（事件归 T3-08）
// ---------------------------------------------------------------------------

test("D · resolveSkill：已发布技能解析出 skill+version；未发布 / 未知名 / 跨租户 ⇒ null", async () => {
  const fixture = await makeApp({ username: "skill-j" });
  try {
    const service = new SkillService({ db: fixture.connection.db, dialect: "sqlite" });
    const tenantId = "11111111-1111-4111-8111-111111111111";

    // 未发布（无当前版本）⇒ null
    const skill = await createSkill(fixture, { name: "resolve-skill" });
    assert.equal(await service.resolveSkill(tenantId, "resolve-skill"), null, "无当前版本 ⇒ null");

    await createVersion(fixture, skill.id, { version: "2.3.4", instructions: "运行手册" });
    assert.equal(await service.resolveSkill(tenantId, "resolve-skill"), null, "DRAFT 未发布 ⇒ 仍 null");

    const published = JSON.parse((await request(fixture, "POST", `/api/v1/skills/${skill.id}/publish`)).body).data;
    const resolved = await service.resolveSkill(tenantId, "resolve-skill");
    assert.ok(resolved, "发布后可解析");
    assert.equal(resolved.skill.id, skill.id);
    assert.equal(resolved.version.id, published.id);
    assert.equal(resolved.version.version, "2.3.4", "解析出的是当前生效版本号");
    assert.equal(resolved.version.instructions, "运行手册");

    assert.equal(await service.resolveSkill(tenantId, "no-such-skill"), null, "未知名 ⇒ null");
    assert.equal(
      await service.resolveSkill("22222222-2222-4222-8222-222222222222", "resolve-skill"),
      null,
      "跨租户 ⇒ null（scope 谓词，I-1）",
    );
  } finally {
    await fixture.close();
  }
});

test("D · resolveSkill 零写（验收 ④：skill.resolved 事件由 T3-08 writer 承载，本任务不落任何行）", async () => {
  const fixture = await makeApp({ username: "skill-k" });
  try {
    const service = new SkillService({ db: fixture.connection.db, dialect: "sqlite" });
    const tenantId = "11111111-1111-4111-8111-111111111111";
    const skill = await createSkill(fixture, { name: "readonly-skill" });
    await createVersion(fixture, skill.id, { version: "1.0.0" });
    await request(fixture, "POST", `/api/v1/skills/${skill.id}/publish`);

    const countsBefore = {
      skill: fixture.raw.prepare("select count(*) as n from skill").get().n,
      skill_version: fixture.raw.prepare("select count(*) as n from skill_version").get().n,
      agent_event: fixture.raw.prepare("select count(*) as n from agent_event").get().n,
      audit_log: fixture.raw.prepare("select count(*) as n from audit_log").get().n,
    };

    await service.resolveSkill(tenantId, "readonly-skill");
    await service.resolveSkill(tenantId, "no-such-skill");

    const countsAfter = {
      skill: fixture.raw.prepare("select count(*) as n from skill").get().n,
      skill_version: fixture.raw.prepare("select count(*) as n from skill_version").get().n,
      agent_event: fixture.raw.prepare("select count(*) as n from agent_event").get().n,
      audit_log: fixture.raw.prepare("select count(*) as n from audit_log").get().n,
    };
    assert.deepEqual(countsAfter, countsBefore, "纯查询：任何表计数都不得变化");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// E · 契约面：SkillResponse 11 键 / SkillVersionResponse 8 键（响应壳外零多余键）
// ---------------------------------------------------------------------------

test("E · 响应键集合：SkillResponse 11 键（无 updated_at）；SkillVersionResponse 8 键", async () => {
  const fixture = await makeApp({ username: "skill-l" });
  try {
    const skill = await createSkill(fixture, { name: "shape-skill" });
    assert.deepEqual(
      Object.keys(skill).sort(),
      [
        "category", "created_at", "created_by", "current_version", "current_version_id",
        "description", "display_name", "id", "name", "status", "tenant_id",
      ].sort(),
      "契约 SkillResponse 11 键逐字",
    );

    await createVersion(fixture, skill.id, { version: "1.0.0" });
    const versions = JSON.parse((await request(fixture, "GET", `/api/v1/skills/${skill.id}/versions`)).body).data;
    assert.deepEqual(
      Object.keys(versions[0]).sort(),
      ["created_at", "created_by", "id", "instructions", "manifest", "skill_id", "status", "version"].sort(),
      "契约 SkillVersionResponse 8 键逐字",
    );
  } finally {
    await fixture.close();
  }
});
