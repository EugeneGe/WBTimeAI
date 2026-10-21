/**
 * T2-06 · I-1 跨租户 404 一致性套件（族矩阵 + case 模板）—— **可执行骨架**
 *
 * 判据 J-7：`01-身份与授权.md` §8 —— 4 族 × {read, write} = 8 case ⇒ 均不泄露他租户数据、
 * `code ∈ {NOT_FOUND, *_NOT_FOUND}`、`data` 不含资源存在性线索、**目标租户数据零副作用**；
 * 反例：任一 case 返 403/401/200（对 404 类）或 body 含存在性线索。
 *
 * ── 两条硬设计（都是为了「不交一个看起来绿、实际跳过的套件」）────────────────
 *
 * 1. **空转守卫**：路由不存在时 Fastify 也返 404 —— 那个 404 与「跨租户 404」在字节上
 *    无法区分。若不加守卫，T2-07 未落地时本套件会**全绿**，而它什么都没证明。
 *    因此每个 case 先 `app.hasRoute(...)`；缺路由 ⇒ 抛「未验证（依赖 T2-07 未完成）」，
 *    **不是** skip、**不是** mock。
 *
 * 2. **夹具注入**：本文件只拥有「矩阵 + 执行器 + 断言」；**装配（路由 + 数据库 + 令牌）归
 *    T2-07**。两者通过 {@link HARNESS_ENV} 指定的模块解耦，避免本文件去猜 T2-07 的内部路径。
 *    没有注入 ⇒ 同样报「未验证」，不静默放过。
 *
 * 运行方式（V0.2.0 起，夹具已在仓内：`tests/conformance/harness.mjs`）
 * ---------------------------------------------------------------
 * 推荐（runner 自己用 `pathToFileURL` 拼 `file://` URL、自己断言执行数 ≥ 11）：
 *
 *   pnpm test:conformance            # 根目录执行；等价于 node scripts/run-conformance.mjs
 *
 * 等价的手工命令 —— **可直接复制**（各为完整单行，行首注释符不在命令内）：
 *
 *   Git Bash / Linux / macOS:
 *     WBTIME_CONFORMANCE_HARNESS="$(node -p "require('node:url').pathToFileURL('packages/e2e/tests/conformance/harness.mjs').href")" node --experimental-sqlite --test packages/e2e/tests/conformance/tenant-404.cases.mjs
 *
 *   PowerShell:
 *     $env:WBTIME_CONFORMANCE_HARNESS = node -p "require('node:url').pathToFileURL('packages/e2e/tests/conformance/harness.mjs').href"; node --experimental-sqlite --test packages/e2e/tests/conformance/tenant-404.cases.mjs
 *
 * 两个坑（都是实测踩过的）：
 *   * `WBTIME_CONFORMANCE_HARNESS` 必须是 **`file://` URL** 而不是裸路径 ——
 *     `await import("D:\...")` 在 Windows 上会被当成包名（ERR_MODULE_NOT_FOUND）；
 *   * 必须带 `--experimental-sqlite` —— 夹具用 `node:sqlite` 灌 DDL。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

/** 夹具模块路径（模块须导出 `createHarness()`，见 §夹具契约）。 */
export const HARNESS_ENV = "WBTIME_CONFORMANCE_HARNESS";

/** 「未验证」的统一前缀 —— 便于从 CI 日志里一眼把它们与真红区分开。 */
export const NOT_VERIFIED = "未验证（依赖 T2-07 未完成）";

/** 允许出现在 404 `data` 里的键：**只能**是客户端自己传进来的那个路径参数。 */
const ALLOWED_ECHO_KEYS = new Set(["organization_id", "credential_id", "permission_id", "provider_id"]);

/**
 * 泄漏探测器：`data` 里出现这些键就意味着「响应承认了对象的某种服务端状态」。
 *
 * 注意与 oracle 的差异：py 的 404 `data` **会回显请求里的 id**
 * （实测 `{"organization_id": "..."}` / `{"permission_id": "..."}`，见
 * `02-施工/施工记录/T2-11-oracle.md` §2 第 8/11/14/15/16 行）。回显**客户端已给出的值**
 * 不构成存在性线索（它没说这个对象存不存在），故 `ALLOWED_ECHO_KEYS` 放行；
 * 但 `name` / `slug` / `owner_id` / `exists` / `created_at` 这类「只有查到行才会有」的键
 * 一律禁止。
 */
const LEAK_KEYS = new Set([
  "name",
  "slug",
  "email",
  "username",
  "owner_id",
  "user_id",
  "tenant_id",
  "exists",
  "created_at",
  "updated_at",
  "masked_value",
  "provider",
]);

/**
 * 4 个**可用族** × {read, write} = 8 case。
 *
 * `kind` 两种，别混：
 * * `not_found` —— 定向资源 op，必须 **404** 且 `code ∈ {NOT_FOUND, *_NOT_FOUND}`；
 * * `list_no_leak` —— 列表 op，必须 **200** 但**不含他租户行**（列表不会 404，这是语义）。
 */
export const FAMILIES = [
  {
    family: "organization",
    why: "组织是 scoped 表（`organization.tenant_id`），`get_organization` 走 ScopedRepo ⇒ 查不到行 ⇒ 折 ORGANIZATION_NOT_FOUND",
    read: {
      id: "organization:read",
      kind: "not_found",
      method: "GET",
      pathTemplate: "/api/v1/organizations/{organization_id}",
      param: "organization_id",
      expectedCodes: ["ORGANIZATION_NOT_FOUND", "NOT_FOUND"],
    },
    write: {
      id: "organization:write",
      kind: "list_no_leak",
      method: "GET",
      // 19 op 里**没有**组织写操作（`GET` 列表 + `GET` 详情），故 write 槽位按
      // team-lead 口径退化为「列表不泄露他租户行」。
      pathTemplate: "/api/v1/organizations",
      listField: null,
    },
  },
  {
    family: "model_credential",
    why: "凭证是 scoped 表（`model_credential.tenant_id`）+ 明文掩码，跨租户删必须 404 CREDENTIAL_NOT_FOUND",
    read: {
      id: "model_credential:read",
      kind: "list_no_leak",
      method: "GET",
      pathTemplate: "/api/v1/models/credentials",
      listField: null,
    },
    write: {
      id: "model_credential:write",
      kind: "not_found",
      method: "DELETE",
      pathTemplate: "/api/v1/models/credentials/{credential_id}",
      param: "credential_id",
      expectedCodes: ["CREDENTIAL_NOT_FOUND", "NOT_FOUND"],
    },
  },
  {
    family: "model_provider",
    why: "provider↔credential 绑定落在 `model_credential` 的 provider 维度；跨租户绑定/解绑都折 NOT_FOUND（不暴露 provider 是否存在）",
    read: {
      id: "model_provider:read",
      kind: "not_found",
      method: "POST",
      pathTemplate: "/api/v1/models/providers/{provider_id}/credential",
      param: "provider_id",
      expectedCodes: ["NOT_FOUND"],
    },
    write: {
      id: "model_provider:write",
      kind: "not_found",
      method: "DELETE",
      pathTemplate: "/api/v1/models/providers/{provider_id}/credential",
      param: "provider_id",
      expectedCodes: ["NOT_FOUND"],
    },
  },
  {
    family: "tool_permission",
    why: "`resource_permission` 是 scoped 表；跨租户撤销必须 404 NOT_FOUND（不泄露该 permission 行是否存在）",
    read: {
      id: "tool_permission:read",
      kind: "list_no_leak",
      method: "GET",
      pathTemplate: "/api/v1/tools/permissions",
      listField: null,
      // 该 op 的 `agent_id` 是**必填查询参数**（py oracle 实测：不传 ⇒ 422 VALIDATION_ERROR，
      // 见 T2-11-oracle.md §3-2）。夹具须提供 A 租户的 agent_id。
      queryParamFrom: "agent_id",
    },
    write: {
      id: "tool_permission:write",
      kind: "not_found",
      method: "DELETE",
      pathTemplate: "/api/v1/tools/permissions/{permission_id}",
      param: "permission_id",
      expectedCodes: ["NOT_FOUND"],
    },
  },
];

/**
 * 本版**无仓储**的 10 族：登记为 `registered-pending`。
 *
 * 这不是 skip —— 而是「登记表长度断言」：`PENDING_FAMILIES.length === 10` 是硬断言，
 * 少登记一族就红。逐族判据随各自版本落地（计划 §5.2 末段）。
 */
export const PENDING_FAMILIES = Object.freeze([
  "agent",
  "agent_version",
  "run",
  "conversation",
  "workspace",
  "tool",
  "skill",
  "workflow",
  "task",
  "plugin",
]);

/** 把 8 个 case 摊平成可遍历的数组（1 个执行器 × 数据表 = 参数化，禁只测一族）。 */
export function flattenCases(families = FAMILIES) {
  const cases = [];
  for (const entry of families) {
    for (const slot of ["read", "write"]) {
      if (entry[slot] !== undefined) cases.push({ family: entry.family, why: entry.why, ...entry[slot] });
    }
  }
  return cases;
}

/** 环境变量指定的夹具模块；未配置返回 `null`。 */
async function loadHarness() {
  const specifier = process.env[HARNESS_ENV];
  if (typeof specifier !== "string" || specifier.trim() === "") return null;
  const module = await import(specifier);
  assert.equal(
    typeof module.createHarness,
    "function",
    `夹具模块必须导出 createHarness()：${specifier}`,
  );
  return module.createHarness();
}

/** 路径参数替换（夹具给出真实 id 后填入）。 */
function concretize(pathTemplate, params) {
  let path = pathTemplate;
  for (const [key, value] of Object.entries(params ?? {})) {
    path = path.replace(`{${key}}`, encodeURIComponent(value));
  }
  assert.equal(
    path.includes("{"),
    false,
    `路径参数未全部填充（夹具缺 id？）：${pathTemplate}`,
  );
  return path;
}

/** 断言四键壳。 */
function assertShell(body) {
  assert.deepEqual(
    Object.keys(body).sort(),
    ["code", "data", "message", "request_id"],
    "失败响应必须是契约四键壳",
  );
}

/** 断言 `data` 不含存在性线索（只允许回显客户端自己传的那个 id）。 */
function assertNoExistenceLeak(body, caseId) {
  const data = body.data;
  assert.equal(
    typeof data === "object" && data !== null && !Array.isArray(data),
    true,
    `${caseId}: data 必须是对象`,
  );
  for (const key of Object.keys(data)) {
    assert.equal(
      ALLOWED_ECHO_KEYS.has(key),
      true,
      `${caseId}: data 出现了非「回显入参」的键 ${key}（可能泄露存在性）`,
    );
    assert.equal(LEAK_KEYS.has(key), false, `${caseId}: data 出现存在性线索键 ${key}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 前置：登记表长度（不依赖夹具，永远可跑）
// ─────────────────────────────────────────────────────────────────────────────

test("族矩阵规模：4 可用族 × {read,write} = 8 case；10 族 registered-pending", () => {
  assert.equal(FAMILIES.length, 4, "可用族必须是 4 个");
  assert.equal(flattenCases().length, 8, "8 个 case（4 族 × 2 槽位）");
  assert.equal(PENDING_FAMILIES.length, 10, "pending 登记表必须正好 10 族");
  assert.equal(new Set(PENDING_FAMILIES).size, 10, "pending 登记不得重复");

  const notFound = flattenCases().filter((item) => item.kind === "not_found");
  const noLeak = flattenCases().filter((item) => item.kind === "list_no_leak");
  assert.equal(
    notFound.length + noLeak.length,
    8,
    "每个 case 必须明确 kind（not_found / list_no_leak），不得含糊",
  );
});

test("每个 case 都带可判定的期望（code 集合或 list 语义），不允许「待定」", () => {
  for (const item of flattenCases()) {
    if (item.kind === "not_found") {
      assert.ok(
        Array.isArray(item.expectedCodes) && item.expectedCodes.length > 0,
        `${item.id}: not_found 类必须给出 expectedCodes`,
      );
      assert.ok(
        item.expectedCodes.every((code) => code === "NOT_FOUND" || code.endsWith("_NOT_FOUND")),
        `${item.id}: expectedCodes 必须落在 {NOT_FOUND, *_NOT_FOUND}`,
      );
      assert.match(item.pathTemplate, /\{[a-z_]+\}/, `${item.id}: 定向资源 op 必须带路径参数`);
    } else {
      assert.equal(item.kind, "list_no_leak");
      assert.equal(
        /\{[a-z_]+\}/.test(item.pathTemplate),
        false,
        `${item.id}: 列表 op 不应带资源路径参数`,
      );
    }
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 夹具契约（T2-07 / T2-10 侧需要提供的唯一接缝）
// ─────────────────────────────────────────────────────────────────────────────
//
// 模块（路径由 `WBTIME_CONFORMANCE_HARNESS` 指定）必须导出：
//
//   export async function createHarness(): Promise<{
//     app: {
//       inject(req): Promise<{ statusCode, headers, json(), body }>,
//       hasRoute({ method, url }): boolean,
//     },                                   // 已 ready 的 TS 后端实例
//     authFor(tenant: "a" | "b"): { authorization: string },
//     resourceId(family: string, tenant: "a" | "b"): string,   // 真实资源 id；family 亦可为 "agent"
//     snapshot(caseId: string): Promise<unknown>,              // 副作用快照
//   }>
//
// 为什么不选「本文件自己建库 + 自己装配」：装配（路由 / 数据库注入 / 令牌签发）是 T2-07 的
// 文件域与判据面；本文件若自建一套就变成「第二套后端装配」，一旦漂移，J-7 测的就不是真后端。
// 注入式接缝让「矩阵 + 断言」与「装配」各自单一来源。
//
// 为什么不复用 `packages/e2e/lib/_harness.mjs`：那套打的是 **py 进程**（S-6 遗留），
// J-7 要证的是 **TS 后端**的 I-1 行为；复用会把「测谁」搞混。

test("夹具契约：未注入时的行为是**明确报错**，不是静默通过", async () => {
  const harness = await harnessPromise;
  if (harness !== null) {
    assert.equal(typeof harness.app?.inject, "function", "夹具的 app 必须能 inject");
    return;
  }

  // 未注入 ⇒ 上面 8 个 case 会各自 assert.fail 并带上「未验证（依赖 T2-07 未完成）」；
  // 本条只把「这个状态是刻意的」钉成断言，避免有人把失败的 case 改成 skip 了事。
  assert.equal(
    process.env[HARNESS_ENV],
    undefined,
    `${HARNESS_ENV} 已设置却加载失败 —— 见上方加载错误`,
  );
  assert.equal(flattenCases().length, 8, "未注入状态下仍是完整的 8 个 case（只是无法执行）");
});


const harnessPromise = loadHarness();

for (const item of flattenCases()) {
  test(`J-7 ${item.id}（${item.kind}）`, async () => {
    const harness = await harnessPromise;

    if (harness === null) {
      assert.fail(
        `${NOT_VERIFIED}：未注入夹具。设置环境变量 ${HARNESS_ENV} 指向导出 createHarness() 的模块（契约见本文件 §夹具契约）。`,
      );
    }

    if (typeof harness.app?.hasRoute !== "function") {
      assert.fail(`${NOT_VERIFIED}：夹具必须提供已 ready 的 Fastify 实例（app.hasRoute 可用）`);
    }

    // ① 空转守卫：路由不存在时的 404 与「跨租户 404」在字节上无法区分，必须先排除。
    const routeExists = harness.app.hasRoute({
      method: item.method,
      url: item.pathTemplate,
    });
    if (!routeExists) {
      assert.fail(
        `${NOT_VERIFIED}：路由 ${item.method} ${item.pathTemplate} 尚未注册（缺路由时的 404 不能算跨租户 404）`,
      );
    }

    // ② 用 A 租户令牌打 B 租户的资源 id
    const resourceId = harness.resourceId(item.family, "b");
    assert.equal(
      typeof resourceId,
      "string",
      `${item.id}: 夹具必须给出 B 租户的真实资源 id`,
    );

    const query = item.queryParamFrom
      ? { [item.queryParamFrom]: harness.resourceId("agent", "a") }
      : undefined;
    const params = item.param === undefined ? {} : { [item.param]: resourceId };
    const url = concretize(item.pathTemplate, params)
      + (query === undefined ? "" : `?${new URLSearchParams(query).toString()}`);

    // ③ 副作用探针（写类必须有；读类也顺手取一次，成本可忽略）
    const before = await harness.snapshot(item.id);

    // POST 的请求体必须是**契约合法**的最小体：绑定 op 的 body schema 要求
    // `credential_id` 非空，空体 `{}` 会在校验层折 422 —— 根本到不了跨租户 scoped
    // 查找，那是「请求不合法的红」，不是 I-1 的红。夹具经 `postPayload(caseId)`
    // 提供（回显 A 租户自己的 id，不构成存在性线索）；未提供时维持空体。
    const payload =
      item.method === "POST" && typeof harness.postPayload === "function"
        ? harness.postPayload(item.id)
        : undefined;

    const response = await harness.app.inject({
      method: item.method,
      url,
      headers: { ...harness.authFor("a") },
      ...(payload === undefined ? {} : { payload }),
    });

    const after = await harness.snapshot(item.id);
    assert.deepEqual(after, before, `${item.id}: 目标租户数据出现副作用（写操作必须零影响）`);

    if (item.kind === "not_found") {
      assert.equal(response.statusCode, 404, `${item.id}: 必须 404（不得 403/401/200）`);
      const body = response.json();
      assertShell(body);
      assert.ok(
        item.expectedCodes.includes(body.code),
        `${item.id}: code=${body.code} 不在 ${JSON.stringify(item.expectedCodes)}`,
      );
      assertNoExistenceLeak(body, item.id);
      assert.notEqual(
        body.code,
        "PERMISSION_DENIED",
        `${item.id}: 跨租户不得用 PERMISSION_DENIED —— 403 只由「权限码不足」触发，混进来就破了 §5.1 边界`,
      );
    } else {
      // 列表类：200 且不含他租户行
      assert.equal(response.statusCode, 200, `${item.id}: 列表 op 必须 200`);
      const body = response.json();
      assertShell(body);
      assert.equal(body.code, 0, `${item.id}: 成功壳 code 必须为 0`);
      const rows = Array.isArray(body.data) ? body.data : [];
      if (item.listField !== null) {
        const offenders = rows.filter((row) => row?.[item.listField] === resourceId);
        assert.deepEqual(offenders, [], `${item.id}: 列表里出现他租户行`);
      }
      // 通用：整串不得包含 B 租户资源 id
      assert.equal(
        JSON.stringify(body).includes(resourceId),
        false,
        `${item.id}: 响应体里出现了他租户资源 id`,
      );
    }

    assert.equal(
      response.headers["x-request-id"],
      response.json().request_id,
      `${item.id}: 体 request_id 必须等于响应头`,
    );
  });
}
