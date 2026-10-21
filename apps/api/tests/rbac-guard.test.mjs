// T2-05 · J-6b 守卫单测（5 个权限码 × 2 态 = 10 例）+ 反例红线
//
// 判据原文（`01-身份与授权.md` §8 J-6b）：对挂 `requirePermission(c)` 的守卫，
// 5 个权限码各 1 例 ⇒ 无码 403 `PERMISSION_DENIED`、有码通过。
// **注**：py 线 4 族 router 实测无 `require_permission`（仅 `CurrentUser`）⇒ 等价实现
// **也不加**，故本判据**不进 e2e**。反例：4 族任一 op 因权限码返 403 ⇒ 必红。
//
// 因此本文件做三件事：
//   ① 在**只在测试里注册**的临时路由上挂守卫，跑 10 例（5 码 × {无码, 有码}）；
//   ② 证明「未认证 ⇒ 401」与「已认证但码不足 ⇒ 403」是两条不同的出口；
//   ③ **证明生产装配里一个守卫都没挂**（这条才是反例红线，见最后一组断言）。

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { after, before, test } from "node:test";

import { ERROR_CODES, ERROR_HTTP_STATUS } from "@wbtime/core";
import { ADMIN_PERMISSION, PERMISSION_CODES } from "@wbtime/db";

import { buildApp } from "../dist/app.js";
import {
  PERMISSION_DENIED_STATUS,
  UNAUTHORIZED_STATUS,
  createPrincipal,
  requirePermission,
} from "../dist/modules/rbac/index.js";

/** 仓库根（apps/api/tests → apps/api → apps → 根）。 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

const app = buildApp({ enableLogging: false });

/**
 * 测试专用的「认证层替身」：从 `x-test-codes` 头造 Principal。
 *
 * * 头**缺席** ⇒ 不设置 `request.principal`（模拟未认证）；
 * * 头存在（含空串）⇒ 设置 Principal，码集合按逗号切分（可空 = 已认证而无任何权限）。
 *
 * 真实认证（Bearer → JWT → Principal）归 T2-04；这里只验证**守卫本身**的契约。
 */
async function testPrincipalHook(request) {
  const raw = request.headers["x-test-codes"];
  if (raw === undefined) return;
  const codes = String(raw)
    .split(",")
    .map((code) => code.trim())
    .filter((code) => code !== "");
  request.principal = createPrincipal({
    userId: "u-guard-test",
    tenantId: "t-guard-test",
    workspaceId: null,
    organizationIds: [],
    permissionCodes: codes,
  });
}

/** 每个权限码挂一条临时路由（`: ` 不能进路径，故替换掉冒号）。 */
function probePath(code) {
  return `/probe/rbac/${code.replace(/:/g, "-").replace(/\*/g, "star")}`;
}

for (const code of PERMISSION_CODES) {
  app.get(
    probePath(code),
    { preHandler: [testPrincipalHook, requirePermission(code)] },
    async () => ({ ok: true, guarded: code }),
  );
}

// 通配主体用的临时路由（验证 `*` 在真实守卫链路里也放行）
app.get(
  "/probe/rbac/wildcard",
  { preHandler: [testPrincipalHook, requirePermission("evaluation:run")] },
  async () => ({ ok: true }),
);

before(async () => {
  await app.ready();
});

after(async () => {
  await app.close();
});

function assertFourKeys(body) {
  assert.deepEqual(
    Object.keys(body).sort(),
    ["code", "data", "message", "request_id"],
    "失败响应必须是契约四键壳",
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ① 10 例：5 码 × {无码 ⇒ 403, 有码 ⇒ 通过}
// ─────────────────────────────────────────────────────────────────────────────

test("J-6b 5 个权限码 × 2 态 = 10 例（无码 403 / 有码通过）", async () => {
  const rows = [];

  for (const code of PERMISSION_CODES) {
    const path = probePath(code);

    // 态 A：已认证但**没有**该码 ⇒ 403 PERMISSION_DENIED
    const denied = await app.inject({
      method: "GET",
      url: path,
      headers: { "x-test-codes": "" },
    });
    assert.equal(denied.statusCode, PERMISSION_DENIED_STATUS, `${code}: 无码必须 403`);
    const deniedBody = denied.json();
    assertFourKeys(deniedBody);
    assert.equal(deniedBody.code, ERROR_CODES.PERMISSION_DENIED, `${code}: 码必须是 PERMISSION_DENIED`);
    assert.equal(deniedBody.data.capability, code, `${code}: 403 的 data 必须指明缺哪个码`);

    // 态 B：已认证且**有**该码 ⇒ 通过
    const allowed = await app.inject({
      method: "GET",
      url: path,
      headers: { "x-test-codes": code },
    });
    assert.equal(allowed.statusCode, 200, `${code}: 有码必须通过`);
    assert.equal(allowed.json().data.guarded, code);

    rows.push(`${code}: 403→200`);
  }

  assert.equal(rows.length, 5, "5 个权限码各 1 例");
  assert.equal(rows.length * 2, 10, "× 2 态 = 10 例");
});

test("J-6b 403 的状态码来自契约（不手写 403）", () => {
  assert.equal(PERMISSION_DENIED_STATUS, ERROR_HTTP_STATUS[ERROR_CODES.PERMISSION_DENIED]);
  assert.equal(PERMISSION_DENIED_STATUS, 403, "契约值本身是 403 —— 但代码取的是派生值");
  assert.equal(UNAUTHORIZED_STATUS, ERROR_HTTP_STATUS[ERROR_CODES.UNAUTHORIZED]);
  assert.equal(UNAUTHORIZED_STATUS, 401);
});

// ─────────────────────────────────────────────────────────────────────────────
// ② 两条出口不混：未认证 401 ≠ 已认证无码 403
// ─────────────────────────────────────────────────────────────────────────────

test("守卫：未认证（无 Principal）⇒ 401 UNAUTHORIZED，不是 403", async () => {
  const response = await app.inject({ method: "GET", url: probePath(PERMISSION_CODES[0]) });

  assert.equal(response.statusCode, UNAUTHORIZED_STATUS);
  const body = response.json();
  assertFourKeys(body);
  assert.equal(body.code, ERROR_CODES.UNAUTHORIZED, "未认证必须回 UNAUTHORIZED（403 会让客户端以为是权限问题）");
  assert.equal(body.request_id, response.headers["x-request-id"]);
});

test("守卫：已认证且有通配 `*` ⇒ 通过任意码", async () => {
  const response = await app.inject({
    method: "GET",
    url: "/probe/rbac/wildcard",
    headers: { "x-test-codes": ADMIN_PERMISSION },
  });
  assert.equal(response.statusCode, 200);
});

test("守卫：403 的 data 携带 capability + reason（联调时能说「缺哪个码」）", async () => {
  const code = PERMISSION_CODES[PERMISSION_CODES.length - 1];
  const response = await app.inject({
    method: "GET",
    url: probePath(code),
    headers: { "x-test-codes": "evaluation:write" }, // 有别的码，但没有被守的那个
  });

  assert.equal(response.statusCode, PERMISSION_DENIED_STATUS);
  const body = response.json();
  assert.deepEqual(body.data, { capability: code, reason: "permission_not_granted" });
  assert.equal(body.request_id, response.headers["x-request-id"], "体 == 头");
});

test("守卫工厂：空码在**构造期**就抛（不允许注册一个恒 403 的路由）", () => {
  for (const bad of ["", "   ", null, undefined, 42]) {
    assert.throws(() => requirePermission(bad), TypeError, `空/非法码 ${String(bad)} 应被拒`);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// ③ 反例红线：生产装配里**一个守卫都没挂**
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 从 `app.printRoutes()` 里抠出**产品路由**（滤掉本文件注册的 `/probe/` 探针）：
 * `[{ method, path }]`。
 *
 * `commonPrefix: false` 是必须的：默认输出是树，健康检查会印成子节点 `healthz`，
 * 直接 `includes("/healthz")` 会漏判（这一点是实测出来的）。
 */
function productionRoutes() {
  const printed = app.printRoutes({ commonPrefix: false });
  const routes = [];
  for (const line of printed.split("\n")) {
    const match = /(\/[^\s]*)\s+\(([A-Z, ]+)\)/.exec(line);
    if (match === null) continue;
    const [, path, methods] = match;
    if (path.startsWith("/probe/")) continue;
    for (const method of methods.split(",").map((item) => item.trim())) {
      if (method !== "" && method !== "HEAD") routes.push({ method, path });
    }
  }
  return routes;
}

/** 路径参数替换成固定 uuid（只为让请求能进到 handler，不追求语义正确）。 */
function concretize(path) {
  return path.replace(/\{[^}]+\}/g, "00000000-0000-4000-8000-000000000000");
}

/** 这些是不是「权限码 403」——即被 requirePermission 拦下的那种失败。 */
function isPermissionDenied(response) {
  if (response.statusCode !== 403) return false;
  try {
    return response.json().code === ERROR_CODES.PERMISSION_DENIED;
  } catch {
    return false;
  }
}

test("反例红线 A：生产路由表里没有任何路由因权限码返 403（运行时全域扫）", async () => {
  const routes = productionRoutes();
  assert.ok(routes.length > 0, "生产路由表为空（断言会空转）");

  const offenders = [];
  for (const route of routes) {
    const response = await app.inject({
      method: route.method,
      url: concretize(route.path),
    });
    if (isPermissionDenied(response)) offenders.push(`${route.method} ${route.path}`);
  }

  assert.deepEqual(
    offenders,
    [],
    `这些生产路由因权限码返了 403（= 有人挂了守卫，破 J-6b 等价性）: ${offenders.join(", ")}`,
  );
});

// 说明（为什么这里不是「路由表 === ["/healthz"]」的快照断言）：
// 早先版本断言「产品路由只有 /healthz」，它在 T2-07 合法注册路由后会**必然变红** ——
// 那是「他人进展」而不是「我这条红线被破」。已用探针实测复现（额外注册两条不挂守卫的
// 4 族路由 ⇒ 原断言红、而运行时无 403）。故改为上面这条**不随进度翻转的不变量**：
// 无论有多少路由，只要没有一条因权限码返 403 就成立。

test("反例红线 B：生产源码零处 `requirePermission(` 调用（守卫只提供能力，不自己挂）", () => {
  const srcRoot = join(ROOT, "apps", "api", "src");
  const files = readdirSync(srcRoot, { recursive: true })
    .map((entry) => String(entry))
    .filter((entry) => entry.endsWith(".ts"));

  assert.ok(files.length > 5, `扫描面过小（${files.length}），疑似路径断链`);

  const callSite = /requirePermission\s*\(/;
  const hits = [];
  for (const relativePath of files) {
    // 守卫的定义处（modules/rbac/guard.ts 与 index.ts 的再导出）不算调用点
    if (relativePath.split(/[\\/]/).includes("rbac")) continue;
    const text = readFileSync(join(srcRoot, relativePath), "utf8");
    if (callSite.test(text)) hits.push(relativePath);
  }

  assert.deepEqual(
    hits,
    [],
    `4 族/任何生产路由都不得挂守卫（计划 §8 J-6b 反例）；命中: ${hits.join(", ")}`,
  );
});

test("反例红线 C：4 族代表路径一律不因权限码返 403（404 / 401 都合法，403 不合法）", async () => {
  const samples = [
    "/api/v1/auth/login",
    "/api/v1/organizations",
    "/api/v1/permissions/check",
    "/api/v1/tools/permissions",
    "/api/v1/models/credentials",
  ];

  for (const url of samples) {
    const response = await app.inject({ method: "GET", url });

    assert.equal(
      isPermissionDenied(response),
      false,
      `${url} 因权限码返了 403 —— 4 族不得挂守卫（计划 §8 J-6b 反例）`,
    );

    // 现状（T2-07 未完成）应是 404；若已变 401/200 说明路由已接入，本条仍然成立，
    // 因此这里只断言「不是权限 403」，不锁死具体状态码（那是 T2-07 的判据面）。
    if (response.statusCode === 404) {
      const body = response.json();
      assert.equal(body.code, ERROR_CODES.NOT_FOUND);
      assert.deepEqual(body.data, {}, "404 的 data 必须为空（不得泄露存在性/权限线索）");
    }
  }
});
