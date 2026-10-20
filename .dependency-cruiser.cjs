/**
 * V0.1.0 · T1-06 — 三条分层规则（架构纪律的机器化载体）
 *
 * 为什么这三条（而不是别的）
 * --------------------------
 * 本仓的分层纪律此前只写在文档里：
 *   「能力包禁 Web」/「ORM 仅 repositories/」/「domain/** 零 ORM/Web」
 * 文档里的纪律没有执行力——工程师照抄旧线代码就会无声越界，等 dependency
 * 长成环时已无法回退。这三条规则就是把那三句话变成**会红的门禁**。
 *
 * 每条规则都配 `--self-test` 之外的**反例注入**（见
 * `docs/V1.0/V0.1.0-基座与契约层/02-施工/施工记录/T1-06.md`）：先证明它会红，
 * 再证明它变绿。只绿不红的门禁等于没有门禁（本项目 K-11 / 假绿反例教训）。
 *
 * 口径说明：`orphan` / `circular` 等「覆盖率型」规则本版**不启用**——V0.1.0 的
 * apps/web 是原样迁入的存量代码，必然存在孤儿模块与既有环；启用它们会让门禁
 * 在本版恒定红，从而被迫加豁免，最终豁免吞掉规则本身。等 V0.8.0 前端收口后
 * 再评估启用。
 */

/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "no-domain-orm-web",
      comment:
        "domain/** 是纯域层：不得依赖任何 ORM 或 Web 框架。它必须能在没有任何" +
        "数据库与 HTTP 的情况下被测试——否则「域」就只是第二个 repository。" +
        " 注意：规则**不能**限定 dependencyTypes:['npm']——pnpm 隔离下未安装到该包的" +
        "依赖会被 depcruise 标成 'unknown'，加了该限定规则会永不命中（实测 2026-10-21）。",
      severity: "error",
      from: { path: "^packages/domain/" },
      to: {
        path: "^(drizzle-orm|fastify|express|koa|react|react-dom|axios)($|/)",
      },
    },
    {
      name: "orm-only-in-repositories",
      comment:
        "ORM 只允许出现在 packages/db/src/repositories/。schema 定义文件用 drizzle 的" +
        "建表函数是必要的例外；除此之外任何地方直接 import ORM，都会让 ScopedRepo<T>" +
        "的强制 scope 约束被绕过（I-2 纪律的 TS 等价物）。",
      severity: "error",
      from: {
        path: "^packages/",
        pathNot: [
          "^packages/db/src/repositories/",
          "^packages/db/src/schema/",
          "^packages/db/src/index\\.ts$",
          "^packages/db/src/client",
        ],
      },
      to: {
        path: "^(drizzle-orm|drizzle-kit)($|/)",
      },
    },
    {
      name: "no-package-imports-app",
      comment:
        "packages/** 不得 import apps/**。方向反过来就是「能力包偷用运行时」——" +
        "一旦发生，包就不再是可复用的能力单元，而是被某个应用绑死的代码。",
      severity: "error",
      from: { path: "^packages/" },
      to: { path: "^apps/" },
    },
  ],
  options: {
    doNotFollow: {
      path: "node_modules",
    },
    exclude: {
      path: "(^|/)(node_modules|dist|\\.turbo|coverage)(/|$)",
    },
    // TS 路径别名必须先解析，否则 `@wbtime/core` 会被当成外部 npm 包而漏判。
    tsPreCompilationDeps: true,
    tsConfig: {
      fileName: "tsconfig.base.json",
    },
    enhancedResolveOptions: {
      exportsFields: ["exports"],
      conditionNames: ["import", "require", "node", "default", "types"],
      extensions: [".ts", ".tsx", ".mjs", ".js", ".json"],
    },
    reporterOptions: {
      text: {
        highlightFocused: true,
      },
    },
  },
};
