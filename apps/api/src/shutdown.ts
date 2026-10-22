/**
 * FIX-07 · 优雅关闭的**超时兜底**（20xx 审计 #9 / `main.ts:165-184`）。
 *
 * 缺陷原文
 * -------
 * 旧 `shutdown()` 只 `await close()`，既不设超时也不 `exit`：
 * * `app.close()` 会被**空闲 keep-alive 连接**挂住（Fastify 会等现有连接自然结束，
 *   而客户端可能一直不复用、也不关闭）；
 * * `pool.end()` 同理，PG 侧若还有租借中的连接就一直等；
 * ⇒ 进程"收到 SIGTERM 但永不退出"，编排系统只能等宽限期到了再 SIGKILL ——
 *   那等于**没有优雅关闭**，只是把强制杀延后了几十秒。
 *
 * 本模块的形状
 * -----------
 * 把关闭流程抽成**纯函数** `runShutdown({ close, timeoutMs, exit, log, signal })`：
 * 依赖全部注入（`close` / `exit` / `log` / 时钟时长），因此可以在单测里用
 * "永不 resolve 的 close + 20ms 超时"精确验证兜底路径，**不需要真发信号**
 * （Windows 上 `child.kill` 是硬杀，发 SIGTERM 的语义与 POSIX 不同，测信号等于测平台）。
 *
 * 三条不变量
 * ---------
 * 1. **`exit` 至多被调用一次**：正常完成 `exit(0)`，超时 `exit(1)`，二者互斥；
 * 2. **并发信号只执行一次**：`main` 里 SIGINT / SIGTERM 可能接连到达（`once` 只挡同名信号），
 *    由 {@link createShutdownHandler} 的首次调用闸门保证「真正开始关闭」只有一次；
 * 3. **超时后不再等待**：`race` 一结束就清掉定时器，避免它把事件循环继续挂着。
 *
 * `close` 依赖的**内部顺序**（V0.3.1 · T031-05）：`main.ts` 传入的 close 回调先做
 * 在飞 run 收敛（`convergeAllInflightRuns` —— 经 `RunCoordinator.cancel` 的终态 CAS，
 * 不得绕开），再 `app.close()` + 连接池关闭。本模块不感知该顺序，只负责整体兜底：
 * 收敛 + 关闭合计超过 `timeoutMs` ⇒ `exit(1)`。
 *
 * `timeoutMs = 0` 的含义：**不设兜底**（只 `await close()`）。它只为测试与
 * "特殊环境里必须等完"的场景存在，生产默认见 `@wbtime/config` 的
 * `shutdownTimeoutMs`（10_000）。
 */

/** 默认兜底时长（毫秒）：与编排系统的默认 `terminationGracePeriodSeconds` 留出余量。 */
export const DEFAULT_SHUTDOWN_TIMEOUT_MS = 10_000;

/** 正常关闭的退出码。 */
export const EXIT_SHUTDOWN_OK = 0;

/** 关闭超时 / 关闭失败的退出码（进程不能"假装正常退出"）。 */
export const EXIT_SHUTDOWN_FAILED = 1;

/**
 * 本模块需要的日志能力（只用到两条）。
 *
 * 刻意**不**直接依赖 pino 的 `Logger`：这样单测可以传一个 5 行的记录器，
 * 不必把 pino 拉进断言路径，也不必为了断言去解析 JSON 日志流。
 */
export interface ShutdownLogger {
  info(fields: Record<string, unknown>, message: string): void;
  error(fields: Record<string, unknown>, message: string): void;
}

/** {@link runShutdown} 的依赖。 */
export interface RunShutdownDeps {
  /** 关闭动作（`app.close()` + 连接池/句柄关闭）；可以是同步的。 */
  readonly close: () => Promise<void> | void;
  /** 兜底时长（毫秒）；`0` = 不设兜底（仅测试 / 特殊场景）。 */
  readonly timeoutMs: number;
  /** 退出回调（生产传 `code => process.exit(code)`；测试传记录器）。 */
  readonly exit: (code: number) => void;
  /** 日志（结构化字段 + 文案）。 */
  readonly log: ShutdownLogger;
  /** 触发本次关闭的信号名（仅用于日志；可为 `null`）。 */
  readonly signal?: string | null;
}

/** {@link runShutdown} 的三种结局（导出是为了让调用方能读懂返回值）。 */
export interface ShutdownOutcome {
  /** 进程退出码（`0` 正常 / `1` 超时或关闭失败）。 */
  readonly code: number;
  /** 是否走了超时兜底。 */
  readonly timedOut: boolean;
}

/**
 * 执行一次优雅关闭：`close()` 成功 ⇒ `exit(0)`；超时或抛错 ⇒ `exit(1)`。
 *
 * @param deps 见 {@link RunShutdownDeps}。
 * @returns 结局（同时已经调用过 `exit`）；`timedOut` 供调用方/测试区分兜底路径。
 * @throws {TypeError} `timeoutMs` 不是非负有限数（编程错误，必须炸在开发机上）。
 */
export async function runShutdown(deps: RunShutdownDeps): Promise<ShutdownOutcome> {
  const { close, timeoutMs, exit, log } = deps;
  const signal = deps.signal ?? null;

  if (!Number.isFinite(timeoutMs) || timeoutMs < 0) {
    throw new TypeError(
      `runShutdown：timeoutMs 必须是非负有限数（实测 ${String(timeoutMs)}）；` +
        "0 表示不设兜底，仅测试/特殊场景可用"
    );
  }

  log.info({ signal, timeout_ms: timeoutMs }, "收到退出信号，开始优雅关闭");

  // 先把 `close()` 归一成"永不 reject 的结局对象"：
  // * 同步抛出的 close 也变成 reject（Promise.resolve().then 兜住）；
  // * 超时路径下 close 后续才 reject 也不会变成 unhandledRejection（结局已被消费）。
  const settled = Promise.resolve()
    .then(() => close())
    .then(
      () => ({ kind: "closed" as const, error: undefined as unknown }),
      (error: unknown) => ({ kind: "failed" as const, error })
    );

  /** 统一出口：保证 `exit` 至多一次被调用，并让返回值与日志口径一致。 */
  const finish = (
    code: number,
    timedOut: boolean,
    fields: Record<string, unknown>,
    message: string
  ): ShutdownOutcome => {
    if (code === EXIT_SHUTDOWN_OK) log.info(fields, message);
    else log.error(fields, message);
    exit(code);
    return { code, timedOut };
  };

  if (timeoutMs === 0) {
    // 不设兜底：语义上等于"无限等"，仅测试 / 特殊场景使用。
    const outcome = await settled;
    if (outcome.kind === "failed") {
      return finish(
        EXIT_SHUTDOWN_FAILED,
        false,
        { signal, err: outcome.error },
        "关闭失败（未设兜底，直接以失败码退出）"
      );
    }
    return finish(EXIT_SHUTDOWN_OK, false, { signal }, "已关闭");
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<{ kind: "timeout" }>((resolve) => {
    timer = setTimeout(() => {
      resolve({ kind: "timeout" });
    }, timeoutMs);
  });

  const raced = await Promise.race([settled, timeout]);
  // 无论谁赢都要清掉定时器：否则这个 timer 会让事件循环多活 `timeoutMs`。
  if (timer !== undefined) clearTimeout(timer);

  if (raced.kind === "timeout") {
    return finish(
      EXIT_SHUTDOWN_FAILED,
      true,
      { signal, timeout_ms: timeoutMs },
      "优雅关闭超时，强制退出（避免被空闲 keep-alive 连接挂住后只能等 SIGKILL）"
    );
  }
  if (raced.kind === "failed") {
    return finish(EXIT_SHUTDOWN_FAILED, false, { signal, err: raced.error }, "关闭失败，以失败码退出");
  }
  return finish(EXIT_SHUTDOWN_OK, false, { signal }, "已关闭");
}

/** 触发关闭的函数（`main` 把 SIGINT / SIGTERM 都接到它上面）。 */
export type ShutdownTrigger = (signal?: string | null) => Promise<ShutdownOutcome>;

/** {@link createShutdownHandler} 的依赖。 */
export interface ShutdownHandlerDeps {
  readonly close: () => Promise<void> | void;
  readonly timeoutMs: number;
  readonly exit: (code: number) => void;
  readonly log: ShutdownLogger;
  /**
   * 实际执行体（缺省 {@link runShutdown}）。
   *
   * 只为测试 open：注入一个计数器就能断言「并发双信号只执行一次」，
   * 而不必为了造出"两次真实关闭"去挂住事件循环。
   */
  readonly run?: (deps: RunShutdownDeps) => Promise<ShutdownOutcome>;
}

/** {@link createShutdownHandler} 的产物。 */
export interface ShutdownHandler {
  /** 触发关闭；并发调用会拿到**同一个** Promise，`run` 只执行一次。 */
  readonly shutdown: ShutdownTrigger;
  /** 实际执行次数（并发的第二次及以后不再执行）。 */
  readonly runs: () => number;
  /** 是否已经开始关闭（供"启动后立刻收到信号"的竞态判断）。 */
  readonly started: () => boolean;
}

/**
 * 造一个"首次调用才真正执行"的关闭触发器。
 *
 * 为什么需要这个闸门：`process.once("SIGINT")` 与 `process.once("SIGTERM")` 是**两个**
 * 独立的监听器，`once` 只保证同名信号不重入。编排系统常见行为是先 SIGTERM、宽限期后
 * SIGINT（Ctrl-C 也是 SIGINT），若不闸门就会跑两遍 `close()` —— 第二次面对的是已关闭的
 * 连接池（`pool.end()` 二次调用会抛 `Cannot use a pool after calling end`），
 * 于是优雅关闭反而以"关闭失败"告终。
 *
 * @param deps 见 {@link ShutdownHandlerDeps}。
 * @returns 触发器 + 只读计数（测试用）。
 */
export function createShutdownHandler(deps: ShutdownHandlerDeps): ShutdownHandler {
  const run = deps.run ?? runShutdown;
  let execution: Promise<ShutdownOutcome> | null = null;
  let runs = 0;

  const shutdown: ShutdownTrigger = (signal = null) => {
    if (execution !== null) {
      // 第二次信号：**不**重复关闭，只记一条日志（幂等，且不产生第二个 exit）。
      deps.log.info({ signal }, "关闭已在进行中，忽略重复信号");
      return execution;
    }
    runs += 1;
    execution = run({
      close: deps.close,
      timeoutMs: deps.timeoutMs,
      exit: deps.exit,
      log: deps.log,
      signal,
    });
    return execution;
  };

  return {
    shutdown,
    runs: () => runs,
    started: () => execution !== null,
  };
}
