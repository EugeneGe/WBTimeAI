/**
 * T3-11 · MCP **8 op**（契约 path / 成功码逐字）。
 *
 * | # | Method · Path | 成功码 |
 * |---|---|---|
 * | 1 | GET `/api/v1/mcp/servers` | 200 |
 * | 2 | POST `/api/v1/mcp/servers` | **201** |
 * | 3 | GET `/api/v1/mcp/servers/{server_id}` | 200 |
 * | 4 | DELETE `/api/v1/mcp/servers/{server_id}` | **204 零字节** |
 * | 5 | POST `/api/v1/mcp/servers/{server_id}/discover` | 200 |
 * | 6 | GET `/api/v1/mcp/tools?server_id=` | 200 |
 * | 7 | GET `/api/v1/mcp/permissions?mcp_tool_id=` | 200 |
 * | 8 | POST `/api/v1/mcp/permissions` | **201** |
 *
 * 两条容易写错的地方
 * --------------
 *   ① **`DELETE` 是 204**（真删行、无响应体）—— 不是 200 + 整行。契约实测，
 *      与 `DELETE /models/providers/{id}`（软删 200）**不同**，不能套模板；
 *   ② **`GET /mcp/permissions` 的 `mcp_tool_id` 是必填 query**（契约 `required: true`）。
 *      做成可选会让"列出本租户全部 MCP 授权"变成一次无界扫描，契约没给这条能力。
 *
 * 认证必须早于入参校验（`preValidation`，与其他 52 op 一致）：否则未认证请求带非法
 * body 会先被 schema 挡成 422，"有没有令牌"就被绕开了。
 */

import { Type } from "@sinclair/typebox";
import type { FastifyInstance } from "fastify";

import {
  CreateMcpPermissionRequestSchema,
  RegisterMcpServerRequestSchema,
  type CreateMcpPermissionRequestBody,
  type RegisterMcpServerRequestBody,
} from "./schemas.js";
import { authenticate, contextOf, requiredParam, type IdentityDeps } from "./support.js";

/** `GET /mcp/tools` 的 query（`server_id` 可选）。 */
const ListMcpToolsQuerySchema = Type.Object(
  { server_id: Type.Optional(Type.Union([Type.String(), Type.Null()])) },
  { additionalProperties: false }
);

/** `GET /mcp/permissions` 的 query（`mcp_tool_id` **必填**，契约 `minLength: 1`）。 */
const ListMcpPermissionsQuerySchema = Type.Object(
  { mcp_tool_id: Type.String({ minLength: 1 }) },
  { additionalProperties: false }
);

/**
 * 注册 MCP 路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖（含 `mcp: McpService`，见 `app.ts` 装配）。
 */
export function mcpRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  const service = deps.mcp;

  // 1. GET /mcp/servers —— 200
  app.get(
    "/api/v1/mcp/servers",
    { preValidation: authenticate(deps) },
    async () => service.listServers()
  );

  // 2. POST /mcp/servers —— 201
  app.post(
    "/api/v1/mcp/servers",
    { preValidation: authenticate(deps), schema: { body: RegisterMcpServerRequestSchema } },
    async (request, reply) => {
      const body = request.body as RegisterMcpServerRequestBody;
      const created = await service.registerServer({
        name: body.name,
        ...(body.transport === undefined ? {} : { transport: body.transport }),
        command: body.command ?? null,
        args: (body.args ?? []) as string[],
        endpoint: body.endpoint ?? null,
        credentialId: body.credential_id ?? null,
        envRef: body.env_ref ?? null,
        workspaceId: body.workspace_id ?? null,
      });
      reply.code(201);
      return created;
    }
  );

  // 3. GET /mcp/servers/{server_id} —— 200（不可见 ⇒ 404）
  app.get(
    "/api/v1/mcp/servers/:server_id",
    { preValidation: authenticate(deps) },
    async (request) => service.getServer(requiredParam(request.params, "server_id"))
  );

  // 4. DELETE /mcp/servers/{server_id} —— **204 零字节**
  app.delete(
    "/api/v1/mcp/servers/:server_id",
    { preValidation: authenticate(deps) },
    async (request, reply) => {
      await service.deleteServer(requiredParam(request.params, "server_id"));
      reply.code(204);
      return reply.send();
    }
  );

  // 5. POST /mcp/servers/{server_id}/discover —— 200（返回物化后的工具行）
  app.post(
    "/api/v1/mcp/servers/:server_id/discover",
    { preValidation: authenticate(deps) },
    async (request) => service.discover(requiredParam(request.params, "server_id"))
  );

  // 6. GET /mcp/tools —— 200（server_id 可选）
  app.get(
    "/api/v1/mcp/tools",
    { preValidation: authenticate(deps), schema: { querystring: ListMcpToolsQuerySchema } },
    async (request) => {
      const query = request.query as { server_id?: string | null };
      return service.listTools(query.server_id ?? null);
    }
  );

  // 7. GET /mcp/permissions —— 200（mcp_tool_id 必填）
  app.get(
    "/api/v1/mcp/permissions",
    { preValidation: authenticate(deps), schema: { querystring: ListMcpPermissionsQuerySchema } },
    async (request) => {
      const query = request.query as { mcp_tool_id: string };
      return service.listPermissions(query.mcp_tool_id);
    }
  );

  // 8. POST /mcp/permissions —— 201
  app.post(
    "/api/v1/mcp/permissions",
    { preValidation: authenticate(deps), schema: { body: CreateMcpPermissionRequestSchema } },
    async (request, reply) => {
      const body = request.body as CreateMcpPermissionRequestBody;
      const created = await service.createPermission({
        mcpToolId: body.mcp_tool_id,
        agentId: body.agent_id ?? null,
        agentVersionId: body.agent_version_id ?? null,
        ...(body.action === undefined ? {} : { action: body.action }),
        ...(body.effect === undefined ? {} : { effect: body.effect }),
        scope: (body.scope ?? null) as Record<string, unknown> | null,
      });
      reply.code(201);
      return created;
    }
  );
}
