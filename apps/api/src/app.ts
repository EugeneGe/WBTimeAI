// apps/api · Fastify 实例装配。
//
// 装配顺序即契约顺序（`contracts/envelope.schema.json` → `x-wbtimeai.enforcement.middleware_stack`）：
//
//   1. request_id 上下文（内层）  —— `genReqId` + `onRequest`，写响应头 `X-Request-Id`
//   2. 响应壳中间件（外层）       —— `onSend`，从「头 / 上下文」取同一个 request_id
//   3. 统一错误出口               —— `setErrorHandler` + `setNotFoundHandler`
//   4. 路由
//
// 旧线注释的原文是「先加 → 更内层；其响应头供外层『响应壳中间件』复用（体 == 头）」，
// 本文件保持同一顺序语义：request_id 先落头，壳后取头。**反过来就会让「体 == 头」
// 变成两处各自生成再祈祷相等**，那正是本版要结构性消灭的东西。

import { ConfigError, loadConfig, requireSecretKey } from "@wbtime/config";
import type { Config } from "@wbtime/config";
import type { DrizzleDatabase, SqlDialect } from "@wbtime/db";
import { createLogger } from "@wbtime/logging";
import Fastify from "fastify";
import type { FastifyInstance, FastifyServerOptions } from "fastify";

import { registerEnvelope } from "./http/envelope.js";
import { registerErrorHandler } from "./http/error-handler.js";
import { attachRequestContext, genReqId } from "./http/request-context.js";
import { AgentService } from "./modules/agent/service.js";
import { AuthService } from "./modules/auth/service.js";
import { createRegisterLimiter } from "./modules/auth/register-limiter.js";
import { CredentialService } from "./modules/credential/service.js";
import { OrganizationService } from "./modules/organization/service.js";
import { createFakeProvider } from "./modules/model/fake-provider.js";
import { ModelGateway } from "./modules/model/gateway.js";
import {
  COMPATIBLE_KEY_ENV,
  PROVIDER_KEY_ENV,
  assertFakeProviderAllowed,
  assertKnownProviderKind,
  createSdkProviderAdapter,
  type ProviderAdapter,
  type ProviderKind,
} from "./modules/model/providers/factory.js";
import { authRoutes } from "./routes/auth.js";
import { agentRoutes } from "./routes/agents.js";
import { healthRoutes } from "./routes/health.js";
import { modelRoutes } from "./routes/models.js";
import { organizationRoutes } from "./routes/organizations.js";
import { permissionRoutes } from "./routes/permissions.js";
import type { IdentityDeps } from "./routes/support.js";
import { userRoutes } from "./routes/users.js";

/**
 * 默认租户 id（单租户部署的过渡方案）。
 *
 * py 线用 `tenants.ensure_default()` 做一次**无作用域**的表扫描来"找到或建出"默认租户；
 * TS 侧不复制那个查询（理由见 T2-03 D-1：`tenant` 不该被扩成第 4 张 unscoped 表）。
 * 本版改为：租户 id 由装配方给出（`WBTIME_AI_TENANT_ID`，缺省用本常量），`TenantRepo`
 * 按 scope 校验它存在且启用。**租户自举（seed / ensure_default）归 V0.6.0**，登记为遗留。
 */
export const DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001";

// ---------------------------------------------------------------------------
// 模型栈装配（T3-02 · A02）
//
// 三条口径，逐条来自任务卡验收 ② 与 R3-19：
//   1. fake 只在 `NODE_ENV=test` / `WBTIME_AI_ALLOW_FAKE_PROVIDER=1` / 显式开关下装配；
//   2. 生产缺对应 API key ⇒ **启动期** `ConfigError`（`CONFIGURATION_ERROR`），
//      **绝不静默回落 fake**（静默回落 = 对外声称有模型能力，实际在放录音）；
//   3. 未给 `model` ⇒ **不装配**（CI 无任何 key，`pnpm test` 必须离线可跑，
//      见 R3-19；真连只在窗口期人工执行）；
//   4. `kind` **白名单校验**（QA F-2）：未知 kind ⇒ `CONFIGURATION_ERROR`，
//      绝不静默降级为 `openai-compatible`（那会把启动期错误推迟到第一个用户请求）。
// ---------------------------------------------------------------------------

/** 装配产物：Provider 适配器 + 网关（网关是 `ModelGatewayPort` 的唯一实现）。 */
export interface ModelStack {
  readonly kind: ProviderKind;
  readonly provider: ProviderAdapter;
  readonly gateway: ModelGateway;
}

/**
 * 模型栈装配选项。`kind` **必填**（不猜：猜错等于静默用错厂商），且必须命中
 * `PROVIDER_KINDS` 白名单 —— 未知值 ⇒ `CONFIGURATION_ERROR`（QA F-2）。
 */
export interface ModelStackOptions {
  readonly kind: ProviderKind;
  /** 配置对象；缺省 `loadConfig(env)`。 */
  readonly config?: Config;
  /** 环境变量源；缺省 `process.env`。 */
  readonly env?: NodeJS.ProcessEnv;
  /** 显式 key；缺省读该 kind 对应的 `*_API_KEY`。 */
  readonly apiKey?: string;
  /** 兼容端点 baseURL（`openai-compatible` 必填）。 */
  readonly baseURL?: string;
  /** 显式放行 fake；缺省看 `config.modelAllowFakeProvider`。 */
  readonly allowFakeProvider?: boolean;
}

/**
 * 装配模型栈（**严格**：缺 key / fake 被禁一律抛 `ConfigError`）。
 *
 * @throws {ConfigError} 见 {@link ModelStackOptions} 上方三条口径。
 */
export function buildModelStack(options: ModelStackOptions): ModelStack {
  const env = options.env ?? process.env;
  const config = options.config ?? loadConfig(env);
  // 入口白名单（QA F-2）：必须在**取 keyEnv 之前**判 —— 否则未知 kind 会先走到
  // `PROVIDER_KEY_ENV[kind]` 拿到 `undefined`，把错误说成「未配置 undefined」（F-3），
  // 误导运维排查；更糟的是不判就会静默降级成 openai-compatible。
  const kind = assertKnownProviderKind(options.kind);

  if (kind === "fake") {
    // 闸门：生产装配 fake 等同伪造能力，宁可启动失败。
    assertFakeProviderAllowed(env, options.allowFakeProvider ?? config.modelAllowFakeProvider);
    const provider = createFakeProvider({});
    return { kind, provider, gateway: new ModelGateway({ provider }) };
  }

  const keyEnv = kind === "openai-compatible" ? COMPATIBLE_KEY_ENV : PROVIDER_KEY_ENV[kind];
  const apiKey = options.apiKey ?? env[keyEnv] ?? "";
  if (apiKey.trim() === "") {
    // 为什么在这里再判一次（工厂内 openai-compatible 只强制 baseURL）：
    // 兼容端点允许"自建无鉴权"是**显式**用法，装配期不该替它默认"无 key 也能跑" ——
    // 那会把 401 从启动期挪到第一个用户请求上。
    throw new ConfigError(
      `未配置 ${keyEnv}（未配置 ≠ 降级：R3-19 要求 fail loud，不得静默回落 fake provider）`,
      [keyEnv],
    );
  }

  const provider = createSdkProviderAdapter({
    kind,
    apiKey,
    ...(options.baseURL === undefined ? {} : { baseURL: options.baseURL }),
    env,
    allowFakeProvider: false,
  });
  return { kind, provider, gateway: new ModelGateway({ provider }) };
}

/** `buildApp` 的可选项（全部有默认值，默认值即生产行为）。 */
export interface BuildAppOptions {
  /** 配置对象；缺省 `loadConfig()`（读 `process.env`）。 */
  readonly config?: Config;
  /** 是否开启 pino 日志；测试传 `false` 可静音（不影响 request_id 上下文）。 */
  readonly enableLogging?: boolean;
  /** 透传给 Fastify 的其它选项（测试可传 `{ trustProxy: true }` 等）。 */
  readonly serverOptions?: FastifyServerOptions;
  /**
   * 数据库句柄。**给了才装配身份族 19 op**。
   *
   * 为什么是"给了才装"而不是无条件：19 个 op 全部依赖仓储与主密钥，没有 db 的实例
   * 无法提供其中任何一个。缺省（`undefined`）时只剩 `/healthz` —— 这正是探针场景
   * （T2-02 的响应壳测试）需要的形态。
   */
  readonly database?: DrizzleDatabase;
  /** 方言（缺省 `pg`；测试传 `sqlite`）。仅在给 `database` 时生效。 */
  readonly dialect?: SqlDialect;
  /** 默认租户 id（缺省 `WBTIME_AI_TENANT_ID` 或 {@link DEFAULT_TENANT_ID}）。 */
  readonly tenantId?: string;
  /** 身份族依赖（测试可注入替身；缺省由 `database` + `config` 现建）。 */
  readonly identity?: IdentityDeps;
  /**
   * 模型栈装配开关。**未给 ⇒ 不装配**（CI 无 key，R3-19 要求离线可跑）。
   *
   * 给了就走 {@link buildModelStack} 的严格口径：缺 key 或 fake 被禁 ⇒ 抛
   * `ConfigError`（`CONFIGURATION_ERROR`），装配后的网关挂 `app.modelGateway`。
   */
  readonly model?: ModelStackOptions;
}

/** 挂了模型栈的实例：`modelGateway` 仅在 `buildApp({ model })` 时存在。 */
declare module "fastify" {
  interface FastifyInstance {
    modelGateway?: ModelGateway;
  }
}

/**
 * 装配身份族依赖（**唯一**取主密钥并构造服务的地方）。
 *
 * 🔴 L-3 / R-22 的落点：`requireSecretKey(config)` 在这里调用。
 * `TokenService` 只校"非空"，**不校 32 字节**（T2-04 的实现），所以"密钥太短 ⇒
 * `CONFIGURATION_ERROR`"这道闸只有装配入口能把 —— 少调这一行，短密钥就会一路生效。
 *
 * @param args 配置 + db 句柄 + 方言 + 租户。
 * @returns 19 op 需要的依赖集合。
 * @throws {ConfigError} `WBTIME_AI_SECRET_KEY` 缺失或不足 32 UTF-8 字节（`CONFIGURATION_ERROR`）。
 */
export function buildIdentityStack(args: {
  readonly config: Config;
  readonly database: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId?: string;
}): IdentityDeps {
  const secretKey = requireSecretKey(args.config);
  const dialect = args.dialect ?? "pg";
  const tenantId = args.tenantId ?? process.env.WBTIME_AI_TENANT_ID ?? DEFAULT_TENANT_ID;
  return {
    db: args.database,
    dialect,
    tenantId,
    auth: new AuthService({ db: args.database, dialect, tenantId, secretKey }),
    organizations: new OrganizationService({ db: args.database, dialect }),
    credentials: new CredentialService({ db: args.database, dialect, secretKey }),
    // T3-05：Agent 族 7 op（发布 / 版本 / run 前置校验；执行归 T3-08）。
    agents: new AgentService({ db: args.database, dialect }),
    // FIX-04：限速器**在这里**构造 —— 每次 `buildApp()` 一份，随实例存亡。
    // 放在模块作用域会变成跨实例共享的配额桶（测试之间互相污染，见 R-34）。
    registerLimiter: createRegisterLimiter({
      limitPerMinute: args.config.registerRateLimitPerMinute,
    }),
  };
}

/**
 * 装配（但不 listen）一个 Fastify 实例。
 *
 * 刻意**不在这里** `await app.ready()`：测试需要在 `ready()` 之前注册探针路由，
 * 才能在不污染产品路由表的前提下测出「6 类不套壳」的真实 HTTP 行为。
 *
 * @param options 见 {@link BuildAppOptions}。
 * @returns 未就绪的 Fastify 实例（调用方负责 `ready()` / `listen()` / `close()`）。
 */
export function buildApp(options: BuildAppOptions = {}): FastifyInstance {
  const config = options.config ?? loadConfig();
  const enableLogging = options.enableLogging ?? true;

  const serverOptions: FastifyServerOptions = {
    // request_id 直接做成 Fastify 的 `request.id`：日志、错误对象、响应头三处同源。
    genReqId: (request) => genReqId(request),
    ...options.serverOptions,
  };

  if (enableLogging) {
    serverOptions.loggerInstance = createLogger({ level: config.logLevel });
  } else {
    serverOptions.logger = false;
  }

  const app = Fastify(serverOptions);

  // 1) request_id 上下文（内层）
  attachRequestContext(app);
  // 2) 响应壳中间件（外层）
  registerEnvelope(app);
  // 3) 失败壳唯一出口
  registerErrorHandler(app);
  // 4) 路由
  healthRoutes(app);

  // 5) 身份族 19 op（需要 db；缺省不装配，见 `database` 的说明）
  const identity =
    options.identity ??
    (options.database === undefined
      ? undefined
      : buildIdentityStack({
          config,
          database: options.database,
          ...(options.dialect === undefined ? {} : { dialect: options.dialect }),
          ...(options.tenantId === undefined ? {} : { tenantId: options.tenantId }),
        }));
  if (identity !== undefined) {
    authRoutes(app, identity);
    userRoutes(app, identity);
    organizationRoutes(app, identity);
    permissionRoutes(app, identity);
    modelRoutes(app, identity);
    // T3-05：Agent 族 7 op（与身份族同一 db / tenant 装配）。
    agentRoutes(app, identity);
  }

  // 6) 模型栈（给了 `model` 才装配；缺 key 在上面就抛，不会走到这里）
  if (options.model !== undefined) {
    // 用 `decorate` 而不是直接赋值：Fastify 会因同名重复装饰而报错，
    // 而"两个任务各自装配一个网关、后者静默覆盖前者"正是装配面要防的事故。
    app.decorate("modelGateway", buildModelStack({ config, ...options.model }).gateway);
  }

  return app;
}

/** 编译期自证：`buildApp` 的返回类型就是 Fastify 实例（不接受隐式 `any`）。 */
export type App = FastifyInstance;
