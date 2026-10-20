// ---------------------------------------------------------------------------
// WBTimeAI · 设置·系统·插件区块单测（V0.4.6 收口 · M07-01 第 12 条）
//
// 覆盖：
//   ① 列表渲染：`core_compat` 取自 `manifest.core_compat`（缺失 → 「未知」灰色）、
//      `entry_point` 缺失 → 「—」、非 `installed` → 琥珀 warn tag + `title` 悬浮原因；
//   ② 安装成功 → POST 201 → 失效列表重取（新行出现、弹窗关闭）；
//   ③ 409 重名 → 展示后端 `message` 且**保留弹窗**；
//   ④ 非法 manifest JSON → 行内错误且**不发请求**；
//   ⑤ 卸载：二次确认后调 DELETE（204）→ 行消失。
//
// 全部以 `server.use` 内联打桩（不改 `src/test/msw-handlers.ts`）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { PluginSection } from "@/components/settings/PluginSection";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";
import type { PluginResponse } from "@/types";

// --- jsdom 补丁：radix dialog / select 所需最小实现 ---
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe(): void {
      void 0;
    }
    unobserve(): void {
      void 0;
    }
    disconnect(): void {
      void 0;
    }
  } as unknown as typeof ResizeObserver;
}
if (typeof window.PointerEvent === "undefined") {
  window.PointerEvent = MouseEvent as unknown as typeof PointerEvent;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = (): void => {
    void 0;
  };
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = (): boolean => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = (): void => {
    void 0;
  };
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = (): void => {
    void 0;
  };
}

/** 正常插件（`manifest.core_compat` 存在）。 */
const PLUGIN_OK: PluginResponse = {
  id: "pl1",
  name: "core-tools",
  version: "1.2.0",
  kind: "tool",
  entry_point: "plugins.core_tools:register",
  permissions: ["fs:read"],
  manifest: { core_compat: ">=0.4.0" },
  status: "installed",
  installed_at: "2026-01-01T00:00:00Z",
};

/** 降级插件（缺 `core_compat` + 有 `status_reason` + 无 `entry_point`）。 */
const PLUGIN_DEGRADED: PluginResponse = {
  id: "pl2",
  name: "legacy-connector",
  version: "0.9.0",
  kind: "connector",
  entry_point: null,
  permissions: [],
  manifest: { status_reason: "内核版本过低，扩展点未加载" },
  status: "degraded",
  installed_at: null,
};

/** 渲染插件区块（独立 QueryClient；禁用重试）。 */
function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <PluginSection />
    </QueryClientProvider>,
  );
}

describe("PluginSection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useI18nStore.setState({ language: "zh-CN" });
    useUiStore.setState({ toast: null });
    useAuthStore.getState().setSession({ accessToken: "test", refreshToken: "test-refresh" });
  });

  it("列表渲染：core_compat 取 manifest、缺失显示「未知」、entry_point 缺失显示「—」、降级为琥珀 warn tag", async () => {
    server.use(http.get("/api/v1/plugins", () => shell([PLUGIN_OK, PLUGIN_DEGRADED])));
    renderSection();

    expect(await screen.findByTestId("settings-plugins-table")).toBeInTheDocument();
    // 全局（非租户隔离）明示。
    expect(screen.getByTestId("settings-plugins-scope-note")).toHaveTextContent("非租户隔离");

    // core_compat：有 → 原值；无 → 「未知」且为灰色占位（不是错误）。
    expect(screen.getByTestId("settings-plugin-core-compat-pl1")).toHaveTextContent(">=0.4.0");
    const unknownCompat = screen.getByTestId("settings-plugin-core-compat-pl2");
    expect(unknownCompat).toHaveTextContent("未知");
    expect(unknownCompat).toHaveClass("text-muted-foreground");

    // entry_point 缺失 → 「—」。
    expect(screen.getByTestId("settings-plugin-row-pl2")).toHaveTextContent("—");

    // 状态：installed 正常色；degraded → 琥珀 + title 悬浮原因。
    const okStatus = screen.getByTestId("settings-plugin-status-pl1");
    expect(okStatus).toHaveTextContent("已安装");
    expect(okStatus).toHaveClass("text-emerald-700");
    expect(okStatus.getAttribute("title")).toBeNull();

    const degradedStatus = screen.getByTestId("settings-plugin-status-pl2");
    expect(degradedStatus).toHaveTextContent("降级");
    expect(degradedStatus).toHaveClass("text-amber-700");
    expect(degradedStatus.getAttribute("title")).toBe("内核版本过低，扩展点未加载");
  });

  it("空列表 → InlineEmpty 空态", async () => {
    server.use(http.get("/api/v1/plugins", () => shell([])));
    renderSection();

    expect(await screen.findByTestId("settings-plugins-empty")).toBeInTheDocument();
    expect(screen.getByText("暂无已安装插件")).toBeInTheDocument();
  });

  it("安装成功 → POST 202/201 后关闭弹窗并失效列表重取", async () => {
    const plugins: PluginResponse[] = [PLUGIN_OK];
    let posted: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/plugins", () => shell(plugins)),
      http.post("/api/v1/plugins", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        posted = body;
        const created: PluginResponse = {
          id: "pl3",
          name: String(body.name),
          version: String(body.version),
          kind: String(body.kind),
          entry_point: null,
          permissions: [],
          manifest: {},
          status: "installed",
          installed_at: null,
        };
        plugins.push(created);
        return shell(created, 201);
      }),
    );
    renderSection();

    fireEvent.click(await screen.findByTestId("settings-plugins-install"));
    fireEvent.change(await screen.findByTestId("settings-plugin-form-name"), {
      target: { value: "new-plugin" },
    });
    fireEvent.change(screen.getByTestId("settings-plugin-form-version"), {
      target: { value: "2.0.0" },
    });
    fireEvent.change(screen.getByTestId("settings-plugin-form-permissions"), {
      target: { value: "fs:read, net:out" },
    });
    fireEvent.change(screen.getByTestId("settings-plugin-form-manifest"), {
      target: { value: '{"core_compat":">=0.4.0"}' },
    });
    fireEvent.click(screen.getByTestId("settings-plugin-form-submit"));

    // 列表失效重取 → 新行出现。
    expect(await screen.findByTestId("settings-plugin-row-pl3")).toBeInTheDocument();
    expect(posted).toMatchObject({
      name: "new-plugin",
      version: "2.0.0",
      kind: "connector",
      entry_point: null,
      permissions: ["fs:read", "net:out"],
      manifest: { core_compat: ">=0.4.0" },
    });
    await waitFor(() => {
      expect(screen.queryByTestId("settings-plugin-form")).not.toBeInTheDocument();
    });
  });

  it("409 重名 → 展示后端 message 且保留弹窗", async () => {
    server.use(
      http.get("/api/v1/plugins", () => shell([PLUGIN_OK])),
      http.post("/api/v1/plugins", () =>
        HttpResponse.json(
          { code: "CONFLICT", message: "已存在同名插件", data: { name: "core-tools" } },
          { status: 409 },
        ),
      ),
    );
    renderSection();

    fireEvent.click(await screen.findByTestId("settings-plugins-install"));
    fireEvent.change(await screen.findByTestId("settings-plugin-form-name"), {
      target: { value: "core-tools" },
    });
    fireEvent.change(screen.getByTestId("settings-plugin-form-version"), {
      target: { value: "1.0.0" },
    });
    fireEvent.click(screen.getByTestId("settings-plugin-form-submit"));

    expect(await screen.findByTestId("settings-plugin-form-error")).toHaveTextContent(
      "已存在同名插件",
    );
    // 弹窗保留（用户可改名后重试）。
    expect(screen.getByTestId("settings-plugin-form")).toBeInTheDocument();
    expect(screen.getByTestId("settings-plugin-form-name")).toHaveValue("core-tools");
  });

  it("非法 manifest JSON → 行内错误且不发请求", async () => {
    let postCount = 0;
    server.use(
      http.get("/api/v1/plugins", () => shell([PLUGIN_OK])),
      http.post("/api/v1/plugins", () => {
        postCount += 1;
        return shell({ ...PLUGIN_OK, id: "pl4" }, 201);
      }),
    );
    renderSection();

    fireEvent.click(await screen.findByTestId("settings-plugins-install"));
    fireEvent.change(await screen.findByTestId("settings-plugin-form-name"), {
      target: { value: "bad-manifest" },
    });
    fireEvent.change(screen.getByTestId("settings-plugin-form-version"), {
      target: { value: "1.0.0" },
    });
    fireEvent.change(screen.getByTestId("settings-plugin-form-manifest"), {
      target: { value: "{ not json" },
    });
    fireEvent.click(screen.getByTestId("settings-plugin-form-submit"));

    expect(await screen.findByTestId("settings-plugin-form-manifest-error")).toHaveTextContent(
      "manifest 不是合法 JSON",
    );
    expect(postCount).toBe(0);
  });

  it("卸载：二次确认后调 DELETE（204 幂等）→ 行消失", async () => {
    const plugins: PluginResponse[] = [PLUGIN_OK];
    let deletedId: string | null = null;
    server.use(
      http.get("/api/v1/plugins", () => shell(plugins)),
      http.delete("/api/v1/plugins/:pluginId", ({ params }) => {
        deletedId = String(params.pluginId);
        const index = plugins.findIndex((item) => item.id === deletedId);
        if (index >= 0) {
          plugins.splice(index, 1);
        }
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderSection();

    fireEvent.click(await screen.findByTestId("settings-plugin-uninstall-pl1"));
    // 确认框出现，此时**尚未**发请求。
    expect(await screen.findByTestId("settings-plugin-delete-dialog")).toBeInTheDocument();
    expect(deletedId).toBeNull();

    fireEvent.click(screen.getByTestId("settings-plugin-delete-submit"));
    await waitFor(() => {
      expect(deletedId).toBe("pl1");
    });
    await waitFor(() => {
      expect(screen.queryByTestId("settings-plugin-row-pl1")).not.toBeInTheDocument();
    });
  });

  // P2-2 守卫：mutation 的 `isError` / `error` 跨目标共享 → 必须在弹窗重新打开时复位。
  it("P2-2：A 卸载失败 → 关闭 → 打开 B，不得残留 A 的错误文案", async () => {
    const plugins: PluginResponse[] = [PLUGIN_OK, PLUGIN_DEGRADED];
    server.use(
      http.get("/api/v1/plugins", () => shell(plugins)),
      http.delete("/api/v1/plugins/:pluginId", () =>
        HttpResponse.json(
          { code: "INTERNAL_ERROR", message: "删除失败-A", data: {} },
          { status: 500 },
        ),
      ),
    );
    renderSection();

    // A 卸载失败 → 弹窗内展示错误。
    fireEvent.click(await screen.findByTestId("settings-plugin-uninstall-pl1"));
    fireEvent.click(await screen.findByTestId("settings-plugin-delete-submit"));
    expect(await screen.findByTestId("settings-plugin-delete-error")).toHaveTextContent(
      "删除失败-A",
    );

    // 关闭确认框。
    fireEvent.click(screen.getByTestId("settings-plugin-delete-cancel"));
    await waitFor(() => {
      expect(screen.queryByTestId("settings-plugin-delete-error")).not.toBeInTheDocument();
    });

    // 打开 B 的确认框 → 不得出现 A 的错误。
    fireEvent.click(screen.getByTestId("settings-plugin-uninstall-pl2"));
    expect(await screen.findByTestId("settings-plugin-delete-dialog")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-plugin-delete-error")).not.toBeInTheDocument();
    expect(screen.queryByText("删除失败-A")).not.toBeInTheDocument();
  });

  it("非 installed 且 manifest.status_reason 缺失 → title 回落原始 status 原文", async () => {
    const noReason: PluginResponse = {
      ...PLUGIN_DEGRADED,
      id: "pl9",
      name: "no-reason-plugin",
      manifest: {},
      status: "degraded",
    };
    server.use(http.get("/api/v1/plugins", () => shell([noReason])));
    renderSection();

    const tag = await screen.findByTestId("settings-plugin-status-pl9");
    expect(tag).toHaveTextContent("降级");
    expect(tag.getAttribute("title")).toBe("degraded");
  });
});
