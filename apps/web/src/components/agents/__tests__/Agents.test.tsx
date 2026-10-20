// ---------------------------------------------------------------------------
// WBTimeAI · Agents（智能页三 Tab）单测（V0.4.5 B4 · T04 · F-22.3~22.5）
//
// 覆盖：
//   ① 默认渲染「专家」Tab（无 `?tab=`）；
//   ② 切换 Tab → 面板切换 + URL 同步 `?tab=`（契约 `/agents?tab=<AgentsTab>`）；
//   ③ `?tab=connectors` 初始直达；非法 `?tab=` 回落 `experts`；
//   ④ 技能 Tab 骨架：搜索 / 已安装计数 / 添加与上传技能按钮及弹窗（F-27.3）/ 分组 / 启用开关（本地态）；
//   ⑤ 连接器 Tab 骨架：卡片网格 / 自定义连接器 / MCP 服务管理弹窗（列表态 ↔ JSON 编辑态）；
//   ⑥ 创建向导弹窗（F-27.2，B5）：Dialog 承载 `CreateAgentWizard`。
//
// - 只读数据源（`useAgents` / `useSkills` / `useMcp`）以 `vi.mock` 打桩（零网络）；
// - `useSkills` 经 `importOriginal` 保留真实 `toSkillListItems` 投影；
// - radix（tabs / dropdown-menu / dialog）浮层 → 补最小 jsdom 桩（对齐 Composer.test.tsx 范式）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { en } from "@/i18n/locales/en";
import { Agents } from "@/pages/Agents";
import { useAuthStore } from "@/stores/authStore";

// --- jsdom 补丁：radix（tabs / dropdown-menu / dialog / floating-ui）所需最小实现 ---
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

// --- 只读数据源打桩（零网络） ---
vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({
    data: [
      {
        id: "a1",
        name: "软件架构师",
        type: "assistant",
        status: "ACTIVE",
        workspace_id: null,
        description: null,
        created_by: "u1",
      },
    ],
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  // F-27.2：创建向导（Dialog 承载）挂载所需 mutation 桩。
  useCreateAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePublishAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

// F-27.2：创建向导挂载所需只读数据桩。
vi.mock("@/hooks/useModels", () => ({
  useProviders: () => ({ data: [], isLoading: false }),
  useProviderModels: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/hooks/useTools", () => ({
  useTools: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/hooks/useWorkspaces", () => ({
  useWorkspaces: () => ({ data: [], isLoading: false }),
}));

vi.mock("@/hooks/useMcp", () => ({
  useMcpServers: () => ({
    data: [
      {
        id: "m1",
        name: "GitHub",
        transport: "stdio",
        endpoint: null,
        command: "npx -y github-mcp",
        args: [],
        env_ref: {},
        status: "ACTIVE",
      },
    ],
    isLoading: false,
  }),
}));

// `useSkills`：仅覆盖 `useSkills`，保留真实 `toSkillListItems` 投影（`importOriginal`）。
vi.mock("@/hooks/useSkills", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSkills")>();
  return {
    ...actual,
    useSkills: () => ({
      data: [
        {
          id: "s1",
          name: "demo",
          display_name: "Demo",
          category: "util",
          status: "DRAFT",
          created_by: "u1",
        },
      ],
      isLoading: false,
    }),
  };
});

/** 位置探针：暴露当前 `location.search` 以断言 `?tab=` 契约。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

/** 渲染 Agents 页（独立 QueryClient + 路由上下文 + 位置探针；可注入 client 供 spy）。 */
function renderAgents(
  initialEntry = "/agents",
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
): QueryClient {
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Agents />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

/** 打开专家 Tab 创建向导弹窗（F-27.2：Dialog 承载）。 */
describe("Agents · 创建向导弹窗（V0.4.5 B5 · F-27.2）", () => {
  it("点击「创建 Agent」→ Dialog 承载 CreateAgentWizard", () => {
    renderAgents("/agents");

    fireEvent.click(screen.getByTestId("toggle-wizard"));
    expect(screen.getByTestId("agents-wizard-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("create-agent-wizard")).toBeInTheDocument();

    // 关闭弹窗 → 向导卸载。
    fireEvent.click(screen.getByTestId("dialog-close"));
    expect(screen.queryByTestId("agents-wizard-dialog")).toBeNull();
  });
});

describe("Agents · V0.4.5 B4 · F-22.3~22.5（三 Tab）", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, user: null });
  });

  it("默认渲染「专家」Tab（无 ?tab=，URL 不变）", () => {
    renderAgents();

    expect(screen.getByTestId("agents-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("agents-tab-experts")).toBeInTheDocument();
    // radix Tabs 保持非活动面板挂载（`data-state=inactive`）→ 以 `data-state` 断言激活态。
    expect(screen.getByTestId("agents-panel-experts")).toHaveAttribute("data-state", "active");
    expect(screen.getByTestId("agents-panel-skills")).toHaveAttribute("data-state", "inactive");
    expect(screen.getByTestId("agents-panel-connectors")).toHaveAttribute("data-state", "inactive");
    expect(screen.getByTestId("location-search").textContent ?? "").not.toContain("tab=");
  });

  it("切换「技能」Tab → 面板激活 + URL 同步 ?tab=skills", () => {
    renderAgents();

    // radix Tabs 在 `mousedown`（button 0）激活。
    fireEvent.mouseDown(screen.getByTestId("agents-tab-skills"), { button: 0, ctrlKey: false });

    expect(screen.getByTestId("agents-panel-skills")).toHaveAttribute("data-state", "active");
    expect(screen.getByTestId("agents-panel-experts")).toHaveAttribute("data-state", "inactive");
    expect(screen.getByTestId("location-search")).toHaveTextContent("tab=skills");
  });

  it("?tab=connectors 初始直达「连接器」Tab", () => {
    renderAgents("/agents?tab=connectors");

    expect(screen.getByTestId("agents-panel-connectors")).toHaveAttribute("data-state", "active");
    expect(screen.getByTestId("agents-panel-experts")).toHaveAttribute("data-state", "inactive");
  });

  it("非法 ?tab= 回落「专家」Tab", () => {
    renderAgents("/agents?tab=bogus");

    expect(screen.getByTestId("agents-panel-experts")).toHaveAttribute("data-state", "active");
  });

  it("技能 Tab 骨架：搜索 / 已安装计数 / 添加与上传按钮（F-27.3）/ 分组 / 启用开关（本地态）", async () => {
    renderAgents("/agents?tab=skills");

    expect(screen.getByTestId("agents-search-skills")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-installed-count")).toHaveTextContent(
      en["agents.skills.installedCount"].replace("{count}", "1"),
    );
    expect(screen.getByTestId("agents-skills-group-custom")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-group-market")).toBeInTheDocument();

    // 启用开关（本地 UI 骨架）。
    const toggle = screen.getByTestId("agents-skill-toggle-s1");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");

    // F-27.3：顶行「添加技能」+「上传技能」两个按钮（下拉已删除），依次并排。
    const add = screen.getByTestId("agents-skills-add");
    const upload = screen.getByTestId("agents-skills-upload");
    expect(add).toBeInTheDocument();
    expect(upload).toBeInTheDocument();
    expect(add.compareDocumentPosition(upload) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // 「添加技能」开弹窗：说明 + 技能市场占位空态；关闭后消失。
    fireEvent.click(add);
    expect(screen.getByTestId("agents-skills-add-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-add-dialog-empty")).toHaveTextContent(
      en["agents.skills.addDialog.marketPending"],
    );
    fireEvent.click(screen.getByTestId("dialog-close"));
    expect(screen.queryByTestId("agents-skills-add-dialog")).toBeNull();

    // 「上传技能」开弹窗：文件选择 + 提交占位禁用。
    fireEvent.click(upload);
    expect(screen.getByTestId("agents-skills-upload-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-upload-input")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-upload-submit")).toBeDisabled();
  });

  it("连接器 Tab 骨架：卡片网格 + 自定义连接器 + MCP 弹窗（列表态 ↔ JSON 编辑态）", () => {
    renderAgents("/agents?tab=connectors");

    expect(screen.getByTestId("agents-connector-card-m1")).toBeInTheDocument();
    expect(screen.getByTestId("agents-connectors-add-custom")).toBeInTheDocument();

    // 打开 MCP 服务管理弹窗 → 列表态。
    fireEvent.click(screen.getByTestId("agents-connectors-manage-mcp"));
    expect(screen.getByTestId("agents-mcp-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("agents-mcp-list")).toBeInTheDocument();
    expect(screen.getByTestId("agents-mcp-toggle-m1")).toBeInTheDocument();

    // 添加 MCP → JSON 编辑态（含配置路径 + 保存）。
    fireEvent.click(screen.getByTestId("agents-mcp-add"));
    expect(screen.getByTestId("agents-mcp-json-editor")).toBeInTheDocument();
    expect(screen.getByTestId("agents-mcp-json-save")).toBeInTheDocument();

    // 返回 → 列表态。
    fireEvent.click(screen.getByTestId("agents-mcp-json-back"));
    expect(screen.getByTestId("agents-mcp-list")).toBeInTheDocument();
  });

  it("MCP JSON 编辑态：非法 JSON 保存 → 报错不返回；合法 → 返回列表", () => {
    renderAgents("/agents?tab=connectors");
    fireEvent.click(screen.getByTestId("agents-connectors-manage-mcp"));
    fireEvent.click(screen.getByTestId("agents-mcp-add"));

    const editor = screen.getByTestId("agents-mcp-json-editor");
    fireEvent.change(editor, { target: { value: "{ not json" } });
    fireEvent.click(screen.getByTestId("agents-mcp-json-save"));
    expect(screen.getByTestId("agents-mcp-json-error")).toBeInTheDocument();
    expect(screen.queryByTestId("agents-mcp-list")).toBeNull();

    fireEvent.change(editor, { target: { value: '{ "mcpServers": {} }' } });
    fireEvent.click(screen.getByTestId("agents-mcp-json-save"));
    expect(screen.getByTestId("agents-mcp-list")).toBeInTheDocument();
  });
});

describe("Agents · V0.4.6 B-15（三 Tab 统一改版）", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, user: null });
  });

  it("H1 / 副标题 / 页头主按钮随 Tab 变化（pill Tab + 计数胶囊契约不变）", () => {
    renderAgents();

    // 缺省专家 Tab：H1=专家、主按钮=创建专家（testid 沿用 toggle-wizard）。
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent(en["agents.tabTitle.experts"]);
    expect(screen.getByTestId("toggle-wizard")).toHaveTextContent(en["agents.create"]);
    // 计数胶囊仍在标签内（mock：专家 1 / 技能 1 / 连接器 1）。
    expect(screen.getByTestId("agents-tab-count-experts")).toHaveTextContent("1");
    expect(screen.getByTestId("agents-tab-count-skills")).toHaveTextContent("1");
    expect(screen.getByTestId("agents-tab-count-connectors")).toHaveTextContent("1");

    // 技能 Tab：H1=技能、主按钮=添加技能（testid 沿用 agents-skills-add）。
    fireEvent.mouseDown(screen.getByTestId("agents-tab-skills"), { button: 0, ctrlKey: false });
    expect(h1).toHaveTextContent(en["agents.tabTitle.skills"]);
    expect(screen.queryByTestId("toggle-wizard")).toBeNull();
    expect(screen.getByTestId("agents-skills-add")).toHaveTextContent(en["agents.skills.add"]);

    // 连接器 Tab：H1=连接器、主按钮=MCP 服务管理（testid 沿用 agents-connectors-manage-mcp）。
    fireEvent.mouseDown(screen.getByTestId("agents-tab-connectors"), { button: 0, ctrlKey: false });
    expect(h1).toHaveTextContent(en["agents.tabTitle.connectors"]);
    expect(screen.queryByTestId("agents-skills-add")).toBeNull();
    expect(screen.getByTestId("agents-connectors-manage-mcp")).toHaveTextContent(
      en["agents.mcp.title"],
    );
  });

  it("页头主按钮随 Tab 打开对应弹窗（技能=添加技能弹窗 / 连接器=MCP 服务管理弹窗）", () => {
    renderAgents();

    fireEvent.mouseDown(screen.getByTestId("agents-tab-skills"), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByTestId("agents-skills-add"));
    expect(screen.getByTestId("agents-skills-add-dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("dialog-close"));
    expect(screen.queryByTestId("agents-skills-add-dialog")).toBeNull();

    fireEvent.mouseDown(screen.getByTestId("agents-tab-connectors"), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByTestId("agents-connectors-manage-mcp"));
    expect(screen.getByTestId("agents-mcp-dialog")).toBeInTheDocument();
  });

  it("刷新随 Tab 失效对应 queryKey（experts→agents / skills→skills / connectors→mcpServers）", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const spy = vi.spyOn(client, "invalidateQueries");
    renderAgents("/agents", client);

    fireEvent.click(screen.getByTestId("agents-refresh"));
    expect(spy).toHaveBeenCalledWith({ queryKey: ["agents"] });

    fireEvent.mouseDown(screen.getByTestId("agents-tab-skills"), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByTestId("agents-refresh"));
    expect(spy).toHaveBeenCalledWith({ queryKey: ["skills"] });

    fireEvent.mouseDown(screen.getByTestId("agents-tab-connectors"), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByTestId("agents-refresh"));
    expect(spy).toHaveBeenCalledWith({ queryKey: ["mcp", "servers"] });
  });
});
