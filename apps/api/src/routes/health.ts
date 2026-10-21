// apps/api · 健康探针 `GET /healthz`。
//
// 关于「是否套壳」的明确回答：**套壳**。契约的 `runtime_probe.success_json` 实测
// `GET /health` → 200 + `{code:0, message:"ok", data:<业务对象>, request_id}`，即
// 普通 JSON 成功响应走统一壳，健康检查**不是**例外清单里的任何一类
// （不是 failure / sse / non_json / framework_path / already_shell / empty_body）。
//
// 因此本路由的写法与将来 4 路由族的业务路由**完全一致**：**返回裸对象**，由
// `http/envelope.ts` 在外层套壳 —— 路由自己拼壳就属于「壳有两层」的反例。
// 断言见 `apps/api/tests/envelope-middleware.test.mjs`（`/healthz` 的真实响应体）。

import type { FastifyInstance } from "fastify";

/** 健康检查路径（唯一的探针入口，不带 `/api/v1` 前缀）。 */
export const HEALTH_PATH = "/healthz";

/** 健康检查的**裸业务对象**（会被成功壳包进 `data`）。 */
export interface HealthData {
  readonly status: "ok";
  /** 进程运行秒数（向下取整；仅用于存活观测，不参与业务判定）。 */
  readonly uptime_seconds: number;
}

/**
 * 注册健康检查路由。
 *
 * @param app Fastify 实例（需在响应壳中间件装配之后调用）。
 */
export function healthRoutes(app: FastifyInstance): void {
  app.get(HEALTH_PATH, async (): Promise<HealthData> => ({
    status: "ok",
    uptime_seconds: Math.floor(process.uptime()),
  }));
}
