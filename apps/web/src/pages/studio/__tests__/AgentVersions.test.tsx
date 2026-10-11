// ---------------------------------------------------------------------------
// Astra AI · AgentVersions 单测（W8 / T2-41；W10 / T2-52 补强 · U-P2-30）
//
// 覆盖：
//   ① 展示 Agent 名与版本列表，标记「当前版本」（`current_version_id`）；
//   ② 一次发布 = 一个新 `agent_version`（不可变）；
//   ③ `can()` 守卫：无 `agent:publish` 时发布卡片不渲染。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { AgentVersions } from "@/pages/studio/AgentVersions";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** Agent 夹具（`current_version_id` = v1，用于「当前版本」标记）。 */
const AGENT = {
  id: "a1",
  tenant_id: "t1",
  name: "Coder",
  workspace_id: "w1",
  description: null,
  type: "PRIMARY",
  status: "ACTIVE",
  current_version_id: "v1",
  created_by: "u1",
  created_at: null,
  updated_at: null,
};

/** 版本夹具（v1 为当前版本；v2 历史）。 */
const VERSION_1 = {
  id: "v1",
  agent_id: "a1",
  version: "1",
  system_prompt: "",
  model_config: {},
  runtime_config: {},
  status: "PUBLISHED",
  created_by: "u1",
  created_at: "2026-10-13T00:00:00Z",
};
const VERSION_2 = { ...VERSION_1, id: "v2", version: "2", created_at: "2026-10-14T00:00:00Z" };
const VERSION_3 = { ...VERSION_1, id: "v3", version: "3", created_at: "2026-10-15T00:00:00Z" };

/** 渲染 AgentVersions（Router 注入 `:agentId` 路由参数）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/studio/agents/a1"]}>
        <Routes>
          <Route path="/studio/agents/:agentId" element={<AgentVersions />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AgentVersions", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/agents/:agentId", () => shell(AGENT)),
      http.get("/api/v1/agents/:agentId/versions", () => shell([VERSION_1, VERSION_2])),
      http.post("/api/v1/agents/:agentId/publish", () => shell(VERSION_3, 201)),
    );
  });

  it("展示 Agent 名与版本列表，并标记「当前版本」", async () => {
    renderPage();

    // `agent` 详情为异步加载：元素先以 id 兜底渲染，待名称就位再断言。
    await waitFor(() => expect(screen.getByTestId("versions-agent")).toHaveTextContent("Coder"));

    const rowV1 = await screen.findByTestId("version-row-1");
    expect(rowV1).toHaveTextContent("当前版本");
    // v2 非当前版本 → 不标记。
    expect(screen.getByTestId("version-row-2")).not.toHaveTextContent("当前版本");
  });

  it("发布新版本 → 反馈新版本号（不可变快照）", async () => {
    renderPage();

    await screen.findByTestId("version-row-1");
    fireEvent.change(screen.getByTestId("versions-prompt-input"), {
      target: { value: "you are helpful" },
    });
    fireEvent.change(screen.getByTestId("versions-model-input"), {
      target: { value: "gpt-4o-mini" },
    });
    fireEvent.click(screen.getByTestId("versions-publish"));

    expect(await screen.findByTestId("versions-feedback")).toHaveTextContent("已发布版本 3");
  });

  it("can() 守卫：无 agent:publish 权限时发布卡片不渲染", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();

    expect(await screen.findByText("缺少权限：agent:publish")).toBeInTheDocument();
    expect(screen.queryByTestId("versions-publish")).not.toBeInTheDocument();
  });
});
