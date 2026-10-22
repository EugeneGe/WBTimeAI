/**
 * T2-07 · **OpenAPI 对齐测试**（本任务最关键的一条）。
 *
 * 背景：`packages/contracts` 没有 OpenAPI 的 TS 生成物，52 个 op（身份 19 + Agent 7 + Skill 7 + Conversation 5 + Approval 4 + 模型目录 6 + 工具目录 1 + runs 3）的 TypeBox schema
 * 只能手写 ⇒ **天然是第二真相源**。没有这条测试，"手写 schema"等于裸奔：改契约（或改
 * schema）时不会有任何东西红，直到联调时前端才崩。
 *
 * 三组断言（每条都对全部 op 逐一执行）：
 *  1. **存在性 + operationId 逐字相同**：契约 path+method 的 `operationId` 必须在我的
 *     schema 字典里**原样**存在；反向也成立（我的字典里不许有契约外的 op）。
 *  2. **请求体必填集合相等**：契约 `requestBody` 的 `required` 集合 == 我 schema 里
 *     非 `Optional` 的键集合（多一个必填 = 会拒掉合法请求；少一个 = 放行非法请求）。
 *  3. **响应属性名集合相等**：契约成功响应的属性名（数组响应取 `items`）== 我 schema 的
 *     属性名集合。**多一个键**会污染壳，**少一个键**会让前端拿到 undefined。
 *
 * 另外断言"恰好 52 个"（T3-08 起：T3-12 的 49 + runs 3）—— 多一条说明加了契约外端点，少一条说明漏实现。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { OPERATION_IDS, OPERATION_SCHEMAS } from "../dist/routes/schemas.js";
import { ROOT } from "./routes-harness.mjs";

/**
 * ⚠️ 读 **v0019** 而不是 v0018（T3-08 起）。
 *
 * 依据（实测，不是推测）：v0019 相对 v0018 **只多** `RunResponse.stop_reason` 与
 * `RunOut.stop_reason` 两个属性，`paths` / `operations` / `schemas` 三集合**逐项相同**
 * （100 / 134 / 116）。v0019 是 T3-01 的正式增量（`00-契约增量-v0019.md`），
 * runs 3 op 的响应必须带 `stop_reason` ⇒ 对齐守卫也必须按 v0019 判，
 * 否则"响应键集合"这条会把合法响应判成多一个键。
 */
const SPEC = JSON.parse(readFileSync(join(ROOT, "contracts", "openapi.v1.frozen.v0019.json"), "utf8"));

/** 契约里全部 op 的 `[method, path, operationId]` 三元组（直接从契约读，不抄表）。 */
function contractOperations() {
  const wanted = new Set(OPERATION_IDS);
  const found = [];
  for (const [path, item] of Object.entries(SPEC.paths)) {
    for (const [method, op] of Object.entries(item)) {
      if (!["get", "post", "put", "delete", "patch"].includes(method)) continue;
      if (typeof op?.operationId !== "string") continue;
      if (!wanted.has(op.operationId)) continue;
      found.push({ method: method.toUpperCase(), path, operationId: op.operationId, op });
    }
  }
  return found;
}

/** 解析 `$ref`（只支持本地 `#/components/schemas/X`）。 */
function resolveRef(schema) {
  if (schema?.$ref === undefined) return schema;
  const name = schema.$ref.replace("#/components/schemas/", "");
  const resolved = SPEC.components.schemas[name];
  assert.ok(resolved !== undefined, `契约里找不到 ${schema.$ref}`);
  return resolved;
}

/** TypeBox schema 的属性名集合。 */
function schemaKeys(schema) {
  return Object.keys(schema?.properties ?? {}).sort();
}

/** TypeBox schema 的**必填**键集合（`Type.Optional` 的键不在 `required` 里）。 */
function schemaRequired(schema) {
  return [...(schema?.required ?? [])].sort();
}

test("恰好 52 个 op（不多不少），且每个 operationId 都能在契约里找到", () => {
  assert.equal(OPERATION_IDS.length, 52, "本版做 52 op（身份 19 + Agent 7 + Skill 7 + Conversation 5 + Approval 4 + 模型目录 6 + 工具目录 1 + runs 3）");
  const contract = contractOperations();
  assert.equal(contract.length, 52, `契约里应能对上 52 个 op，实测 ${contract.length}`);

  const contractIds = new Set(contract.map((item) => item.operationId));
  for (const id of OPERATION_IDS) {
    assert.ok(contractIds.has(id), `schema 字典里有契约外 op：${id}`);
  }
  for (const item of contract) {
    assert.ok(OPERATION_SCHEMAS[item.operationId], `契约 op 未实现 schema：${item.operationId}`);
  }
});

test("每个 op 的 method / path / 成功码与契约一致", () => {
  for (const item of contractOperations()) {
    const mine = OPERATION_SCHEMAS[item.operationId];
    assert.equal(mine.method, item.method, `${item.operationId} 的 method 不符`);
    assert.equal(mine.path, item.path, `${item.operationId} 的 path 不符`);

    const successCodes = Object.keys(item.op.responses ?? {})
      .filter((code) => code.startsWith("2"))
      .map(Number);
    assert.deepEqual(
      [...successCodes].sort((a, b) => a - b),
      [mine.successStatus],
      `${item.operationId} 的成功码集合不符（契约 ${successCodes.join("/")}，我 ${mine.successStatus}）`
    );
  }
});

test("请求体必填集合与契约逐条相等", () => {
  for (const item of contractOperations()) {
    const mine = OPERATION_SCHEMAS[item.operationId];
    const contractBody = item.op.requestBody?.content?.["application/json"]?.schema;
    if (contractBody === undefined) {
      assert.equal(mine.body, undefined, `${item.operationId} 契约无请求体，我不该有`);
      continue;
    }
    const resolved = resolveRef(contractBody);
    assert.ok(mine.body !== undefined, `${item.operationId} 缺少请求体 schema`);
    assert.deepEqual(
      schemaRequired(mine.body),
      [...(resolved.required ?? [])].sort(),
      `${item.operationId} 的请求体必填集合不符`
    );
    assert.deepEqual(
      schemaKeys(mine.body),
      schemaKeys(resolved),
      `${item.operationId} 的请求体属性名集合不符`
    );
  }
});

test("成功响应属性名集合与契约逐条相等（数组响应取 items）", () => {
  for (const item of contractOperations()) {
    const mine = OPERATION_SCHEMAS[item.operationId];
    if (mine.successStatus === 204) {
      // 204 无响应体：契约里也确实没有 content
      const response = item.op.responses["204"];
      assert.equal(
        response?.content,
        undefined,
        `${item.operationId} 是 204 却声明了响应体 —— J-10 要求零字节`
      );
      continue;
    }
    const contractResponse =
      item.op.responses[String(mine.successStatus)]?.content?.["application/json"]?.schema;
    assert.ok(contractResponse !== undefined, `${item.operationId} 契约缺 ${mine.successStatus} 响应体`);

    const contractShape = resolveRef(contractResponse);
    const isArray = contractShape.type === "array";
    assert.equal(
      mine.response.type,
      isArray ? "array" : mine.response.type,
      `${item.operationId} 响应是否为数组不一致`
    );

    const contractKeys = isArray
      ? schemaKeys(resolveRef(contractShape.items))
      : schemaKeys(contractShape);
    const myKeys = isArray ? schemaKeys(mine.response.items) : schemaKeys(mine.response);

    assert.deepEqual(myKeys, contractKeys, `${item.operationId} 的响应属性名集合不符`);
  }
});

test("52 op 的 operationId 与本任务交付的清单逐字相同（防「顺手改名」）", () => {
  // 清单来源：01-身份与授权.md §1（19 行）+ T3-05 任务卡（7 行）+ T3-06 任务卡（7 行）
  //           + T3-07 任务卡（5 行）；
  // 只做"字符串层面没被改过"的守卫。
  const expected = [
    "register_api_v1_auth_register_post",
    "login_api_v1_auth_login_post",
    "refresh_api_v1_auth_refresh_post",
    "logout_api_v1_auth_logout_post",
    "read_me_api_v1_users_me_get",
    "update_me_api_v1_users_me_put",
    "list_devices_api_v1_users_me_devices_get",
    "logout_all_api_v1_users_me_logout_all_post",
    "list_organizations_api_v1_organizations_get",
    "get_organization_api_v1_organizations__organization_id__get",
    "check_capability_api_v1_permissions_check_get",
    "list_permissions_api_v1_tools_permissions_get",
    "grant_permission_api_v1_tools_permissions_post",
    "revoke_permission_api_v1_tools_permissions__permission_id__delete",
    "list_credentials_api_v1_models_credentials_get",
    "save_credential_api_v1_models_credentials_post",
    "delete_credential_api_v1_models_credentials__credential_id__delete",
    "bind_credential_api_v1_models_providers__provider_id__credential_post",
    "unbind_credential_api_v1_models_providers__provider_id__credential_delete",
    // ---- Agent 族（T3-05 · 7 op）----
    "list_agents_api_v1_agents_get",
    "create_agent_api_v1_agents_post",
    "get_agent_api_v1_agents__agent_id__get",
    "update_agent_api_v1_agents__agent_id__put",
    "publish_agent_api_v1_agents__agent_id__publish_post",
    "run_agent_api_v1_agents__agent_id__run_post",
    "list_versions_api_v1_agents__agent_id__versions_get",
    // ---- Skill 族（T3-06 · 7 op）----
    "list_skills_api_v1_skills_get",
    "create_skill_api_v1_skills_post",
    "get_skill_api_v1_skills__skill_id__get",
    "update_skill_api_v1_skills__skill_id__put",
    "publish_skill_version_api_v1_skills__skill_id__publish_post",
    "list_skill_versions_api_v1_skills__skill_id__versions_get",
    "create_skill_version_api_v1_skills__skill_id__versions_post",
    // ---- Conversation 族（T3-07 · 5 op）----
    "list_conversations_api_v1_conversations_get",
    "create_conversation_api_v1_conversations_post",
    "get_conversation_api_v1_conversations__conversation_id__get",
    "update_conversation_api_v1_conversations__conversation_id__put",
    "list_messages_api_v1_conversations__conversation_id__messages_get",
    // ---- Approval 族（T3-12 · 4 op）----
    "list_approvals_api_v1_approvals_get",
    "get_approval_api_v1_approvals__approval_id__get",
    "approve_approval_api_v1_approvals__approval_id__approve_post",
    "reject_approval_api_v1_approvals__approval_id__reject_post",
    // ---- 模型目录族（T3-12 · 6 op）----
    "list_providers_api_v1_models_providers_get",
    "register_provider_api_v1_models_providers_post",
    "get_provider_api_v1_models_providers__provider_id__get",
    "disable_provider_api_v1_models_providers__provider_id__delete",
    "list_models_api_v1_models_providers__provider_id__models_get",
    "register_model_api_v1_models_providers__provider_id__models_post",
    // ---- 工具目录族（T3-12 · 1 op）----
    "list_tools_api_v1_tools_get",
    // ---- runs 族（T3-08 · 3 op）----
    "get_run_api_v1_runs__run_id__get",
    "cancel_run_api_v1_runs__run_id__cancel_post",
    "list_run_events_api_v1_runs__run_id__events_get",
  ];
  assert.deepEqual([...OPERATION_IDS].sort(), [...expected].sort());
});
