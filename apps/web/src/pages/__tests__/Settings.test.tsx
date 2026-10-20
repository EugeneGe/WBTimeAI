// ---------------------------------------------------------------------------
// WBTimeAI · Settings 桌面数据目录 Card 单测（V0.4.2 · W2 · T4）
//
// 覆盖：
//   ① 无 `window.wbtimeAiDesktop`（纯 Web 部署）→ **不渲染**「数据目录」Card；
//   ② 有 `window.wbtimeAiDesktop`（桌面壳内）→ 渲染 Card 并回填 `dataDir`；
//   ③ 保存：合法绝对路径 → `setSettings({ dataDir })`，反馈「重启壳后生效」；
//   ④ 恢复默认：`setSettings({ dataDir: "" })`，反馈「已恢复默认」；
//   ⑤ 渲染层即时提示：相对路径 → 拦截（不发起 `setSettings`）；
//   ⑥ 主进程拒绝：`setSettings` 抛错 → 回显「主进程校验未通过」。
//
// 以 `window.wbtimeAiDesktop` 打桩（不经 IPC）；Settings 页未登录 → 各后端 Query 禁用、零网络。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Settings } from "@/pages/Settings";
import { useAuthStore } from "@/stores/authStore";
import type {
  WBTimeAIDesktopApi,
  DesktopBackendStatus,
  DesktopRuntimeStatus,
  DesktopSettings,
} from "@/types/desktop";

const BASE_SETTINGS: DesktopSettings = {
  rendererMode: "bundled",
  apiBaseUrl: "",
  autoSpawnBackend: true,
  port: 8080,
  dataDir: "",
  // V0.4.5 B3·F-12：桌面设置新增 `language`（默认英文）；桩补齐字段形状。
  language: "en",
};

const NONE_STATUS: DesktopBackendStatus = {
  kind: "none",
  baseUrl: "",
  pid: null,
  detail: "test",
};

/** 运行时状态打桩默认值（T6）。 */
const IDLE_RUNTIME: DesktopRuntimeStatus = {
  phase: "idle",
  runtimeDir: "C:\\Users\\x\\AppData\\Local\\WBTimeAI\\runtime",
  ready: false,
  extractedBytes: 0,
  totalBytes: 0,
  entriesDone: 0,
  entriesTotal: 0,
  detail: "尚未安装",
};

/**
 * 构造 `window.wbtimeAiDesktop` 打桩。
 *
 * @param initial 初始桌面设置。
 * @param onSet `setSettings` 回调（可抛错模拟主进程拒绝）。
 * @param runtimeStatus 运行时状态（默认 idle）。
 * @returns `api` + 记录的 `patches` + 运行时调用计数。
 */
function makeApi(
  initial: DesktopSettings,
  onSet?: (patch: Partial<DesktopSettings>) => void,
  runtimeStatus: DesktopRuntimeStatus = IDLE_RUNTIME,
) {
  const state: DesktopSettings = { ...initial };
  const patches: Array<Partial<DesktopSettings>> = [];
  const runtimeCalls = { install: 0, cancel: 0 };
  const api: WBTimeAIDesktopApi = {
    getStatus: async () => NONE_STATUS,
    setRemote: async () => NONE_STATUS,
    restartBackend: async () => NONE_STATUS,
    getSettings: async () => ({ ...state }),
    setSettings: async (patch) => {
      patches.push(patch);
      onSet?.(patch);
      Object.assign(state, patch);
      return { ...state };
    },
    onStatus: () => () => undefined,
    getRuntimeStatus: async () => runtimeStatus,
    installRuntime: async () => {
      runtimeCalls.install += 1;
      return runtimeStatus;
    },
    cancelRuntime: async () => {
      runtimeCalls.cancel += 1;
      return runtimeStatus;
    },
    onRuntimeProgress: () => () => undefined,
    // V0.4.4 Bug7：新增 IPC（本页不用，桩补齐接口形状）。
    pickDirectory: async () => null,
    // V0.4.5 B5 · F-26.5：壳动作（本页不用，桩补齐接口形状）。
    shellAction: async () => undefined,
  };
  return { api, patches, runtimeCalls };
}

/** 渲染 Settings（独立 QueryClient，禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Settings />
    </QueryClientProvider>,
  );
}

describe("Settings · 桌面数据目录 Card", () => {
  beforeEach(() => {
    // 未登录：后端 Query 全禁用（零网络）；桌面 Card 与登录态无关。
    useAuthStore.setState({ isAuthenticated: false, accessToken: null, permissions: [] });
    delete window.wbtimeAiDesktop;
  });

  afterEach(() => {
    delete window.wbtimeAiDesktop;
  });

  it("无 window.wbtimeAiDesktop → 不渲染数据目录 Card（纯 Web 隐藏）", () => {
    renderPage();
    expect(screen.queryByTestId("desktop-data-dir-card")).toBeNull();
  });

  it("有 window.wbtimeAiDesktop → 渲染 Card 并回填 dataDir", async () => {
    const { api } = makeApi({ ...BASE_SETTINGS, dataDir: "D:\\WBTimeAIData" });
    window.wbtimeAiDesktop = api;

    renderPage();

    expect(await screen.findByTestId("desktop-data-dir-card")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("desktop-data-dir-input")).toHaveValue("D:\\WBTimeAIData");
    });
  });

  it("保存合法绝对路径 → setSettings({ dataDir }) + 反馈", async () => {
    const { api, patches } = makeApi({ ...BASE_SETTINGS });
    window.wbtimeAiDesktop = api;

    renderPage();
    const input = await screen.findByTestId("desktop-data-dir-input");
    await waitFor(() => expect(input).toBeEnabled());

    fireEvent.change(input, { target: { value: "D:\\NewData" } });
    fireEvent.click(screen.getByTestId("desktop-data-dir-save"));

    expect(await screen.findByTestId("desktop-data-dir-feedback")).toHaveTextContent(
      "已保存，重启桌面壳后生效：D:\\NewData",
    );
    expect(patches).toEqual([{ dataDir: "D:\\NewData" }]);
  });

  it("恢复默认 → setSettings({ dataDir: '' }) + 反馈", async () => {
    const { api, patches } = makeApi({ ...BASE_SETTINGS, dataDir: "D:\\WBTimeAIData" });
    window.wbtimeAiDesktop = api;

    renderPage();
    await screen.findByTestId("desktop-data-dir-card");

    fireEvent.click(screen.getByTestId("desktop-data-dir-reset"));

    expect(await screen.findByTestId("desktop-data-dir-feedback")).toHaveTextContent(
      "已恢复默认（~/.wbtime-ai）",
    );
    expect(patches).toEqual([{ dataDir: "" }]);
  });

  it("渲染层即时提示：相对路径被拦截（不发起 setSettings）", async () => {
    const { api, patches } = makeApi({ ...BASE_SETTINGS });
    window.wbtimeAiDesktop = api;

    renderPage();
    const input = await screen.findByTestId("desktop-data-dir-input");
    await waitFor(() => expect(input).toBeEnabled());

    fireEvent.change(input, { target: { value: "relative/data" } });
    fireEvent.click(screen.getByTestId("desktop-data-dir-save"));

    expect(await screen.findByText(/请输入绝对路径/)).toBeInTheDocument();
    expect(patches).toHaveLength(0);
  });

  it("主进程拒绝：setSettings 抛错 → 回显主进程校验未通过", async () => {
    const { api } = makeApi({ ...BASE_SETTINGS }, () => {
      throw new Error(
        "Error invoking remote method 'settings:set': Error: 数据目录非法：目录不可写",
      );
    });
    window.wbtimeAiDesktop = api;

    renderPage();
    const input = await screen.findByTestId("desktop-data-dir-input");
    await waitFor(() => expect(input).toBeEnabled());

    fireEvent.change(input, { target: { value: "D:\\NoPerm" } });
    fireEvent.click(screen.getByTestId("desktop-data-dir-save"));

    const errorEl = await screen.findByTestId("desktop-data-dir-error");
    expect(errorEl).toHaveTextContent("主进程校验未通过：数据目录非法：目录不可写");
  });
});

describe("Settings · 便携运行时 Card（T6）", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: false, accessToken: null, permissions: [] });
    delete window.wbtimeAiDesktop;
  });

  afterEach(() => {
    delete window.wbtimeAiDesktop;
  });

  it("无 window.wbtimeAiDesktop → 不渲染运行时 Card", () => {
    renderPage();
    expect(screen.queryByTestId("desktop-runtime-card")).toBeNull();
  });

  it("有 window.wbtimeAiDesktop → 渲染 Card 并显示阶段（已就绪）", async () => {
    const { api } = makeApi({ ...BASE_SETTINGS }, undefined, {
      ...IDLE_RUNTIME,
      phase: "done",
      ready: true,
      detail: "运行时已就绪",
    });
    window.wbtimeAiDesktop = api;

    renderPage();

    expect(await screen.findByTestId("desktop-runtime-card")).toBeInTheDocument();
    expect(screen.getByTestId("desktop-runtime-phase")).toHaveTextContent("已就绪");
  });

  it("解压中 → 显示进度（50%）、重试禁用、点击取消触发 cancelRuntime", async () => {
    const { api, runtimeCalls } = makeApi({ ...BASE_SETTINGS }, undefined, {
      ...IDLE_RUNTIME,
      phase: "extracting",
      totalBytes: 1048576 * 10,
      extractedBytes: 1048576 * 5,
      detail: "解压中…",
    });
    window.wbtimeAiDesktop = api;

    renderPage();
    await screen.findByTestId("desktop-runtime-card");

    expect(screen.getByTestId("desktop-runtime-progress")).toHaveTextContent("50%");
    expect(screen.getByTestId("desktop-runtime-retry")).toBeDisabled();

    fireEvent.click(screen.getByTestId("desktop-runtime-cancel"));
    await waitFor(() => expect(runtimeCalls.cancel).toBe(1));
  });

  it("错误态 → 重试可用并触发 installRuntime", async () => {
    const { api, runtimeCalls } = makeApi({ ...BASE_SETTINGS }, undefined, {
      ...IDLE_RUNTIME,
      phase: "error",
      detail: "runtime.zip 校验失败",
    });
    window.wbtimeAiDesktop = api;

    renderPage();
    await screen.findByTestId("desktop-runtime-card");

    fireEvent.click(screen.getByTestId("desktop-runtime-retry"));
    await waitFor(() => expect(runtimeCalls.install).toBe(1));
  });
});
