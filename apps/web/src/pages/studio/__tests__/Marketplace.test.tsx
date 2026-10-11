// ---------------------------------------------------------------------------
// Astra AI · Marketplace 单测（W8 / T2-44 · U-P2-30 / I-P2-18 部分）
//
// 覆盖：
//   ① 预检展示元数据（作者 / 版本 / 兼容范围 / 依赖 / 摘要 / 签名提示）；
//   ② confirm 导入（`status: IMPORTED`）；
//   ③ 校验 SHA-256（不匹配拒绝）；
//   ④ 导出 yaml 文本并下载；
//   ⑤ `can()` 权限守卫（`marketplace:import` / `marketplace:export`）。
//
// R14：前端不解析 yaml——上传 yaml 原文，元数据由后端返回；本测试以 msw 打桩后端契约。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Marketplace } from "@/pages/studio/Marketplace";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** 预检元数据夹具（`confirm=false`）。 */
const PREVIEW = {
  status: "PREVIEW",
  kind: "agent",
  name: "my-agent",
  version: "1.2.0",
  core_compat: ">=0.4.0,<0.5.0",
  author: "Alice",
  license: "MIT",
  dependencies: ["skill:foo@1.0.0"],
  manifest_path: "agent.yaml",
  artifact_sha256: "a".repeat(64),
  signature_present: false,
};

/** 导入结果夹具（`confirm=true`）。 */
const IMPORTED = {
  status: "IMPORTED",
  kind: "agent",
  name: "my-agent",
  version: "1.2.0",
  digest: "deadbeef",
};

/** 导出响应夹具。 */
const EXPORT = {
  yaml: "kind: agent\nname: my-agent\nversion: 1.2.0\n",
  kind: "agent",
  id: "a1",
  digest: "cafe",
};

/** 模块级 mock 引用（供下载断言）。 */
let createObjectURL: ReturnType<typeof vi.fn>;

/** 渲染 Marketplace（独立 QueryClient）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Marketplace />
    </QueryClientProvider>,
  );
}

describe("Marketplace", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    // 下载依赖 URL.createObjectURL（jsdom 未实现）→ 打桩。
    createObjectURL = vi.fn(() => "blob:mock");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });

    server.use(
      http.post("/api/v1/agent-studio/marketplace/import", async ({ request }) => {
        const body = (await request.json()) as { confirm?: boolean };
        return shell(body.confirm ? IMPORTED : PREVIEW);
      }),
      http.get("/api/v1/agent-studio/marketplace/export", () => shell(EXPORT)),
    );
  });

  it("预检展示元数据（含未签名提示）", async () => {
    renderPage();

    fireEvent.change(screen.getByTestId("marketplace-yaml-input"), {
      target: { value: "kind: agent\nname: my-agent\nversion: 1.2.0\n" },
    });
    fireEvent.click(screen.getByTestId("marketplace-preview-button"));

    expect(await screen.findByTestId("marketplace-preview")).toBeInTheDocument();
    expect(screen.getByTestId("marketplace-preview-kind")).toHaveTextContent("agent");
    expect(screen.getByTestId("marketplace-preview-name")).toHaveTextContent("my-agent");
    expect(screen.getByTestId("marketplace-preview-version")).toHaveTextContent("1.2.0");
    expect(screen.getByTestId("marketplace-preview-core-compat")).toHaveTextContent(
      ">=0.4.0,<0.5.0",
    );
    expect(screen.getByTestId("marketplace-preview-author")).toHaveTextContent("Alice");
    expect(screen.getByTestId("marketplace-preview-dependencies")).toHaveTextContent(
      "skill:foo@1.0.0",
    );
    expect(screen.getByTestId("marketplace-preview-sha")).toHaveTextContent("aaaa");
    expect(screen.getByTestId("marketplace-preview-signature")).toHaveTextContent("未签名");
  });

  it("confirm 导入产生 IMPORTED 结果", async () => {
    renderPage();

    fireEvent.change(screen.getByTestId("marketplace-yaml-input"), {
      target: { value: "kind: agent\nname: my-agent\nversion: 1.2.0\n" },
    });
    fireEvent.click(screen.getByTestId("marketplace-preview-button"));
    await screen.findByTestId("marketplace-preview");

    fireEvent.click(screen.getByTestId("marketplace-confirm-button"));
    const result = await screen.findByTestId("marketplace-import-result");
    expect(result).toHaveTextContent("已导入 agent/my-agent@1.2.0");
  });

  it("SHA-256 不匹配 → 拒绝且不展示预检", async () => {
    server.use(
      http.post("/api/v1/agent-studio/marketplace/import", () =>
        HttpResponse.json(
          { code: "VALIDATION_ERROR", message: "SHA-256 不匹配：拒绝安装", data: {} },
          { status: 400 },
        ),
      ),
    );
    renderPage();

    fireEvent.change(screen.getByTestId("marketplace-yaml-input"), {
      target: { value: "kind: agent\nname: my-agent\nversion: 1.2.0\n" },
    });
    fireEvent.change(screen.getByTestId("marketplace-expected-sha-input"), {
      target: { value: "deadbeef".repeat(8) },
    });
    fireEvent.click(screen.getByTestId("marketplace-preview-button"));

    await waitFor(() =>
      expect(screen.getByTestId("marketplace-feedback")).toHaveTextContent("SHA-256 不匹配"),
    );
    expect(screen.queryByTestId("marketplace-preview")).not.toBeInTheDocument();
  });

  it("导出 yaml 文本并可下载", async () => {
    renderPage();

    fireEvent.change(screen.getByTestId("marketplace-export-id-input"), {
      target: { value: "a1" },
    });
    fireEvent.click(screen.getByTestId("marketplace-export-button"));

    expect(await screen.findByTestId("marketplace-export-yaml")).toHaveValue(EXPORT.yaml);
    fireEvent.click(screen.getByTestId("marketplace-download"));
    expect(createObjectURL).toHaveBeenCalled();
  });

  it("can() 权限守卫生效（导入 / 导出）", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();

    expect(await screen.findByText("缺少权限：marketplace:import")).toBeInTheDocument();
    expect(screen.getByText("缺少权限：marketplace:export")).toBeInTheDocument();
  });
});
