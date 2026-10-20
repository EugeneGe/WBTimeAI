// ---------------------------------------------------------------------------
// WBTimeAI · AgentStudio 单测（W8 / T2-41 · U-P2-17 / U-P2-30）
//
// 覆盖：
//   ① 九分区导航齐备（Basic / Model / Prompt / Skills / Tools / MCP / Knowledge /
//      Memory / Permission）；
//   ② 面板 CRUD（创建 / 更新 Agent、绑定 Skill、创建 Skill）；
//   ③ 版本发布产生新 `agent_version`；
//   ④ `can()` 权限守卫生效（`RequirePermission`）。
//
// 面板复用既有 capability（service + hooks → msw 契约 handler）；本文件以
// `server.use(...)` **就近**注册 Studio 特有的契约 handler（不修改共享 msw 夹具）。
//
// 🔴 V0.4.6 缺陷 L-4 / 批次 B2：页面文案已全量 i18n 化（默认语言 `en`），故本文件在
//    `beforeEach` 显式切到 `zh-CN` 以保留既有中文断言（**断言文案不改**），
//    `afterEach` 复位 `en` 防跨文件语言污染；另有 1 条 en 态守卫用例。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AgentStudio } from "@/pages/studio/AgentStudio";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** Agent 夹具（与既有 `msw-handlers` 的 `AGENT` 对齐）。 */
const AGENT = {
  id: "a1",
  tenant_id: "t1",
  name: "Coder",
  workspace_id: "w1",
  description: null,
  type: "PRIMARY",
  status: "DRAFT",
  current_version_id: null,
  created_by: "u1",
  created_at: null,
  updated_at: null,
};

/** Skill 夹具（可绑定）。 */
const SKILL = {
  id: "sk1",
  tenant_id: "t1",
  name: "demo-skill",
  display_name: "Demo Skill",
  description: null,
  category: "general",
  status: "ACTIVE",
  current_version_id: null,
  current_version: null,
  created_by: "u1",
  created_at: null,
};

/** 新建 Skill 夹具（与既有绑定区分，便于断言计数）。 */
const NEW_SKILL = { ...SKILL, id: "sk-new", name: "new-skill", display_name: "New Skill" };

/** MCP Server 夹具。 */
const MCP_SERVER = {
  id: "ms1",
  tenant_id: "t1",
  name: "demo-server",
  transport: "stdio",
  endpoint: null,
  command: null,
  args: [],
  env_ref: {},
  credential_id: null,
  status: "ACTIVE",
  workspace_id: null,
  created_at: null,
};

/** 渲染 Agent Studio（独立 QueryClient + 路由上下文）。 */
function renderStudio() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AgentStudio />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AgentStudio", () => {
  beforeEach(() => {
    // 文案断言均为中文 → 用例内显式指定 `zh-CN`（默认语言是 `en`）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
    // 就近注册 Studio 特有契约 handler（既有共享 handler 覆盖其余端点）。
    server.use(
      http.get("/api/v1/agents/:agentId", () => shell(AGENT)),
      http.put("/api/v1/agents/:agentId", () => shell(AGENT)),
      http.get("/api/v1/skills", () => shell([SKILL])),
      http.post("/api/v1/skills", () => shell(NEW_SKILL, 201)),
      http.get("/api/v1/mcp/servers", () => shell([MCP_SERVER])),
      http.get("/api/v1/permissions/check", () =>
        shell({
          capability: "x",
          allowed: true,
          effect: "ALLOW",
          reason: "ok",
          source: null,
        }),
      ),
    );
  });

  afterEach(() => {
    // 复位默认语言，避免污染其他测试文件（vitest 同进程复用 store）。
    useI18nStore.setState({ language: "en" });
  });

  it("九分区导航齐备，且可创建 / 更新 Agent（CRUD）", async () => {
    renderStudio();

    for (const panel of [
      "basic",
      "model",
      "prompt",
      "skills",
      "tools",
      "mcp",
      "knowledge",
      "memory",
      "permission",
    ]) {
      expect(screen.getByTestId(`studio-nav-${panel}`)).toBeInTheDocument();
    }

    // -- 创建（C）：POST /agents --
    fireEvent.change(screen.getByTestId("studio-agent-name-input"), {
      target: { value: "Coder" },
    });
    fireEvent.click(screen.getByTestId("studio-create-agent"));
    await waitFor(() =>
      expect(screen.getByTestId("studio-feedback")).toHaveTextContent("Agent 已创建"),
    );

    // -- 更新（U）：PUT /agents/{id}（Basic 面板）--
    const nameInput = await screen.findByTestId("basic-name-input");
    fireEvent.change(nameInput, { target: { value: "Coder2" } });
    fireEvent.click(screen.getByTestId("basic-save"));
    await waitFor(() =>
      expect(screen.getByTestId("studio-feedback")).toHaveTextContent("基础信息已保存"),
    );
  });

  it("Skills 面板可绑定 / 创建，且预览反映绑定数", async () => {
    renderStudio();

    fireEvent.click(await screen.findByTestId("studio-agent-a1"));
    fireEvent.click(screen.getByTestId("studio-nav-skills"));

    // 绑定既有 Skill。
    fireEvent.click(await screen.findByTestId("skill-bind-demo-skill"));
    await waitFor(() => expect(screen.getByTestId("studio-preview-skills")).toHaveTextContent("1"));

    // 创建并绑定新 Skill。
    fireEvent.change(screen.getByTestId("panel-skill-name-input"), {
      target: { value: "new-skill" },
    });
    fireEvent.click(screen.getByTestId("panel-skill-create"));
    await waitFor(() => expect(screen.getByTestId("studio-preview-skills")).toHaveTextContent("2"));
  });

  it("发布产生新 agent_version", async () => {
    renderStudio();

    fireEvent.click(await screen.findByTestId("studio-agent-a1"));
    fireEvent.click(screen.getByTestId("studio-publish"));
    await waitFor(() =>
      expect(screen.getByTestId("studio-feedback")).toHaveTextContent("已发布版本 1"),
    );
  });

  it("can() 权限守卫生效（缺少权限 → 阻止渲染）", async () => {
    useAuthStore.setState({ permissions: [] });
    renderStudio();

    expect(await screen.findByText("缺少权限：agent:create")).toBeInTheDocument();
    expect(screen.getByText("缺少权限：agent:publish")).toBeInTheDocument();
  });

  // V0.4.6 缺陷 L-4 / 批次 B2：默认语言 en 下不得露中文（选卡标题 / 按钮 / 分区说明）。
  it("i18n：切到 en → 选 Agent 卡与发布按钮为英文，不残留中文", async () => {
    useI18nStore.setState({ language: "en" });
    renderStudio();

    expect(await screen.findByText("Select Agent")).toBeInTheDocument();
    expect(screen.getByTestId("studio-create-agent")).toHaveTextContent("Create");
    expect(screen.getByTestId("studio-preview")).toHaveTextContent("Configuration & preview");
    expect(screen.getByTestId("studio-hub-nav")).toHaveAttribute("aria-label", "Studio pages");
    // 分区说明走 en 资源（Basic 分区）。
    expect(screen.getByTestId("studio-nav-basic")).toHaveTextContent("Name / description / status");

    // 批次 C1：进入 Basic 面板，面板正文同样走 en 资源。
    fireEvent.click(await screen.findByTestId("studio-agent-a1"));
    fireEvent.click(screen.getByTestId("studio-nav-basic"));
    expect(await screen.findByText("Basic information")).toBeInTheDocument();
    expect(screen.getByTestId("basic-save")).toHaveTextContent("Save basic info");
    expect(screen.queryByText("基础信息")).toBeNull();

    // 关键中文文案均已切到 en 资源。
    expect(screen.queryByText("选择 Agent")).toBeNull();
    expect(screen.queryByText("配置与预览")).toBeNull();
  });
});
