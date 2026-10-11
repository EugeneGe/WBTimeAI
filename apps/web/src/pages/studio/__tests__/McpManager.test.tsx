// ---------------------------------------------------------------------------
// Astra AI · McpManager 单测（W3 / T2-18；W10 / T2-52 补强 · U-P2-17 / U-P2-30）
//
// 覆盖：
//   ① Server 注册 → 反馈；凭据**仅掩码**（绝不回显明文引用）；
//   ② 工具发现 / 删除 → 反馈；
//   ③ `usePermissionCheck` 展示**后端** capability 判定（`mcp:delete`）；
//   ④ `can()` 守卫：无 `mcp:create` / `mcp:discover` / `mcp:delete` 时动作不渲染。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { McpManager } from "@/pages/studio/McpManager";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** MCP Server 夹具（`credential_id` = 引用，页面必须掩码）。 */
const SERVER = {
  id: "m1",
  tenant_id: "t1",
  name: "fs",
  transport: "stdio",
  endpoint: null,
  command: "npx -y mcp-fs",
  args: [],
  env_ref: {},
  credential_id: "cred-12345678",
  status: "ACTIVE",
  workspace_id: null,
  created_at: null,
};

/** 权限判定夹具（后端 capability）。 */
const PERM_CHECK = {
  capability: "mcp:delete",
  allowed: true,
  effect: "ALLOW",
  reason: "",
  source: null,
};

/** 渲染 McpManager（独立 QueryClient；禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <McpManager />
    </QueryClientProvider>,
  );
}

describe("McpManager", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/mcp/servers", () => shell([SERVER])),
      http.get("/api/v1/permissions/check", () => shell(PERM_CHECK)),
      http.get("/api/v1/mcp/tools", () => shell([])),
      http.get("/api/v1/mcp/permissions", () => shell([])),
      http.post("/api/v1/mcp/servers", () => shell({ ...SERVER, id: "m2", name: "new" }, 201)),
      http.delete("/api/v1/mcp/servers/:serverId", () => new HttpResponse(null, { status: 204 })),
      http.post("/api/v1/mcp/servers/:serverId/discover", () => shell([])),
    );
  });

  it("展示 Server（凭据掩码）并展示后端 capability 判定", async () => {
    renderPage();

    expect(await screen.findByTestId("mcp-server-fs")).toBeInTheDocument();
    // 凭据仅掩码：不回显明文引用。
    const credential = screen.getByTestId("mcp-credential-fs");
    expect(credential).toHaveTextContent("••••5678");
    expect(credential).not.toHaveTextContent("cred-12345678");
    // `usePermissionCheck`（后端判定）→ 徽标。
    expect(await screen.findByText("mcp:delete 允许")).toBeInTheDocument();
  });

  it("注册 Server → 反馈", async () => {
    renderPage();

    await screen.findByTestId("mcp-server-fs");
    fireEvent.change(screen.getByTestId("mcp-name-input"), { target: { value: "new" } });
    fireEvent.change(screen.getByTestId("mcp-credential-input"), {
      target: { value: "cred-ref-1" },
    });
    fireEvent.click(screen.getByTestId("mcp-register-submit"));

    expect(await screen.findByTestId("mcp-feedback")).toHaveTextContent("Server 已注册");
  });

  it("发现工具 / 删除 Server → 反馈", async () => {
    renderPage();

    await screen.findByTestId("mcp-server-fs");

    fireEvent.click(screen.getByRole("button", { name: "发现" }));
    expect(await screen.findByTestId("mcp-feedback")).toHaveTextContent("发现 0 个工具");

    fireEvent.click(screen.getByTestId("mcp-delete-fs"));
    expect(await screen.findByTestId("mcp-feedback")).toHaveTextContent("Server 已删除");
  });

  it("can() 守卫：无 mcp:create / mcp:discover / mcp:delete 权限时动作不渲染", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();

    expect(await screen.findByTestId("mcp-server-fs")).toBeInTheDocument();
    expect(screen.getByText("缺少权限：mcp:create")).toBeInTheDocument();
    expect(screen.getByText("缺少权限：mcp:discover")).toBeInTheDocument();
    expect(screen.getByText("缺少权限：mcp:delete")).toBeInTheDocument();
    // 动作按钮不渲染。
    expect(screen.queryByTestId("mcp-register-submit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mcp-delete-fs")).not.toBeInTheDocument();
  });
});
