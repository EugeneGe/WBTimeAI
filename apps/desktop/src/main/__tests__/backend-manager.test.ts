// ---------------------------------------------------------------------------
// BackendManager 单测（M2 · WS3 · T-03）
//
// 覆盖 §2.1 优先级链的四个分支 + spawn 未就绪回落；全部依赖注入，**确定性**、
// 不触网、不真 spawn、不依赖 Electron（node --test 直接跑编译产物）。
// ---------------------------------------------------------------------------
import assert from "node:assert/strict";
import type { ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { test } from "node:test";
import type { DesktopSettings } from "../../shared/protocol";
import { BackendManager, type SpawnFn } from "../backend-manager";

const BASE_SETTINGS: DesktopSettings = {
  rendererMode: "bundled",
  apiBaseUrl: "",
  autoSpawnBackend: true,
  port: 8080,
};

/** 构造一个只读设置来源（SettingsReader）。 */
function reader(overrides: Partial<DesktopSettings> = {}): { load(): DesktopSettings } {
  const settings: DesktopSettings = { ...BASE_SETTINGS, ...overrides };
  return { load: () => settings };
}

/** ChildProcess 替身：可被 kill 并触发 exit。 */
class FakeChild extends EventEmitter {
  pid = 4321;
  exitCode: number | null = null;
  signalCode: NodeJS.Signals | null = null;

  kill(signal?: NodeJS.Signals | number): boolean {
    this.signalCode = typeof signal === "string" ? signal : "SIGTERM";
    this.exitCode = 0;
    this.emit("exit", 0, this.signalCode);
    return true;
  }
}

test("已配置远端 URL → kind=remote（最高优先，用户可覆盖）", async () => {
  const manager = new BackendManager(reader({ apiBaseUrl: "http://remote.test:9000/" }), {
    probeImpl: async () => true,
    whichImpl: () => false,
  });

  const target = await manager.resolve();

  assert.equal(target.kind, "remote");
  assert.equal(target.baseUrl, "http://remote.test:9000");
  assert.equal(manager.getApiBaseUrl(), "http://remote.test:9000");
});

test("无远端 + PATH 有 astra + autoSpawn → spawn 本地子进程（kind=spawned）", async () => {
  const child = new FakeChild();
  const spawnImpl: SpawnFn = () => child as unknown as ChildProcess;
  const manager = new BackendManager(reader(), {
    spawnImpl,
    probeImpl: async () => true,
    whichImpl: (command) => command === "astra",
    spawnReadyTimeoutMs: 200,
    probePollIntervalMs: 1,
  });

  const target = await manager.resolve();

  assert.equal(target.kind, "spawned");
  assert.equal(target.pid, 4321);
  assert.equal(target.baseUrl, "http://127.0.0.1:8080");
  await manager.stop();
});

test("无远端 + 无 astra + 已有本地后端可达 → kind=existing", async () => {
  const manager = new BackendManager(reader(), {
    probeImpl: async (baseUrl) => baseUrl === "http://127.0.0.1:8080",
    whichImpl: () => false,
  });

  const target = await manager.resolve();

  assert.equal(target.kind, "existing");
  assert.equal(target.baseUrl, "http://127.0.0.1:8080");
});

test("全部不可用 → kind=none（壳显示引导）", async () => {
  const manager = new BackendManager(reader(), {
    probeImpl: async () => false,
    whichImpl: () => false,
  });

  const target = await manager.resolve();

  assert.equal(target.kind, "none");
  assert.equal(target.baseUrl, "");
});

test("spawn 但未就绪 → 回收子进程并回落 none", async () => {
  const child = new FakeChild();
  const spawnImpl: SpawnFn = () => child as unknown as ChildProcess;
  const manager = new BackendManager(reader(), {
    spawnImpl,
    probeImpl: async () => false,
    whichImpl: () => true,
    spawnReadyTimeoutMs: 30,
    probePollIntervalMs: 1,
    killGraceMs: 20,
  });

  const target = await manager.resolve();

  assert.equal(target.kind, "none");
  assert.notEqual(child.signalCode, null);
});
