// ---------------------------------------------------------------------------
// WBTimeAI · Projects 单测（W10 / T2-50 · U-P2-17/30；V0.4.6 B-22 重排后更新）
//
// 覆盖：
//   ① 工作区列表选择 → 项目台账 + 新建弹窗创建；
//   ② 文件浏览器：列表；**Files 未装配（503）→ 降级态**「文件能力未装配（需 Storage）」；
//   ③ Environment 面板：敏感项 `masked=true` **只读引用**（`ref`），不展示明文；
//   ④ Git 面板（W10-E1）：展示 Project 元信息 + 降级标注，**无伪造实时状态**；
//   ⑤ `RequirePermission` 守卫（无 `project:create` 权限时新建入口被拦）；
//   ⑥ B-22 新增：副标题（工作区 + 项目数）/ 纯前端搜索 / 切换工作区清空上下文 /
//      未选工作区空态 + 主按钮 disabled / 「在远程工作台打开」带 workspace+project 上下文。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { Projects } from "@/pages/Projects";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

// Radix Dialog / 滚动定位依赖的 jsdom 缺失 API（指针捕获 / 滚动 / ResizeObserver）。
beforeAll(() => {
  const proto = Element.prototype as Element & {
    hasPointerCapture?: (pointerId: number) => boolean;
    setPointerCapture?: (pointerId: number) => void;
    releasePointerCapture?: (pointerId: number) => void;
  };
  if (typeof proto.hasPointerCapture !== "function") {
    proto.hasPointerCapture = () => false;
  }
  if (typeof proto.setPointerCapture !== "function") {
    proto.setPointerCapture = () => {};
  }
  if (typeof proto.releasePointerCapture !== "function") {
    proto.releasePointerCapture = () => {};
  }
  if (typeof HTMLElement.prototype.scrollIntoView !== "function") {
    HTMLElement.prototype.scrollIntoView = () => {};
  }
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as unknown as typeof ResizeObserver;
  }
});

/** 工作区夹具 A（B-22 左列上下文）。 */
const WORKSPACE_A = {
  id: "w1",
  tenant_id: "t1",
  owner_id: "u1",
  name: "Demo Workspace",
  workspace_type: "TEAM",
  settings: {},
  config: {},
  created_at: "2026-10-10T09:12:00",
  updated_at: "2026-10-18T17:20:00",
};

/** 工作区夹具 B（用于「切换工作区清空上下文」）。 */
const WORKSPACE_B = { ...WORKSPACE_A, id: "w2", name: "Sandbox", workspace_type: "PERSONAL" };

/** 项目夹具 A（`ProjectResponse`）。 */
const PROJECT_A = {
  id: "p1",
  tenant_id: "t1",
  organization_id: null,
  workspace_id: "w1",
  name: "Demo",
  description: null,
  repo_url: "https://git.example.com/demo.git",
  default_branch: "main",
  settings: { linter: "ruff" },
  created_at: "2026-10-13T00:00:00",
  updated_at: "2026-10-13T00:00:00",
};

/** 项目夹具 B（搜索过滤用例：仓库片段 `console-web` 只应命中这一行）。 */
const PROJECT_B = {
  ...PROJECT_A,
  id: "p2",
  name: "Console Web",
  repo_url: "https://git.example.com/console-web.git",
  default_branch: "develop",
};

/** 创建项目的返回值（201）。 */
const PROJECT_CREATED = { ...PROJECT_A, id: "p3", name: "NewProj" };

/** 文件对象夹具（`FileObjectResponse`）。 */
const FILE = {
  key: "workspaces/w1/README.md",
  size: 12,
  content_type: "text/markdown",
  etag: "abc",
  created_at: "2026-10-13T00:00:00",
};

/** 文件内容夹具（base64 "hello"）。 */
const FILE_CONTENT = {
  path: "workspaces/w1/README.md",
  size: 5,
  encoding: "base64",
  content_base64: "aGVsbG8=",
};

/** 环境夹具（`EnvironmentResponse`）：含 1 明文 + 1 敏感引用。 */
const ENV = {
  id: "env1",
  tenant_id: "t1",
  organization_id: null,
  workspace_id: "w1",
  name: "dev",
  env_vars: [
    { name: "PLAIN", value: "hello", ref: null, masked: false },
    { name: "API_TOKEN", value: null, ref: "secret:MY_TOKEN", masked: true },
  ],
  runtime: { python: "3.12" },
  created_at: "2026-10-13T00:00:00",
  updated_at: "2026-10-13T00:00:00",
};

/** 统一失败壳（503 降级）。 */
function unavailable() {
  return HttpResponse.json(
    {
      code: "DEPENDENCY_MISSING",
      message: "工作区文件能力未装配（缺 Storage 注入）",
      data: {},
      request_id: "test-request",
    },
    { status: 503 },
  );
}

/** 渲染 Projects（独立 QueryClient + Router 上下文，禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects"]}>
        <Projects />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 选择左侧工作区（列表项为按钮，B-22 起取代原下拉选择器）。 */
async function selectWorkspace(workspaceId = "w1") {
  fireEvent.click(await screen.findByTestId(`workspace-item-${workspaceId}`));
}

describe("Projects", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/workspaces", () => shell([WORKSPACE_A, WORKSPACE_B])),
      http.get("/api/v1/projects", () => shell([PROJECT_A, PROJECT_B])),
      http.post("/api/v1/projects", () => shell(PROJECT_CREATED, 201)),
      http.get("/api/v1/projects/:projectId", () => shell(PROJECT_A)),
      http.get("/api/v1/workspaces/:workspaceId/files", () => shell([FILE])),
      http.get("/api/v1/workspaces/:workspaceId/files/content", () => shell(FILE_CONTENT)),
      http.get("/api/v1/workspaces/:workspaceId/environment", () => shell([ENV])),
      http.get("/api/v1/workspaces/:workspaceId/environment/:envId", () => shell(ENV)),
    );
  });

  it("选择工作区展示项目列表，并通过弹窗创建项目", async () => {
    renderPage();
    await selectWorkspace();

    expect(await screen.findByTestId("project-row-p1")).toHaveTextContent("Demo");

    // B-22：创建入口改为页头主按钮 → 弹窗内填写 → 提交。
    fireEvent.click(screen.getByTestId("project-create-open"));
    fireEvent.change(await screen.findByTestId("project-name-input"), {
      target: { value: "NewProj" },
    });
    fireEvent.click(screen.getByTestId("project-create-button"));

    expect(await screen.findByTestId("projects-feedback")).toHaveTextContent("已创建项目 NewProj");
  });

  it("副标题展示当前工作区与项目数", async () => {
    renderPage();
    await selectWorkspace();

    await waitFor(() =>
      expect(screen.getByTestId("projects-subtitle")).toHaveTextContent(
        "当前工作区：Demo Workspace · 共 2 个项目",
      ),
    );
  });

  it("台账搜索按仓库片段过滤（纯前端）", async () => {
    renderPage();
    await selectWorkspace();
    expect(await screen.findByTestId("project-row-p2")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("projects-search"), {
      target: { value: "console-web" },
    });

    await waitFor(() => expect(screen.queryByTestId("project-row-p1")).toBeNull());
    expect(screen.getByTestId("project-row-p2")).toBeInTheDocument();
    expect(screen.getByTestId("projects-total")).toHaveTextContent("共 1 个");
  });

  it("切换工作区清空选中项目与搜索关键词", async () => {
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));
    expect(await screen.findByTestId("project-detail")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("projects-search"), { target: { value: "demo" } });
    expect(screen.getByTestId("projects-search")).toHaveValue("demo");

    await selectWorkspace("w2");

    await waitFor(() => expect(screen.queryByTestId("project-detail")).toBeNull());
    expect(screen.getByTestId("projects-search")).toHaveValue("");
  });

  it("未选工作区：内联空态 + 新建按钮 disabled", async () => {
    renderPage();

    expect(await screen.findByTestId("projects-hint")).toHaveTextContent("选择左侧工作区");

    const createButton = screen.getByTestId("project-create-open");
    expect(createButton).toBeDisabled();
    expect(createButton).toHaveAttribute("title", "请先选择工作区");
  });

  it("Git 面板展示元信息 + 降级标注（不伪造实时状态）", async () => {
    renderPage();
    await selectWorkspace();

    fireEvent.click(await screen.findByTestId("project-select-p1"));

    expect(await screen.findByTestId("project-detail")).toBeInTheDocument();
    expect(screen.getByTestId("project-repo-url")).toHaveTextContent(
      "https://git.example.com/demo.git",
    );
    expect(screen.getByTestId("project-default-branch")).toHaveTextContent("main");
    expect(screen.getByTestId("project-git-degrade")).toHaveTextContent(
      "实时 Git 状态需 Sandbox 装配（R1/R3 增量）",
    );
  });

  it("详情卡「在远程工作台打开」带 workspace / project 上下文", async () => {
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));

    const link = await screen.findByTestId("project-open-remote");
    expect(link).toHaveAttribute("href", "/remote-tasks?workspace=w1&project=p1");
  });

  it("文件浏览器：列表 + 内容预览", async () => {
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));
    fireEvent.click(await screen.findByTestId("project-detail-tab-files"));

    expect(await screen.findByTestId("file-row-workspaces/w1/README.md")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("file-preview-workspaces/w1/README.md"));
    await waitFor(() => expect(screen.getByTestId("file-preview")).toHaveTextContent("hello"));
  });

  it("文件能力未装配（503）→ 降级态", async () => {
    server.use(http.get("/api/v1/workspaces/:workspaceId/files", () => unavailable()));
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));
    fireEvent.click(await screen.findByTestId("project-detail-tab-files"));

    expect(await screen.findByTestId("files-degrade")).toHaveTextContent(
      "文件能力未装配（需 Storage）",
    );
  });

  it("Environment 面板：敏感项只读引用、不回显明文", async () => {
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));
    fireEvent.click(await screen.findByTestId("project-detail-tab-env"));

    fireEvent.click(await screen.findByTestId("environment-row-env1"));
    expect(await screen.findByTestId("environment-detail")).toBeInTheDocument();

    // 非敏感项展示明文值。
    expect(screen.getByTestId("env-var-value-PLAIN")).toHaveTextContent("hello");
    // 敏感项仅展示引用（masked）。
    expect(screen.getByTestId("env-var-ref-API_TOKEN")).toHaveTextContent("secret:MY_TOKEN");
  });

  it("详情 Tab 常驻挂载：切换分段不丢失文件面板输入", async () => {
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));

    fireEvent.click(await screen.findByTestId("project-detail-tab-files"));
    fireEvent.change(screen.getByTestId("files-prefix-input"), { target: { value: "src/" } });
    expect(screen.getByTestId("files-prefix-input")).toHaveValue("src/");

    fireEvent.click(screen.getByTestId("project-detail-tab-git"));
    fireEvent.click(screen.getByTestId("project-detail-tab-files"));

    expect(screen.getByTestId("files-prefix-input")).toHaveValue("src/");
  });

  it("RequirePermission 守卫：无 project:create 权限时新建入口被拦", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();
    await selectWorkspace();

    // 语言无关断言：本文件不设语言（默认 `en`），故不能断言中文文案；
    // 改为锚点 `data-permission-code`（`RequirePermission` 稳定契约）。
    const denied = await screen.findAllByTestId("permission-denied");
    expect(denied.some((el) => el.getAttribute("data-permission-code") === "project:create")).toBe(
      true,
    );
  });
});
