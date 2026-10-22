/**
 * T3-12 · Approval **4 op**（§2 W4 任务卡；契约 path / 成功码逐字）。
 *
 * | # | Method · Path | 成功码 | 说明 |
 * |---|---|---|---|
 * | 1 | GET `/api/v1/approvals` | 200 | **只返 `PENDING`**；`limit`(1..200, 缺省 50) / `offset`(≥0) |
 * | 2 | GET `/api/v1/approvals/{approval_id}` | 200 | 详情（跨租户 / 不存在 ⇒ 404） |
 * | 3 | POST `/api/v1/approvals/{approval_id}/approve` | 200 | `PENDING → APPROVED`；已决议 ⇒ 409 |
 * | 4 | POST `/api/v1/approvals/{approval_id}/reject` | 200 | `PENDING → REJECTED`；已决议 ⇒ 409 |
 *
 * 三条必须守住的纪律
 * ----------------
 *   ① **认证早于入参校验**（`preValidation`，与既有 38 op 惯例一致）：否则未认证请求
 *      带非法 query（如 `limit=0`）会先被 schema 挡成 422，"有没有令牌"被绕开。
 *      反例由 `routes-approvals.test.mjs` 的「未认证 + 非法 query ⇒ 401」钉住。
 *   ② **决议不触发执行**：本文件只调 `deps.approvals.approve/reject`，**不得**出现
 *      任何执行器 / 沙箱 / AgentLoop 的 import。执行在 T3-08 的恢复路径
 *      （`approval.decided` 事件 → run 续跑）。这条是卡面反例「approve 直接调执行器
 *      ⇒ 必红」的静态面，行为面由测试断言"决议后工具调用表零增长"。
 *   ③ **不得自造成功码**：approve / reject 都是 **200**（不是 201、不是 204），
 *      因为契约回的是更新后的整行。
 *
 * `limit` / `offset` 是全仓**唯一**带分页参数的列表 op
 * ---------------------------------------------------
 * 契约实测：`GET /approvals` 的 `parameters` 有 `limit` / `offset` 两个 query 项
 * （其余列表 op 的 `parameters` 都是空数组）。所以这里**可以**也有义务实现分页 ——
 * 与 `routes-invariants` 的口径不冲突（那边只对"契约声明为空"的 op 做"不得出现分页"
 * 的正面断言）。缺省值也照抄契约：`limit=50` / `offset=0`。
 */

import { Type } from "@sinclair/typebox";
import type { FastifyInstance } from "fastify";

import { authenticate, contextOf, requiredParam, type IdentityDeps } from "./support.js";

/**
 * 契约 `GET /approvals` 的 query 参数（`limit` 1..200 缺省 50；`offset` ≥0 缺省 0）。
 *
 * `additionalProperties: false`：契约没有声明其它 query 项，多传一个就应当 422
 * —— 与"响应 `additionalProperties: false`"同一套纪律，避免契约外的参数被静默忽略。
 */
const ListApprovalsQuerySchema = Type.Object(
  {
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
    offset: Type.Optional(Type.Integer({ minimum: 0, default: 0 })),
  },
  { additionalProperties: false }
);

/** 解析后的 query（`default` 已由 TypeBox 填充，但类型层仍是可选）。 */
interface ListApprovalsQuery {
  readonly limit?: number;
  readonly offset?: number;
}

/**
 * 注册审批族路由。
 *
 * @param app Fastify 实例。
 * @param deps 身份族依赖（含 `approvals: ApprovalService`，见 `app.ts` 装配）。
 */
export function approvalRoutes(app: FastifyInstance, deps: IdentityDeps): void {
  const service = deps.approvals;

  // 1. GET /approvals —— 200（只返 PENDING；分页）
  app.get(
    "/api/v1/approvals",
    {
      preValidation: authenticate(deps),
      schema: { querystring: ListApprovalsQuerySchema },
    },
    async (request) => {
      const context = contextOf(request);
      const query = request.query as ListApprovalsQuery;
      return service.listPending(context.scope.tenantId, {
        ...(query.limit === undefined ? {} : { limit: query.limit }),
        ...(query.offset === undefined ? {} : { offset: query.offset }),
      });
    }
  );

  // 2. GET /approvals/{approval_id} —— 200（不可见 ⇒ 404）
  app.get(
    "/api/v1/approvals/:approval_id",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      return service.getById(
        context.scope.tenantId,
        requiredParam(request.params, "approval_id")
      );
    }
  );

  // 3. POST /approvals/{approval_id}/approve —— 200（已决议 ⇒ 409）
  app.post(
    "/api/v1/approvals/:approval_id/approve",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      return service.approve(
        context.scope.tenantId,
        requiredParam(request.params, "approval_id"),
        context.user.id
      );
    }
  );

  // 4. POST /approvals/{approval_id}/reject —— 200（已决议 ⇒ 409）
  app.post(
    "/api/v1/approvals/:approval_id/reject",
    { preValidation: authenticate(deps) },
    async (request) => {
      const context = contextOf(request);
      return service.reject(
        context.scope.tenantId,
        requiredParam(request.params, "approval_id"),
        context.user.id
      );
    }
  );
}
