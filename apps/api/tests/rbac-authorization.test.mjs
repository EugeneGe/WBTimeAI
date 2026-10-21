// T2-05 · J-6a 判定层（纯函数，零 IO）
//
// 判据原文（`01-身份与授权.md` §8 J-6a）：
//   `GET /permissions/check?cap=<code>` 四字段恒在（capability/allowed/effect/reason）；
//   `*` 用户 ⇒ allowed=true,effect=ALLOW；无该码 ⇒ allowed=false,effect=DENY 且**仍是 200**。
//   反例：check 返回 4xx；或 effect 与 allowed 不同步。
//
// 本文件只测 **service 层**（HTTP 适配归 T2-07）：
// 「仍是 200」在这里的等价表达是「判定结果是一个正常返回值，不是异常」——
// 所以有一条断言专门检查 checkCapability 对无码主体**不抛**。

import assert from "node:assert/strict";
import { test } from "node:test";

import { ADMIN_PERMISSION, PERMISSION_CODES } from "@wbtime/db";

import {
  buildPrincipal,
  checkCapability,
  createPrincipal,
  decideCapability,
  hasPermission,
} from "../dist/modules/rbac/index.js";

/** 造主体：`codes` 即已合流的权限码。 */
function principalWith(codes) {
  return createPrincipal({
    userId: "u-1",
    tenantId: "t-1",
    workspaceId: null,
    organizationIds: ["o-1"],
    permissionCodes: codes,
  });
}

/** 判定结果的**精确**键集：J-6a 的四字段 + J-11 oracle 实测的第 5 键 source。 */
const DECISION_KEYS = ["allowed", "capability", "effect", "reason", "source"];

function assertFourFields(decision, expectedCapability) {
  assert.deepEqual(Object.keys(decision).sort(), DECISION_KEYS, "四字段恒在 + source，且不得多出其它键");
  assert.equal(decision.capability, expectedCapability);
  assert.equal(typeof decision.allowed, "boolean");
  assert.ok(decision.effect === "ALLOW" || decision.effect === "DENY", "effect 只能是契约两值");
  assert.equal(typeof decision.reason, "string");
  assert.ok(decision.reason.length > 0, "reason 必须非空");
}

test("J-6a 四字段恒在：任意主体 × 任意码都是同一组键", () => {
  const principals = [principalWith([]), principalWith(["*"]), principalWith(["evaluation:run"])];
  const capabilities = ["evaluation:run", "marketplace:import", "", "不存在的码"];

  let checked = 0;
  for (const principal of principals) {
    for (const capability of capabilities) {
      const decision = checkCapability(principal, capability);
      assertFourFields(decision, capability);
      checked += 1;
    }
  }
  assert.equal(checked, 12, "3 主体 × 4 码 = 12 次判定都必须满足四字段");
});

test("J-6a `*` 通配：查任意码 ⇒ allowed=true / effect=ALLOW", () => {
  const admin = principalWith([ADMIN_PERMISSION]);
  assert.equal(ADMIN_PERMISSION, "*", "通配码字面量必须来自 @wbtime/db 的单一来源");

  for (const capability of [...PERMISSION_CODES, "任意:未知码", ADMIN_PERMISSION]) {
    const decision = checkCapability(admin, capability);
    assert.equal(decision.allowed, true, `通配主体查 ${capability} 必须放行`);
    assert.equal(decision.effect, "ALLOW");
    assert.equal(decision.reason, "wildcard_admin");
    assert.equal(hasPermission(admin, capability), true);
  }
});

test("J-6a 无该码 ⇒ allowed=false / effect=DENY（且不抛异常 = 仍是 200 的语义）", () => {
  const limited = principalWith(["evaluation:read"]);

  for (const capability of PERMISSION_CODES.filter((code) => code !== "evaluation:read")) {
    // 关键：这里如果抛异常，「HTTP 仍 200」就不可能成立
    const decision = checkCapability(limited, capability);
    assert.equal(decision.allowed, false);
    assert.equal(decision.effect, "DENY");
    assert.equal(decision.reason, "permission_not_granted");
    assert.equal(hasPermission(limited, capability), false);
  }

  // 正例：自己有的码仍放行（防止「一律 DENY」这种假成立）
  const own = checkCapability(limited, "evaluation:read");
  assert.equal(own.allowed, true);
  assert.equal(own.effect, "ALLOW");
  assert.equal(own.reason, "permission_granted");
});

test("J-6a 空白主体（无任何码）⇒ 全部 DENY，但判定本身正常返回", () => {
  const nobody = principalWith([]);
  for (const capability of PERMISSION_CODES) {
    const decision = checkCapability(nobody, capability);
    assert.equal(decision.allowed, false);
    assert.equal(decision.effect, "DENY");
  }
});

test("J-6a 反例：effect 与 allowed 必须同步（全组合逐一检查）", () => {
  const principals = [
    principalWith([]),
    principalWith(["*"]),
    principalWith([...PERMISSION_CODES]),
    principalWith(["evaluation:write"]),
  ];

  const seen = new Set();
  for (const principal of principals) {
    for (const capability of [...PERMISSION_CODES, ADMIN_PERMISSION, "", " "]) {
      const decision = checkCapability(principal, capability);
      // 这条就是反例本身：allowed===true ⇔ effect==="ALLOW"
      assert.equal(
        decision.allowed,
        decision.effect === "ALLOW",
        `不同步: allowed=${decision.allowed} effect=${decision.effect}（cap=${JSON.stringify(capability)}）`,
      );
      seen.add(decision.effect);
    }
  }
  assert.deepEqual([...seen].sort(), ["ALLOW", "DENY"], "两个 effect 都必须被覆盖到（否则断言是哑真）");
});

test("空码 / 非字符串能力码 ⇒ DENY 且 reason 指明「问错了」，不因通配而放行", () => {
  const admin = principalWith([ADMIN_PERMISSION]); // 持有通配也不该放行空码

  for (const capability of ["", "   ", null, undefined, 42, {}]) {
    const decision = checkCapability(admin, capability);
    assert.equal(decision.allowed, false, `空/非法码 ${JSON.stringify(capability)} 不得因通配放行`);
    assert.equal(decision.effect, "DENY");
    assert.equal(decision.reason, "capability_malformed");
    assert.equal(hasPermission(admin, capability), false);
  }
});

test("权限码不做大小写/空白归一化（拼写错误必须暴露成 DENY）", () => {
  const principal = principalWith(["marketplace:import"]);

  assert.equal(hasPermission(principal, "Marketplace:Import"), false);
  assert.equal(hasPermission(principal, " marketplace:import"), false);
  assert.equal(hasPermission(principal, "marketplace:import "), false);
  // 但 decode 出来的「前缀匹配」也不得成立
  assert.equal(hasPermission(principal, "marketplace:imp"), false);
});

test("checkCapability 与 decideCapability 同结论（两个入口不能各说一套）", () => {
  const principal = principalWith(["evaluation:run"]);
  for (const capability of [...PERMISSION_CODES, "*", ""]) {
    assert.deepEqual(checkCapability(principal, capability), decideCapability(principal, capability));
  }
});

test("hasPermission 与 decideCapability.allowed 恒等（判定式只有一处实现）", () => {
  const principals = [
    principalWith([]),
    principalWith(["*"]),
    principalWith(["marketplace:export"]),
    principalWith([...PERMISSION_CODES]),
  ];
  for (const principal of principals) {
    for (const capability of [...PERMISSION_CODES, ADMIN_PERMISSION]) {
      assert.equal(hasPermission(principal, capability), decideCapability(principal, capability).allowed);
    }
  }
});

test("createPrincipal / buildPrincipal：空 id 抛错、结果被冻结（判权依赖的值不可变）", () => {
  assert.throws(
    () =>
      createPrincipal({
        userId: "",
        tenantId: "t-1",
        workspaceId: null,
        organizationIds: [],
        permissionCodes: [],
      }),
    TypeError,
  );

  assert.throws(() => buildPrincipal({
    userId: "u-1",
    tenantId: "  ",
    permissionCodes: [],
  }), TypeError);

  const principal = principalWith(["evaluation:read"]);
  assert.equal(Object.isFrozen(principal), true);
  assert.equal(Object.isFrozen(principal.permissionCodes), true);

  // 冻结是**真的**生效：试图改写会抛（严格模式）
  assert.throws(() => {
    principal.permissionCodes.push("marketplace:import");
  }, TypeError);
});

test("buildPrincipal 的缺省值：workspaceId=null / organizationIds=[]", () => {
  const principal = buildPrincipal({ userId: "u-1", tenantId: "t-1", permissionCodes: [] });
  assert.equal(principal.workspaceId, null);
  assert.deepEqual(principal.organizationIds, []);
  assert.deepEqual(principal.permissionCodes, []);
});
