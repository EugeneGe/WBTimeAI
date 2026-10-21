/**
 * T2-05 · Router 层守卫工厂（计划 §4.3「判定发生在哪一层」）。
 *
 *     Bearer → Principal → hasPermission → 失败抛 PERMISSION_DENIED(403)
 *
 * 三条纪律，逐条都有出处：
 *
 * 1. **状态码从契约派生，不手写 403**（R-14）：取
 *    `httpStatusOf(ERROR_CODES.PERMISSION_DENIED)`，与 `contracts/errors.json` 同源。
 *    写死 `403` 的代码在契约调整后会静默错位，而这里会跟着表走。
 * 2. **未认证 ⇒ 401，不是 403**（计划 §5.1 边界表）：`request.principal` 缺席说明
 *    认证层没跑或凭证无效，此时「你连是谁都不知道」，返回 403 会让客户端误以为
 *    「换个账号就好」。只有「已认证但码不足」才是 403。
 * 3. **本文件不挂任何路由**：守卫只是工厂，谁挂谁负责。V0.2.0 的 4 路由族**全部不挂**
 *    （py 线实测 4 族 router 只有 `CurrentUser`、没有 `require_permission`，等价实现也不加，
 *    见计划 §8 J-6b 的注解）。J-6b 的反例「4 族任一 op 因权限码返 403 ⇒ 必红」抓的就是
 *    「有人觉得这里该挂一个」——所以挂载点必须由 dispatch 方显式给出，不能在本文件里默认生效。
 */

import { ERROR_CODES } from "@wbtime/core";
import type { preHandlerAsyncHookHandler } from "fastify";

import { HttpException } from "../../http/error-handler.js";
import { httpStatusOf } from "../../http/status-map.js";
import { checkCapability } from "./authorization.js";
import type { CapabilityDecision, Principal } from "./principal.js";

declare module "fastify" {
  interface FastifyRequest {
    /**
     * 已认证主体（由认证层 T2-04 在 `preHandler` 链更早的位置写入）。
     *
     * ⚠️ **T2-04 请勿重复 `declare module` 这同一个属性**：类型重复声明若类型不同会
     * 直接编译报错（`Subsequent property declarations must have the same type`）。
     * 正确做法是 `import type { Principal } from "../modules/rbac/principal.js"` 后直接赋值。
     */
    principal?: Principal;
  }
}

/**
 * 构造一个「要求某权限码」的路由级守卫。
 *
 * 用法（**仅测试 / 将来没有契约依据的路由才会用到**）：
 * ```ts
 * app.get("/x", { preHandler: [requirePermission("evaluation:run")] }, handler)
 * ```
 *
 * @param capability 权限码（契约字面量）。空码在**构造期**就抛：允许空码等于允许「问一个
 *   没有名字的权限」，而判定层对空码恒 DENY，最终表现是「这个守卫永远 403」——
 *   一个永远不会通过的路由不该能注册成功。
 * @returns Fastify `preHandler` 异步钩子。
 * @throws {TypeError} `capability` 为空字符串 / 非字符串（构造期，不是请求期）。
 */
export function requirePermission(capability: string): preHandlerAsyncHookHandler {
  if (typeof capability !== "string" || capability.trim() === "") {
    throw new TypeError("requirePermission: capability 必须是非空字符串（空码会让守卫恒 403）");
  }

  return async (request): Promise<void> => {
    const principal = request.principal;
    if (principal === undefined) {
      throw new HttpException(
        httpStatusOf(ERROR_CODES.UNAUTHORIZED),
        ERROR_CODES.UNAUTHORIZED,
        "未认证或凭证缺失（守卫需要已解析的 Principal）",
        {},
      );
    }

    const decision = checkCapability(principal, capability);
    if (decision.allowed) return;

    throw new HttpException(
      httpStatusOf(ERROR_CODES.PERMISSION_DENIED),
      ERROR_CODES.PERMISSION_DENIED,
      "已认证但权限不足",
      // 附加上下文（契约允许 `data.may_carry_context`）：不带 capability 的 403
      // 在联调时只能说「不行」，带上才能说「缺哪个码」。
      { capability: decision.capability, reason: decision.reason },
    );
  };
}

/**
 * 由判定结论直接产出 403 错误（供 Service 层在「已知结论」时复用同一形状）。
 *
 * 与守卫共用同一份 message / data 结构，避免出现「守卫的 403」和「Service 的 403」
 * 长得不一样 —— 前端只需要认一套。
 *
 * @param decision 已得出的判定结论（`allowed` 必须为 false）。
 * @returns 可直接 `throw` 的 `HttpException`。
 * @throws {TypeError} `decision.allowed === true` 时（把 ALLOW 当 DENY 抛是逻辑错误）。
 */
export function forbiddenFrom(decision: CapabilityDecision): HttpException {
  if (decision.allowed) {
    throw new TypeError("forbiddenFrom: 传入的结论是 ALLOW，不能用来构造 403");
  }
  return new HttpException(
    httpStatusOf(ERROR_CODES.PERMISSION_DENIED),
    ERROR_CODES.PERMISSION_DENIED,
    "已认证但权限不足",
    { capability: decision.capability, reason: decision.reason },
  );
}

/** 契约里的两个状态码（派生值，供测试对账；不在业务代码里手写数字）。 */
export const PERMISSION_DENIED_STATUS: number = httpStatusOf(ERROR_CODES.PERMISSION_DENIED);

/** 未认证状态码（同上）。 */
export const UNAUTHORIZED_STATUS: number = httpStatusOf(ERROR_CODES.UNAUTHORIZED);
