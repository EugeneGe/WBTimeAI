/**
 * T3-12 · 工具目录 **1 op**（`GET /api/v1/tools`；契约 path / 成功码逐字）。
 *
 * 返回**本租户**的工具目录（5 个内置：`filesystem / git / http / shell / code_exec`）。
 * 语义与 py `routers/v1/tools.py::list_tools` 对齐（"工具浏览器"），差别只在实现：
 * py 直接读内存注册表，TS 先按 R3-23 **幂等物化**进 `tool` 表再读回 —— 因为
 * `tool_permission.tool_id` 是 FK，权限要引用工具就必须先有行与稳定 `id`。
 *
 * 本文件**不注册**的路径（刻意）
 * ----------------------------
 * `GET /tools/permissions` · `POST /tools/permissions` ·
 * `DELETE /tools/permissions/{permission_id}` 三条在契约里**存在**（1+2+1 = 3 个额外 op），
 * 但**不在 T3-12 卡面**（卡面范围红线：4 + 6 + 1 = 11 op，不新增 op）。
 * 它们归后续版本，`routes-invariants` 的守恒断言会阻止"顺手加一条"。
 *
 * 同理不注册 `GET /mcp/tools`（那是 MCP 族，归 T3-11）。
 */

import type { FastifyInstance } from "fastify";

import { authenticate, contextOf, type IdentityDeps } from "./support.js";

/**
 * 注册工具目录路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖（含 `tools: ToolService`，见 `app.ts` 装配）。
 */
export function toolRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  // GET /tools —— 200（数组；含 `code_exec` 且 `requires_sandbox=true`）
  app.get(
    "/api/v1/tools",
    { preValidation: authenticate(deps) },
    async (request) => deps.tools.list(contextOf(request).scope.tenantId)
  );
}
