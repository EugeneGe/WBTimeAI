// ---------------------------------------------------------------------------
// 后端策略解析（M2 · WS3 · T-03）
//
// 按设计 §2.1 优先级链解析后端目标：
//   1) 设置中的远端 URL（最高优先，用户可覆盖）        → kind=remote
//   2) spawn 本地 `astra run`（PATH 有 astra + 开关开）→ kind=spawned
//   3) 探测 127.0.0.1:<port>/health 通                  → kind=existing
//   4) 均不可用                                        → kind=none
//
// 依赖（spawn / 探测 / which）均可注入，便于确定性单测；退出时回收子进程。
// ---------------------------------------------------------------------------
import { spawn as nodeSpawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { request as httpRequest } from "node:http";
import type { BackendStatus, DesktopSettings } from "../shared/protocol";
import type { SettingsReader } from "./settings-store";

/** spawn 依赖签名（可注入替身）。 */
export type SpawnFn = (
  command: string,
  args: string[],
  options: { env: NodeJS.ProcessEnv; stdio: "ignore"; detached: boolean },
) => ChildProcess;

/** `/health` 探测签名（可注入替身）。 */
export type ProbeFn = (baseUrl: string, timeoutMs: number) => Promise<boolean>;

/** 命令存在性探测签名（可注入替身）。 */
export type WhichFn = (command: string) => boolean;

/** 可注入依赖 + 超时参数。 */
export interface BackendManagerOptions {
  spawnImpl?: SpawnFn;
  probeImpl?: ProbeFn;
  whichImpl?: WhichFn;
  probeTimeoutMs?: number;
  spawnReadyTimeoutMs?: number;
  probePollIntervalMs?: number;
  killGraceMs?: number;
}

interface ResolvedOptions {
  spawnImpl: SpawnFn;
  probeImpl: ProbeFn;
  whichImpl: WhichFn;
  probeTimeoutMs: number;
  spawnReadyTimeoutMs: number;
  probePollIntervalMs: number;
  killGraceMs: number;
}

const DEFAULTS = {
  probeTimeoutMs: 1500,
  spawnReadyTimeoutMs: 20000,
  probePollIntervalMs: 500,
  killGraceMs: 3000,
} as const;

/** 全局命令。 */
const ASTRA_COMMAND = "astra";

/** 默认 `/health` 探测（Node 内建 http，无第三方依赖）。 */
function defaultProbe(baseUrl: string, timeoutMs: number): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    let settled = false;
    const done = (value: boolean): void => {
      if (!settled) {
        settled = true;
        resolve(value);
      }
    };
    try {
      const target = new URL("/health", ensureTrailingSlash(baseUrl));
      const req = httpRequest(
        {
          protocol: target.protocol,
          hostname: target.hostname,
          port: target.port !== "" ? target.port : undefined,
          path: target.pathname,
          method: "GET",
          timeout: timeoutMs,
        },
        (res) => {
          res.resume();
          done(res.statusCode === 200);
        },
      );
      req.on("timeout", () => {
        req.destroy();
        done(false);
      });
      req.on("error", () => done(false));
      req.end();
    } catch {
      done(false);
    }
  });
}

/** 默认命令探测：扫描 `PATH`（Windows 兼容 PATHEXT 常见扩展）。 */
function defaultWhich(command: string): boolean {
  const pathValue = process.env.PATH ?? "";
  const separator = process.platform === "win32" ? ";" : ":";
  const dirs = pathValue.split(separator).filter((entry) => entry.length > 0);
  const candidates =
    process.platform === "win32"
      ? [`${command}.exe`, `${command}.cmd`, `${command}.bat`, command]
      : [command];
  const joiner = separator === ";" ? "\\" : "/";
  for (const dir of dirs) {
    for (const candidate of candidates) {
      if (existsSync(`${dir}${joiner}${candidate}`)) {
        return true;
      }
    }
  }
  return false;
}

function ensureTrailingSlash(url: string): string {
  return url.endsWith("/") ? url : `${url}/`;
}

/** 去掉尾斜杠，得到稳定基址。 */
function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

/**
 * 后端目标解析与管理器。
 */
export class BackendManager {
  private target: BackendStatus = {
    kind: "none",
    baseUrl: "",
    pid: null,
    detail: "尚未解析",
  };
  private settings: DesktopSettings;
  private child: ChildProcess | null = null;
  private readonly options: ResolvedOptions;

  /**
   * @param settingsReader 设置来源（构造时读取一次）。
   * @param options 可注入依赖与超时（默认见 {@link DEFAULTS}）。
   */
  constructor(
    private readonly settingsReader: SettingsReader,
    options: BackendManagerOptions = {},
  ) {
    this.settings = this.settingsReader.load();
    this.options = {
      spawnImpl: options.spawnImpl ?? (nodeSpawn as unknown as SpawnFn),
      probeImpl: options.probeImpl ?? defaultProbe,
      whichImpl: options.whichImpl ?? defaultWhich,
      probeTimeoutMs: options.probeTimeoutMs ?? DEFAULTS.probeTimeoutMs,
      spawnReadyTimeoutMs: options.spawnReadyTimeoutMs ?? DEFAULTS.spawnReadyTimeoutMs,
      probePollIntervalMs: options.probePollIntervalMs ?? DEFAULTS.probePollIntervalMs,
      killGraceMs: options.killGraceMs ?? DEFAULTS.killGraceMs,
    };
  }

  /** 用最新设置更新解析上下文（不触发重解析）。 */
  applySettings(settings: DesktopSettings): void {
    this.settings = settings;
  }

  /** 当前后端状态。 */
  status(): BackendStatus {
    return { ...this.target };
  }

  /** 当前 API 基址（`kind=none` 时为空串）。 */
  getApiBaseUrl(): string {
    return this.target.baseUrl;
  }

  /**
   * 按优先级链解析后端目标。
   *
   * @returns 选定的后端状态（`kind=none` 表示无可用后端）。
   */
  async resolve(): Promise<BackendStatus> {
    const remote = this.settings.apiBaseUrl.trim();
    if (remote !== "") {
      const baseUrl = normalizeBaseUrl(remote);
      const reachable = await this.options.probeImpl(baseUrl, this.options.probeTimeoutMs);
      return this.setTarget({
        kind: "remote",
        baseUrl,
        pid: null,
        detail: reachable ? "已连接远端后端" : "远端不可达（请检查 URL / 网络）",
      });
    }

    if (this.settings.autoSpawnBackend && this.options.whichImpl(ASTRA_COMMAND)) {
      try {
        return await this.spawnLocal();
      } catch {
        // spawn 失败 → 继续尝试已有本地后端。
      }
    }

    const existingBaseUrl = `http://127.0.0.1:${this.settings.port}`;
    if (await this.options.probeImpl(existingBaseUrl, this.options.probeTimeoutMs)) {
      return this.setTarget({
        kind: "existing",
        baseUrl: existingBaseUrl,
        pid: null,
        detail: "已连接本地后端",
      });
    }

    return this.setTarget({
      kind: "none",
      baseUrl: "",
      pid: null,
      detail: "未发现可用后端，请配置远端或安装 astra",
    });
  }

  /** 重启：回收现有子进程后重新解析。 */
  async restart(): Promise<BackendStatus> {
    await this.stop();
    return this.resolve();
  }

  /** 回收由壳拉起的后端子进程（幂等）。 */
  async stop(): Promise<void> {
    const child = this.child;
    this.child = null;
    if (!child || child.exitCode !== null || child.signalCode !== null) {
      return;
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        child.kill("SIGKILL");
        resolve();
      }, this.options.killGraceMs);
      child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
      child.kill("SIGTERM");
    });
  }

  /** 拉起本地 `astra run` 并等待 `/health` 就绪。 */
  private async spawnLocal(): Promise<BackendStatus> {
    const baseUrl = `http://127.0.0.1:${this.settings.port}`;
    const child = this.options.spawnImpl(ASTRA_COMMAND, ["run"], {
      env: process.env,
      stdio: "ignore",
      detached: false,
    });
    this.child = child;
    child.once("exit", () => {
      if (this.child === child) {
        this.child = null;
      }
    });

    const ready = await this.waitUntilReady(baseUrl, this.options.spawnReadyTimeoutMs);
    if (!ready) {
      await this.stop();
      throw new Error("spawned backend did not become ready in time");
    }
    return this.setTarget({
      kind: "spawned",
      baseUrl,
      pid: child.pid ?? null,
      detail: "已拉起本地后端",
    });
  }

  /** 轮询 `/health` 直到就绪或超时。 */
  private async waitUntilReady(baseUrl: string, timeoutMs: number): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      if (await this.options.probeImpl(baseUrl, this.options.probeTimeoutMs)) {
        return true;
      }
      if (Date.now() >= deadline) {
        return false;
      }
      await new Promise<void>((resolve) => setTimeout(resolve, this.options.probePollIntervalMs));
    }
  }

  private setTarget(target: BackendStatus): BackendStatus {
    this.target = target;
    return { ...target };
  }
}
