// ---------------------------------------------------------------------------
// WBTimeAI · 设置·系统分区单测（V0.4.6 缺陷 L-3：组织只读卡）
//
// 覆盖：
//   ① 组织卡成功态：列表取**首条** → 以其 id 调详情，展示 name / slug / id
//      （同时证明 `GET /organizations` 与 `GET /organizations/{id}` 均被真实消费）；
//   ② 组织卡 loading 态：列表未返回 → `Skeleton`（`settings-organization-loading`）；
//   ③ 组织卡 error 态：列表 500 → muted 文案「加载失败」；
//   ④ 组织卡空态：列表 `[]` → muted 文案「暂无组织」。
//
// 全部以 `server.use` 内联打桩（不改 `src/test/msw-handlers.ts`）；
// `server.listen({onUnhandledRequest:"error"})` 要求 `/settings/system`、`/plugins`、
// `/audit` 也一并打桩（系统分区同屏渲染这三个区块）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { SystemSection } from "@/components/settings/sections/SystemSection";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";
import type { OrganizationResponse } from "@/types";

/** 系统信息（保证 `settings-system-info` 渲染，排除系统块自身 loading 干扰）。 */
const SYSTEM = { mode: "local", app_name: "WBTimeAI", app_version: "0.4.6" };

/** 组织列表首条。 */
const ORGANIZATION: OrganizationResponse = {
  id: "org-1",
  tenant_id: "tenant-1",
  name: "Acme 工作室",
  slug: "acme",
};

/** 第二个组织（用于断言「只取首条」）。 */
const ORGANIZATION_OTHER: OrganizationResponse = {
  id: "org-2",
  tenant_id: "tenant-1",
  name: "Beta 工作室",
  slug: "beta",
};

/** 渲染整个系统分区（独立 QueryClient；禁用重试）。 */
function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SystemSection />
    </QueryClientProvider>,
  );
}

/** 打桩「与本卡无关」的兄弟区块（插件 / 审计），避免 MSW 未匹配请求报错。 */
function stubSiblingBlocks() {
  server.use(
    http.get("/api/v1/settings/system", () => shell(SYSTEM)),
    http.get("/api/v1/plugins", () => shell([])),
    http.get("/api/v1/audit", () => shell([])),
  );
}

describe("SystemSection · 组织只读卡（缺陷 L-3）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.getState().setSession({ accessToken: "test", refreshToken: "test-refresh" });
  });

  it("成功态：列表取首条 → 以首条 id 调详情，展示 name / slug / id", async () => {
    stubSiblingBlocks();
    const detailRequests: string[] = [];
    server.use(
      http.get("/api/v1/organizations", () => shell([ORGANIZATION, ORGANIZATION_OTHER])),
      http.get("/api/v1/organizations/:organizationId", ({ params }) => {
        detailRequests.push(String(params.organizationId));
        return shell(ORGANIZATION);
      }),
    );
    renderSection();

    expect(await screen.findByTestId("settings-organization-info")).toBeInTheDocument();
    expect(screen.getByTestId("settings-organization-name")).toHaveTextContent("Acme 工作室");
    expect(screen.getByTestId("settings-organization-slug")).toHaveTextContent("acme");
    expect(screen.getByTestId("settings-organization-id")).toHaveTextContent("org-1");

    // 详情接口被**真实消费**，且用的是列表首条 id（不是硬编码 / 不是第二条）。
    expect(detailRequests).toEqual(["org-1"]);
    // 只读卡：无编辑动作。
    expect(screen.queryByRole("button", { name: /编辑|保存|删除/ })).not.toBeInTheDocument();
  });

  it("loading 态：组织列表未返回 → Skeleton", () => {
    stubSiblingBlocks();
    server.use(http.get("/api/v1/organizations", () => new Promise<Response>(() => undefined)));
    renderSection();

    expect(screen.getByTestId("settings-organization-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-organization-info")).not.toBeInTheDocument();
    expect(screen.queryByTestId("settings-organization-empty")).not.toBeInTheDocument();
  });

  it("error 态：列表 500 → muted 文案「加载失败」", async () => {
    stubSiblingBlocks();
    server.use(
      http.get("/api/v1/organizations", () =>
        HttpResponse.json({ code: "INTERNAL_ERROR", message: "boom", data: {} }, { status: 500 }),
      ),
    );
    renderSection();

    const error = await screen.findByTestId("settings-organization-error");
    expect(error).toHaveTextContent("加载失败");
    expect(error).toHaveClass("text-muted-foreground");
  });

  it("空态：列表 [] → muted 文案「暂无组织」，且不发详情请求", async () => {
    stubSiblingBlocks();
    let detailCalls = 0;
    server.use(
      http.get("/api/v1/organizations", () => shell([])),
      http.get("/api/v1/organizations/:organizationId", () => {
        detailCalls += 1;
        return shell(ORGANIZATION);
      }),
    );
    renderSection();

    const empty = await screen.findByTestId("settings-organization-empty");
    expect(empty).toHaveTextContent("暂无组织");
    expect(empty).toHaveClass("text-muted-foreground");
    expect(detailCalls).toBe(0);
  });
});
