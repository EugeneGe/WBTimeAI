/**
 * T2-11 · **J-11 跨语言等价**（19 op 逐条比 `{status, code, data 键集合}` + **值**）。
 *
 * 这是「契约等价」的终局证明：19 个 op 里任何一个 `data` 多一个键或少一个键，都说明
 * TS 与 py 的语义分了岔 —— 那正是这个版本存在的理由。
 *
 * 四条口径（与 `T2-11-oracle.md` 的采集口径对齐，否则"同入参"不成立）
 * ----------------------------------------------------------------
 * 1. **输入集原样复用**：body 直接用 oracle 里采到的 body（只填必填字段）；路径参数统一
 *    `00000000-0000-4000-8000-000000000000`；顺序照抄（先读 → 再写 → 最后 refresh/logout）。
 * 2. **token 按侧替换**（声明式，见 `j11-harness.mjs` 头注）：`auth:true` 用 TS 链里拿到的
 *    access_token；`refresh` 的 body 里那个 **py 签的 JWT** 换成 TS 侧的 refresh_token。
 *    token 值本身是每侧私有且不可比，这不算"篡改入参"—— 入参的形状与位置完全一致。
 * 3. **结构级**：`status` / `code` / `data` 的**键集合**（`compareCase`）。
 * 4. **值级（V0.2.0 审计 #4 修复）**：白名单字段逐值比对（`compareValues`）——
 *    `source` / `allowed` / `effect` / 回显 id 等「值由代码决定」的字段必须相等。
 *    显式豁免见 `VALUE_EXCLUSIONS`：`reason` 按 **R-29 + L-4 裁定**不逐字对齐
 *    （py 中文文案 vs TS 机器枚举），审计报告「对齐 reason」的建议**不采纳**。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PARITY_DIALECT,
  PG_INPUT_OVERRIDES,
  TRUNCATED_PREVIEW_IDS,
  applyExpectedOverride,
  applyInputOverride,
  VALUE_EXCLUSIONS,
  buildUrl,
  compareCase,
  compareValues,
  loadOracle,
  makeParityApp,
  splitOperation,
} from "./j11-harness.mjs";

/** oracle 里 `refresh` 那条的 body 携带的是 py 签发的 JWT —— 比对时按侧替换。 */
const REFRESH_OP_ID = "refresh";

/**
 * 测试名必须**显式带方言**（FIX-09）。
 *
 * 理由：本文件同一份代码可跑两档（`sqlite` 默认 / `pg` 需 `WBTIME_PG_URL`）。若测试名
 * 不带方言，"全绿"这句话就无法区分「SQLite 档等价」与「PG 档等价」—— 而本版**只允许**
 * 声称前者（PG 主机 2026-10-22 到期，见 `02-施工/00-施工期裁定.md`）。名字里带
 * `dialect=` 让日志本身就构成证据边界。
 */
const DIALECT_LABEL = `dialect=${PARITY_DIALECT}`;

/**
 * 输入替换的**可见标注**（由登记表派生，不手写字符串 —— 手写就会与表漂移）。
 *
 * 期望形态：`tool_id=方言替换`。它出现在值级比对那一列，作用是让"PG 档 19/19 绿"
 * 无法被读成"PG 完全等价"：读者一眼能看到哪一行的哪一个字段是被替换过的。
 */
const OVERRIDE_LABEL = Object.values(PG_INPUT_OVERRIDES)
  .map((rule) => `${String(rule.path).split(".").at(-1)}=方言替换`)
  .join(", ");

/**
 * 渲染表格里的「值」列 —— **按 `checked` 的内容分支**，不能只看长度。
 *
 * 为什么必须分支（QA 2026-10-21 抓到的错标，我必须记在这里）：
 * `j11-harness.mjs` 的 `checked` 有**三种**来源，语义完全不同：
 *
 * | 来源（harness 行号） | 内容形态 | 数组型? | 含义 |
 * |---|---|---|---|
 * | `:928` `checked.push(key)` | `"source"` 等字段名 | 否 | 白名单字段**命中并比对过** |
 * | `:909` `checked.push(\`data[0].keys(N)\`)` | `"data[0].keys(9)"` | 是 | 首元素**键集合**，**不做值比对** |
 * | `:895` `checked.push("data[]:empty")` | `"data[]:empty"` | 是 | 只断言实测也为**空数组** |
 *
 * 只要按长度写文案，数组型就会印成「值: 1 项（白名单字段）」——
 * 而那 1 项**一个白名单字段都不是**。把"含义模糊"改成"明确写错"比原问题更糟，
 * 所以文案必须由内容决定，不能由计数决定。
 *
 * @param {{values: {skipped: boolean, reason?: string, checked: string[]}, overridden: boolean}} item
 *   一条 op 的比对结果。
 * @returns {string} 四种形态之一：`skipped(原因)` / `键: data[0].keys(N)（不做值比对）` /
 *   `空数组（实测亦为空）` / `值: N 项（白名单字段[；tool_id=方言替换]）`。
 */
function renderValueColumn(item) {
  if (item.values.skipped) return `skipped(${item.values.reason})`;

  const checked = item.values.checked;
  const only = checked.length === 1 ? String(checked[0]) : null;

  // 非空数组：首元素键集合（值不比）
  if (only !== null && only.startsWith("data[0].keys")) {
    return `键: ${only}（不做值比对）`;
  }
  // 空数组：只断言实测也为空
  if (only === "data[]:empty") {
    return "空数组（实测亦为空）";
  }

  // 对象型：`checked` 就是命中并比对过的白名单字段名，此处 N 才真的等于"比了几个字段"。
  // 登记式输入替换（PG 档）只发生在对象型 op 上（由 PG_INPUT_OVERRIDES_KEYS 守卫），
  // 故只在这条分支追加 `tool_id=方言替换`。
  const count = checked.length;
  return item.overridden
    ? `值: ${count} 项（白名单字段；${OVERRIDE_LABEL}）`
    : `值: ${count} 项（白名单字段）`;
}

test(`J-11 · 19 op 逐条与 py 真运行时等价（${DIALECT_LABEL} · status / code / data 键集合 + 白名单字段值（数组比首元素键））`, async () => {
  const oracle = loadOracle();
  assert.equal(oracle._provenance.oracle_kind, "runtime", "期望值必须来自真运行时，不是 OpenAPI 推导");
  assert.equal(oracle.ops.length, 19, "oracle 必须含 19 条");

  const fixture = await makeParityApp();
  /** 本侧链中的令牌（register / login 产生）。 */
  let accessToken = null;
  let refreshToken = null;
  /** 每条 op 的比对结果（最后统一断言 + 打印表格）。 */
  const results = [];

  try {
    for (const item of oracle.ops) {
      const { method, path } = splitOperation(item.operation);
      const url = buildUrl(path, item.request.params, item.request.query);

      // ── 入参：body 原样复用；只有 refresh 那条的 token 按侧替换 ────────────
      let payload = item.request.body;
      if (item.id === REFRESH_OP_ID) {
        assert.ok(refreshToken !== null, "refresh 之前必须有本侧 refresh_token");
        payload = { ...item.request.body, refresh_token: refreshToken };
      }
      // ── PG 档的**登记式输入替换**（规模恒为 1 条，见 PG_INPUT_OVERRIDES）─────
      // SQLite 档 `applied === false` ⇒ payload 逐字不变，仍在做"原样入参"的证明。
      const inputOverride = applyInputOverride(item.id, payload);
      payload = inputOverride.payload;
      // 期望值同步：请求改了哪个字段，期望里同一个字段也要跟着改（否则是半截替换）。
      const expectedOverride = applyExpectedOverride(item.expected, item.id);
      const expected = expectedOverride.expected;
      const overridden = inputOverride.applied || expectedOverride.applied;

      const headers = {};
      if (item.request.auth === true) {
        assert.ok(accessToken !== null, `${item.id} 需要 access_token，但链里还没有`);
        headers.authorization = `Bearer ${accessToken}`;
      }
      if (payload !== null && payload !== undefined) headers["content-type"] = "application/json";

      const response = await fixture.app.inject({
        method,
        url,
        headers,
        ...(payload === null || payload === undefined ? {} : { payload }),
      });

      // ── 链条推进：register / login 拿到本侧令牌 ───────────────────────────
      if (item.id === "register" || item.id === "login") {
        assert.equal(response.statusCode, oracle.ops.find((op) => op.id === item.id).expected.status);
        const data = JSON.parse(response.body).data;
        accessToken = data.access_token;
        refreshToken = data.refresh_token;
      }

      const compared = compareCase(expected, response);
      // 值级比对：吃**解析后的 body**（不是 inject 的 response，便于反例用例构造伪值）。
      const values = compareValues(
        expected,
        response.body === "" ? null : JSON.parse(response.body)
      );
      results.push({
        id: item.id,
        operation: item.operation,
        ok: compared.ok && values.ok,
        diffs: [...compared.diffs, ...values.diffs],
        actual: compared.actual,
        values,
        overridden,
      });
    }
  } finally {
    await fixture.close();
  }

  // ── 逐条断言（差异清单应为空）──────────────────────────────────────────
  const failures = results.filter((item) => !item.ok);
  const table = results
    .map(
      (item) =>
        `${item.ok ? "✅" : "❌"} ${item.id.padEnd(24)} ${item.operation.padEnd(56)} ` +
        `status=${item.actual.status} code=${String(item.actual.code)} ` +
        `data=${item.actual.data_type}` +
        `${item.actual.data_keys === null ? "" : `[${item.actual.data_keys.length} keys]`}` +
        // `renderValueColumn()` 返回**完整**标签（含 `值:` / `键:` / `空数组` 前缀），
        // 因此这里不再加 `值: ` —— 否则会印成 `值: 值: 5 项…`。
        ` ${renderValueColumn(item)}` +
        `${item.ok ? "" : `  ← ${item.diffs.join("; ")}`}`
    )
    .join("\n");

  assert.equal(
    failures.length,
    0,
    `J-11 有 ${failures.length} 条不等价：\n` +
      failures.map((item) => `  ${item.id}: ${item.diffs.join("; ")}`).join("\n") +
      `\n\n完整比对表：\n${table}`
  );

  // ── 值级比对的覆盖面（不能"一条都没比"却全绿 —— 那是新的假绿）─────────────
  const skipped = results.filter((item) => item.values.skipped).map((item) => item.id).sort();
  assert.deepEqual(
    skipped,
    [...TRUNCATED_PREVIEW_IDS].sort(),
    "值级比对被跳过的 op 必须**恰好**是 raw_preview 被截断的三条（多一条少一条都算红）"
  );

  const unaccounted = results.flatMap((item) =>
    item.values.unaccounted.map((key) => `${item.id}:${key}`)
  );
  assert.deepEqual(
    unaccounted,
    [],
    "有 py 字段既不在值白名单也不在排除表 —— 必须显式登记（禁止静默放水）"
  );

  const valueChecks = results.reduce((sum, item) => sum + item.values.checked.length, 0);
  // 16 条可解析的 op 里，白名单字段合计必须远多于「0」；给一个下界把"白名单被清空"钉住。
  assert.ok(
    valueChecks >= 20,
    `值级比对项过少（${valueChecks}）—— 白名单疑似被清空（放水口复发）`
  );

  // `reason` 的豁免必须是**写在排除表里的一条记录**，不是"白名单里恰好没有它"。
  assert.equal(
    typeof VALUE_EXCLUSIONS.reason,
    "string",
    "reason 必须显式登记在 VALUE_EXCLUSIONS（R-29 + L-4 裁定）"
  );
  assert.match(VALUE_EXCLUSIONS.reason, /R-29/, "reason 豁免的依据必须写明 R-29");

  // 让"逐条"这件事在测试输出里可见（不是一句"全部通过"）
  console.log(`[J-11] 19/19 等价（${DIALECT_LABEL}，值级比对 ${valueChecks} 项）：\n${table}`);
  // 输入替换必须在报告里可见（否则"PG 绿了"会被读成"PG 完全等价"）。
  if (results.some((item) => item.overridden)) {
    for (const [opId, rule] of Object.entries(PG_INPUT_OVERRIDES)) {
      console.log(
        `[J-11 说明] PG 档 ${opId} 的 ${rule.path.split(".").at(-1)} 用 UUID 替换` +
          `（${rule.value}）：冻结 DDL 该列为 UUID，oracle 的 "oracle-value" 只在 SQLite 档合法；` +
          "py-on-PG 同会 500。这是**测试输入侧**的唯一替换，不构成「PG 已等价」的声称。"
      );
    }
  }
});

test(`J-11 反例自检（${DIALECT_LABEL}）：把某条期望的 data 键集合改一个 ⇒ 比对器必须报红`, async () => {
  // 没有这条，上面那条测试就可能是"比对器永远为真"的假绿（本项目 K-11 的形态）。
  const fixture = await makeParityApp();
  const register = await fixture.app.inject({
    method: "POST",
    url: "/api/v1/auth/register",
    headers: { "content-type": "application/json" },
    payload: { username: "neg_case", email: "neg@example.com", password: "Neg-Password-2026" },
  });
  await fixture.close();

  const good = compareCase(
    { status: 201, code: 0, data_type: "object", data_keys: ["access_token", "expires_in", "refresh_token", "token_type"] },
    register
  );
  assert.equal(good.ok, true, "正常用例必须先绿（否则反例证明不了什么）");

  // ① 多一个键
  const extra = compareCase(
    {
      status: 201,
      code: 0,
      data_type: "object",
      data_keys: ["access_token", "expires_in", "refresh_token", "token_type", "ghost_key"],
    },
    register
  );
  assert.equal(extra.ok, false);
  assert.match(extra.diffs.join(" "), /data 少键: ghost_key/);

  // ② 少一个键
  const missing = compareCase(
    { status: 201, code: 0, data_type: "object", data_keys: ["access_token", "expires_in"] },
    register
  );
  assert.equal(missing.ok, false);
  assert.match(missing.diffs.join(" "), /data 多键: refresh_token/);

  // ③ 状态码不符
  const wrongStatus = compareCase(
    { status: 200, code: 0, data_type: "object", data_keys: ["access_token", "expires_in", "refresh_token", "token_type"] },
    register
  );
  assert.equal(wrongStatus.ok, false);
  assert.match(wrongStatus.diffs.join(" "), /status: 期望 200，实测 201/);
});

test(`J-11 值级反例自检（${DIALECT_LABEL}）：source 伪造成 null 必红；reason 中文差异必不红（豁免是显式的）`, async () => {
  // 为什么必须真跑：`compareValues` 若写成"永远 ok"，主用例 19/19 依然是绿的 ——
  // 值级比对会变成比键集合更精致的假绿。这里把「改一个值就红」钉成可执行命题。
  const oracle = loadOracle();
  const checkCase = oracle.ops.find((op) => op.id === "check_permission");
  assert.ok(checkCase, "oracle 必须含 check_permission（值级比对的主战场）");

  // 真跑一次 check：register 拿令牌 → GET /permissions/check?cap=evaluation:run。
  const fixture = await makeParityApp();
  let body;
  try {
    const registered = await fixture.app.inject({
      method: "POST",
      url: "/api/v1/auth/register",
      headers: { "content-type": "application/json" },
      payload: { username: "neg_values", email: "neg-values@example.com", password: "Neg-Password-2026" },
    });
    assert.equal(registered.statusCode, 201, registered.body);
    const token = JSON.parse(registered.body).data.access_token;

    const response = await fixture.app.inject({
      method: "GET",
      url: "/api/v1/permissions/check?cap=evaluation:run",
      headers: { authorization: `Bearer ${token}` },
    });
    assert.equal(response.statusCode, 200);
    body = JSON.parse(response.body);
  } finally {
    await fixture.close();
  }

  // ① 对照：真实响应必须绿（否则下面的"红"证明不了任何东西）
  const baseline = compareValues(checkCase.expected, body);
  assert.equal(baseline.ok, true, `真实响应必须先绿，实测 diffs=${baseline.diffs.join("; ")}`);
  assert.deepEqual(
    baseline.diffs,
    [],
    "真实响应不应产生任何值级 diff（含 source=default_deny）"
  );
  assert.equal(baseline.skipped, false, "check_permission 的 raw_preview 可解析，不该被跳过");
  assert.ok(baseline.checked.includes("source"), "source 必须在白名单里被真的比过");

  // ② 红证（一）：把实测 `source` 伪造成 null —— 正是 FIX-01 修掉的那个 bug 的值
  const forgedSource = {
    ...body,
    data: { ...body.data, source: null },
  };
  const sourceDiff = compareValues(checkCase.expected, forgedSource);
  assert.equal(sourceDiff.ok, false, "source 被伪造成 null 时**必须**报 diff（否则值级比对是假绿）");
  assert.match(
    sourceDiff.diffs.join(" "),
    /source 期望 "default_deny"，实测 null/,
    `diff 必须点名字段与两侧值，实测：${sourceDiff.diffs.join("; ")}`
  );

  // ③ 红证（二）：`reason` 换成 py 的中文文案 —— **必须不报 diff**。
  // 依据 R-29 + L-4：py 是中文文案、TS 是机器枚举，值不逐字对齐是**裁定口径**。
  // 这一条证明豁免是「写在 VALUE_EXCLUSIONS 里的显式决定」，而不是「白名单漏写了」。
  const forgedReason = {
    ...body,
    data: { ...body.data, reason: "默认拒绝（deny-by-default）" },
  };
  const reasonDiff = compareValues(checkCase.expected, forgedReason);
  assert.equal(
    reasonDiff.ok,
    true,
    `reason 的中文/枚举差异**不得**报 diff（R-29 + L-4 已裁定豁免），实测：${reasonDiff.diffs.join("; ")}`
  );
  assert.deepEqual(reasonDiff.diffs, []);
  assert.ok(
    reasonDiff.excluded.includes("reason"),
    "reason 必须落在**排除表**里被记录（证明是显式豁免，不是遗漏）"
  );

  // ④ 红证（三）：`reason` 伪中文 + `source` 伪造 —— 只有 source 那一项进 diff。
  const bothForged = compareValues(checkCase.expected, {
    ...body,
    data: { ...body.data, source: null, reason: "默认拒绝（deny-by-default）" },
  });
  assert.equal(bothForged.ok, false);
  assert.equal(
    bothForged.diffs.filter((line) => line.includes("reason")).length,
    0,
    "reason 不得出现在 diff 里（豁免对组合场景同样成立）"
  );
  assert.equal(bothForged.diffs.filter((line) => line.includes("source")).length, 1);

  // ⑤ 数组形态的两条：`list_credentials` 的 oracle 是空数组 ⇒ 实测非空必须红。
  const emptyCase = oracle.ops.find((op) => op.id === "list_credentials");
  assert.ok(emptyCase, "oracle 必须含 list_credentials");
  const emptyOk = compareValues(emptyCase.expected, { code: 0, message: "ok", data: [] });
  assert.equal(emptyOk.ok, true, "py 空数组 + 实测空数组 ⇒ 绿");
  assert.equal(emptyOk.checked.includes("data[]:empty"), true, "空数组断言必须被真的执行过");

  const emptyRed = compareValues(emptyCase.expected, { code: 0, message: "ok", data: [{ id: "x" }] });
  assert.equal(emptyRed.ok, false, "py 是空数组而实测有行 ⇒ 必须红");
  assert.match(emptyRed.diffs.join(" "), /py 期望空数组，实测 1 行/);

  // ⑥ 未登记字段不得静默放过：把 py 侧的一个键从白名单/排除表里"摘掉"是做不到的，
  // 但可以证明 `unaccounted` 真的会报出来（用一个 oracle 里不存在的键模拟"新增字段"）。
  const withGhost = {
    ...checkCase.expected,
    raw_preview: JSON.stringify({
      code: 0,
      message: "ok",
      data: { ...body.data, ghost_field: 1 },
    }),
  };
  const ghostDiff = compareValues(withGhost, body);
  assert.deepEqual(
    ghostDiff.unaccounted,
    ["ghost_field"],
    "py 侧出现未登记字段时必须报进 unaccounted（禁止静默放水）"
  );
});
