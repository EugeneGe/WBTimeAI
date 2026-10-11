// ---------------------------------------------------------------------------
// Astra AI · Projects 单测（W10 / T2-50 · U-P2-17/30）
//
// 覆盖：
//   ① Workspace 选择 → Project 列表展示 + 创建；
//   ② 文件浏览器：404/列表；**Files 未装配（503）→ 降级态**「文件能力未装配（需 Storage）」；
//   ③ Environment 面板：敏感项 `masked=true` **只读引用**（`ref`），不展示明文；
//   ④ Git 面板（W10-E1）：展示 Project 元信息 + 降级标注，**无伪造实时状态**；
//   ⑤ `can()` / `RequirePermission` 守卫（无 `project:create` 权限时新建按钮被拦）。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { Projects } from "@/pages/Projects";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** 项目夹具（`ProjectResponse`）。 */
const PROJECT = {
  id: "p1",
  tenant_id: "t1",
  organization_id: null,
  workspace_id: "w1",
  name: "Demo",
  description: null,
  repo_url: "https://git.example.com/demo.git",
  default_branch: "main",
  settings: { linter: "ruff" },
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
};

/** 创建项目返回值。 */
const PROJECT_2 = { ...PROJECT, id: "p2", name: "NewProj" };

/** 文件对象夹具（`FileObjectResponse`）。 */
const FILE = {
  key: "workspaces/w1/README.md",
  size: 12,
  content_type: "text/markdown",
  etag: "abc",
  created_at: "2026-10-13T00:00:00Z",
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
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
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

/** 渲染 Projects（独立 QueryClient，禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Projects />
    </QueryClientProvider>,
  );
}

/** 选择默认工作区（等待 option 就位后 change）。 */
async function selectWorkspace() {
  await screen.findByRole("option", { name: "Demo Workspace" });
  fireEvent.change(screen.getByTestId("workspace-select"), { target: { value: "w1" } });
}

describe("Projects", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/projects", () => shell([PROJECT])),
      http.post("/api/v1/projects", () => shell(PROJECT_2, 201)),
      http.get("/api/v1/projects/:projectId", () => shell(PROJECT)),
      http.get("/api/v1/workspaces/:workspaceId/files", () => shell([FILE])),
      http.get("/api/v1/workspaces/:workspaceId/files/content", () => shell(FILE_CONTENT)),
      http.get("/api/v1/workspaces/:workspaceId/environment", () => shell([ENV])),
      http.get("/api/v1/workspaces/:workspaceId/environment/:envId", () => shell(ENV)),
    );
  });

  it("选择工作区展示项目列表并可创建", async () => {
    renderPage();
    await selectWorkspace();

    expect(await screen.findByTestId("project-row-p1")).toHaveTextContent("Demo");

    fireEvent.change(screen.getByTestId("project-name-input"), { target: { value: "NewProj" } });
    fireEvent.click(screen.getByTestId("project-create-button"));

    expect(await screen.findByTestId("projects-feedback")).toHaveTextContent("已创建项目 NewProj");
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

  it("文件浏览器：列表 + 内容预览", async () => {
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));

    expect(await screen.findByTestId("file-row-workspaces/w1/README.md")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("file-preview-workspaces/w1/README.md"));
    await waitFor(() => expect(screen.getByTestId("file-preview")).toHaveTextContent("hello"));
  });

  it("文件能力未装配（503）→ 降级态", async () => {
    server.use(http.get("/api/v1/workspaces/:workspaceId/files", () => unavailable()));
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));

    expect(await screen.findByTestId("files-degrade")).toHaveTextContent(
      "文件能力未装配（需 Storage）",
    );
  });

  it("Environment 面板：敏感项只读引用、不回显明文", async () => {
    renderPage();
    await selectWorkspace();
    fireEvent.click(await screen.findByTestId("project-select-p1"));

    fireEvent.click(await screen.findByTestId("environment-row-env1"));
    expect(await screen.findByTestId("environment-detail")).toBeInTheDocument();

    // 非敏感项展示明文值。
    expect(screen.getByTestId("env-var-value-PLAIN")).toHaveTextContent("hello");
    // 敏感项仅展示引用（masked）。
    expect(screen.getByTestId("env-var-ref-API_TOKEN")).toHaveTextContent("secret:MY_TOKEN");
  });

  it("can() 守卫：无 project:create 权限时新建按钮被拦", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();
    await selectWorkspace();

    expect(await screen.findByText("缺少权限：project:create")).toBeInTheDocument();
  });
});
